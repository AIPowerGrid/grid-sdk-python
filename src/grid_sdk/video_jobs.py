# SPDX-License-Identifier: MIT
"""Candidate credit-backed video jobs. No POST retries or asset downloads."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Literal, Mapping, Optional, TypedDict, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx

SCHEMA = "aipg.video-job.v1"
FEATURE = "video-async-credit-jobs-v1"
SOURCE_FEATURE = "video-source-conditioning-v1"
MAX_JSON = 64 * 1024
MAX_BODY = 64 * 1024 * 1024 + MAX_JSON
MAX_MONEY = 2**53 - 1  # Exact in both SDK languages.
STATES = {
    "pending_dispatch",
    "queued",
    "execution_uncertain",
    "completed",
    "closed_without_result",
}
TERMINAL = {"completed", "closed_without_result"}


class VideoMedia(TypedDict):
    url: str
    key: str
    sha256: str
    seed: Optional[int]


class VideoResult(TypedDict):
    model: str
    worker: str
    gen_time: float
    recipe_root: Optional[str]
    media: List[VideoMedia]


class VideoJob(TypedDict):
    schema: str
    job_id: str
    model: str
    state: Literal[
        "pending_dispatch",
        "queued",
        "execution_uncertain",
        "completed",
        "closed_without_result",
    ]
    request_hash: str
    reserved_micro: int
    max_cost_micro: int
    actual_micro: Optional[int]
    result: Optional[VideoResult]


class VideoJobError(RuntimeError):
    """Sanitized failure. Preserve the key/receipt when submission is uncertain."""

    def __init__(
        self,
        kind: str,
        *,
        http_status: Optional[int] = None,
        submission_uncertain: bool = False,
    ):
        self.kind = kind
        self.http_status = http_status
        self.submission_uncertain = submission_uncertain
        super().__init__(
            f"Grid video job {kind}" + (f" (HTTP {http_status})" if http_status else "")
        )


def _positive(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < value <= 2_147_483.647
        or not math.isfinite(value)
    ):
        raise ValueError("timeouts and poll intervals must be positive and finite")
    return value


def _uuid(value: str, *, key: bool = False) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            "use a canonical UUIDv4 key or canonical UUID job id"
        ) from None
    if str(parsed) != value or (key and parsed.version != 4):
        raise ValueError("use a canonical UUIDv4 key or canonical UUID job id")
    return value


def _headers(
    api_key: str, user_token: Optional[str], key: Optional[str]
) -> Dict[str, str]:
    values = [api_key] + ([user_token] if user_token is not None else [])
    if any(
        not isinstance(value, str)
        or not value
        or any(not 32 <= ord(char) <= 126 for char in value)
        for value in values
    ):
        raise ValueError("credentials must be nonempty printable ASCII header values")
    result = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if user_token is not None:
        result["X-Grid-User-Token"] = user_token
    if key is not None:
        result["Idempotency-Key"] = _uuid(key, key=True)
    return result


def _selector(job_id: Optional[str], key: Optional[str]) -> str:
    if (job_id is None) == (key is None):
        raise ValueError("provide exactly one of job_id and idempotency_key")
    return "/videos/jobs/" + _uuid(job_id) if job_id is not None else "/videos/jobs"


def _money(value: object, *, zero: bool = False) -> bool:
    return type(value) is int and (0 if zero else 1) <= value <= MAX_MONEY


def _status(value: object) -> VideoJob:
    if not isinstance(value, dict):
        raise VideoJobError("invalid_response")
    try:
        _uuid(value["job_id"])
        state = value["state"]
        if (
            value["schema"] != SCHEMA
            or state not in STATES
            or not isinstance(value["model"], str)
            or not 1 <= len(value["model"]) <= 255
            or not isinstance(value["request_hash"], str)
            or not re.fullmatch("[0-9a-f]{64}", value["request_hash"])
            or not _money(value["reserved_micro"])
            or not _money(value["max_cost_micro"])
            or value["reserved_micro"] > value["max_cost_micro"]
        ):
            raise ValueError
        actual, result = value["actual_micro"], value["result"]
        if actual is not None and (
            not _money(actual, zero=True) or actual > value["max_cost_micro"]
        ):
            raise ValueError
        if state not in TERMINAL and (actual is not None or result is not None):
            raise ValueError
        if state == "completed":
            if (
                actual is None
                or not isinstance(result, dict)
                or result["model"] != value["model"]
            ):
                raise ValueError
            if (
                not isinstance(result["worker"], str)
                or len(result["worker"]) > 255
                or isinstance(result["gen_time"], bool)
                or not isinstance(result["gen_time"], (int, float))
                or not math.isfinite(result["gen_time"])
                or result["gen_time"] < 0
                or not isinstance(result["media"], list)
                or len(result["media"]) != 1
                or (
                    result.get("recipe_root") is not None
                    and (
                        not isinstance(result["recipe_root"], str)
                        or len(result["recipe_root"]) > 255
                    )
                )
            ):
                raise ValueError
            item = result["media"][0]
            url = urlsplit(item["url"])
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or not isinstance(item["key"], str)
                or not 1 <= len(item["key"]) <= 2048
                or not re.fullmatch("[0-9a-f]{64}", item["sha256"])
                or (
                    item.get("seed") is not None and not _money(item["seed"], zero=True)
                )
            ):
                raise ValueError
        elif result is not None:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError, IndexError):
        raise VideoJobError("invalid_response") from None
    return cast(VideoJob, value)


def _bound(current: VideoJob, expected: Mapping[str, object]) -> VideoJob:
    fields = cast(Mapping[str, object], current)
    if any(
        fields[field] != expected[field]
        for field in (
            "job_id",
            "model",
            "request_hash",
            "reserved_micro",
            "max_cost_micro",
        )
    ):
        raise VideoJobError("changed_identity")
    return current


@dataclass(frozen=True)
class _Submission:
    encoded: bytes
    model: str
    ceiling: int
    source: bool


def _submission(body: Mapping[str, object]) -> _Submission:
    try:
        encoded = json.dumps(dict(body), allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(encoded) > MAX_BODY:
            raise ValueError
        snapshot = json.loads(encoded)
        if (
            not isinstance(snapshot.get("model"), str)
            or not 1 <= len(snapshot["model"]) <= 255
            or not isinstance(snapshot.get("prompt"), str)
            or not 1 <= len(snapshot["prompt"]) <= 8000
            or not _money(snapshot.get("max_cost_micro_usd"))
            or type(snapshot.get("n", 1)) is not int
            or snapshot.get("n", 1) != 1
            or (snapshot.get("image") and snapshot.get("keyframes"))
            or (
                snapshot.get("reference_video")
                and (not snapshot.get("reference_audio") or not snapshot.get("size"))
            )
        ):
            raise ValueError
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError(
            "invalid video body; explicit model, prompt and positive exact cost ceiling required"
        ) from None
    return _Submission(
        encoded,
        snapshot["model"],
        snapshot["max_cost_micro_usd"],
        bool(snapshot.get("reference_audio") or snapshot.get("reference_video")),
    )


def _decode(raw: bytes) -> object:
    try:
        return json.loads(raw, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise VideoJobError("invalid_response") from None


def _invalid_constant(value: str) -> object:
    raise ValueError("nonfinite JSON is invalid")


def _features(value: object) -> List[str]:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("features"), list)
        or not all(isinstance(item, str) for item in value["features"])
    ):
        raise VideoJobError("invalid_capabilities")
    return cast(List[str], value["features"])


def _accepted(value: object, code: int, submission: _Submission) -> VideoJob:
    status = _status(value)
    if (
        status["model"] != submission.model
        or status["max_cost_micro"] != submission.ceiling
        or code != (200 if status["state"] in TERMINAL else 202)
    ):
        raise VideoJobError("invalid_response")
    return status


class _VideoBase:
    def __init__(self, api_key: str, base_url: str):
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or not url.path.rstrip("/").endswith("/v1")
        ):
            raise ValueError(
                "video jobs require an http(s) /v1 base without credentials, query or fragment"
            )
        _headers(api_key, None, None)
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._health = self._base[:-3] + "/health"


class VideoJobs(_VideoBase):
    """Persist key + body before submit; recover/wait only GET the existing job."""

    def _request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        timeout: float,
        body: Optional[bytes] = None,
    ) -> tuple[object, int]:
        deadline = time.monotonic() + _positive(timeout)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                with client.stream(
                    method, url, headers=headers, content=body
                ) as response:
                    if response.status_code not in (
                        {200, 202} if method == "POST" else {200}
                    ):
                        raise VideoJobError(
                            "http_error", http_status=response.status_code
                        )
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline:
                            raise VideoJobError("deadline")
                        if len(data) + len(chunk) > MAX_JSON:
                            raise VideoJobError("response_too_large")
                        data.extend(chunk)
                    return _decode(bytes(data)), response.status_code
        except httpx.HTTPError:
            raise VideoJobError("transport_error") from None

    def capabilities(self, *, timeout: float = 30.0) -> List[str]:
        """Contract features, not permission, pricing or worker availability."""
        return _features(self._request("GET", self._health, {}, timeout)[0])

    def submit(
        self,
        body: Mapping[str, object],
        *,
        idempotency_key: str,
        user_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> VideoJob:
        submission = _submission(body)
        headers = _headers(self._key, user_token, idempotency_key)
        features = self.capabilities(timeout=timeout)
        if FEATURE not in features or (
            submission.source and SOURCE_FEATURE not in features
        ):
            raise VideoJobError("contract_unavailable")
        try:
            value, code = self._request(
                "POST",
                self._base + "/videos/jobs",
                headers,
                timeout,
                submission.encoded,
            )
            return _accepted(value, code, submission)
        except VideoJobError as exc:
            raise VideoJobError(
                exc.kind, http_status=exc.http_status, submission_uncertain=True
            ) from None

    def recover(
        self,
        *,
        job_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        user_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> VideoJob:
        path = _selector(job_id, idempotency_key)
        status = _status(
            self._request(
                "GET",
                self._base + path,
                _headers(self._key, user_token, idempotency_key),
                timeout,
            )[0]
        )
        if job_id is not None and status["job_id"] != job_id:
            raise VideoJobError("changed_identity")
        return status

    def wait(
        self,
        receipt: VideoJob,
        *,
        user_token: Optional[str] = None,
        timeout: float = 600.0,
        poll_interval: float = 5.0,
        request_timeout: float = 30.0,
    ) -> VideoJob:
        deadline = time.monotonic() + _positive(timeout)
        _positive(poll_interval)
        _positive(request_timeout)
        anchor = dict(_status(receipt))
        status = _status(receipt)
        while status["state"] not in TERMINAL:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VideoJobError("deadline")
            status = _bound(
                self.recover(
                    job_id=status["job_id"],
                    user_token=user_token,
                    timeout=min(remaining, request_timeout),
                ),
                anchor,
            )
            if status["state"] not in TERMINAL:
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
        return status


class AsyncVideoJobs(_VideoBase):
    """Async twin of VideoJobs; cancellation never triggers a replacement POST."""

    async def _request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        timeout: float,
        body: Optional[bytes] = None,
    ) -> tuple[object, int]:
        deadline = time.monotonic() + _positive(timeout)
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False
            ) as client:
                async with client.stream(
                    method, url, headers=headers, content=body
                ) as response:
                    if response.status_code not in (
                        {200, 202} if method == "POST" else {200}
                    ):
                        raise VideoJobError(
                            "http_error", http_status=response.status_code
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if time.monotonic() >= deadline:
                            raise VideoJobError("deadline")
                        if len(data) + len(chunk) > MAX_JSON:
                            raise VideoJobError("response_too_large")
                        data.extend(chunk)
                    return _decode(bytes(data)), response.status_code
        except httpx.HTTPError:
            raise VideoJobError("transport_error") from None

    async def capabilities(self, *, timeout: float = 30.0) -> List[str]:
        return _features((await self._request("GET", self._health, {}, timeout))[0])

    async def submit(
        self,
        body: Mapping[str, object],
        *,
        idempotency_key: str,
        user_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> VideoJob:
        submission = _submission(body)
        headers = _headers(self._key, user_token, idempotency_key)
        features = await self.capabilities(timeout=timeout)
        if FEATURE not in features or (
            submission.source and SOURCE_FEATURE not in features
        ):
            raise VideoJobError("contract_unavailable")
        try:
            value, code = await self._request(
                "POST",
                self._base + "/videos/jobs",
                headers,
                timeout,
                submission.encoded,
            )
            return _accepted(value, code, submission)
        except VideoJobError as exc:
            raise VideoJobError(
                exc.kind, http_status=exc.http_status, submission_uncertain=True
            ) from None

    async def recover(
        self,
        *,
        job_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        user_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> VideoJob:
        path = _selector(job_id, idempotency_key)
        status = _status(
            (
                await self._request(
                    "GET",
                    self._base + path,
                    _headers(self._key, user_token, idempotency_key),
                    timeout,
                )
            )[0]
        )
        if job_id is not None and status["job_id"] != job_id:
            raise VideoJobError("changed_identity")
        return status

    async def wait(
        self,
        receipt: VideoJob,
        *,
        user_token: Optional[str] = None,
        timeout: float = 600.0,
        poll_interval: float = 5.0,
        request_timeout: float = 30.0,
    ) -> VideoJob:
        deadline = time.monotonic() + _positive(timeout)
        _positive(poll_interval)
        _positive(request_timeout)
        anchor = dict(_status(receipt))
        status = _status(receipt)
        while status["state"] not in TERMINAL:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VideoJobError("deadline")
            status = _bound(
                await self.recover(
                    job_id=status["job_id"],
                    user_token=user_token,
                    timeout=min(remaining, request_timeout),
                ),
                anchor,
            )
            if status["state"] not in TERMINAL:
                await asyncio.sleep(
                    min(poll_interval, max(0.0, deadline - time.monotonic()))
                )
        return status
