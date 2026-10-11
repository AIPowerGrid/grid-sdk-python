# SPDX-License-Identifier: MIT
"""Wire contracts for the separate candidate /v1/videos/jobs client."""

import asyncio
import copy
import json
from typing import Any

import httpx
import pytest
import respx

from grid_sdk import (
    AsyncGrid,
    AsyncVideoJobs,
    Grid,
    VideoJobError,
    VideoJobs,
    video_jobs,
)
from grid_sdk.video_jobs import FEATURE, MAX_JSON, SOURCE_FEATURE

BASE = "https://grid.example/v1"
KEY = "00000000-0000-4000-8000-0000000000aa"  # Public request UUID, not a credential.
JOB = "62964058-56d2-4b84-9ba3-cd8a26ebf831"
MODEL = "LTX-2.5 Distilled BF16"
BODY = {
    "model": MODEL,
    "prompt": "a person waving in a car",
    "frames": 33,
    "fps": 24,
    "max_cost_micro_usd": 50000,
}


def receipt(state: str = "queued", **changes: Any) -> dict:
    value = {
        "schema": "aipg.video-job.v1",
        "job_id": JOB,
        "model": MODEL,
        "state": state,
        "request_hash": "a" * 64,
        "reserved_micro": 12000,
        "max_cost_micro": 50000,
        "actual_micro": None,
        "result": None,
    }
    if state == "completed":
        value.update(
            actual_micro=12000,
            result={
                "model": MODEL,
                "worker": "fixture-worker",
                "gen_time": 4.5,
                "recipe_root": None,
                "media": [
                    {
                        "url": "https://media.example/test.mp4",
                        "key": "test.mp4",
                        "sha256": "b" * 64,
                        "seed": None,
                    }
                ],
            },
        )
    value.update(changes)
    return value


def health(features: list = None) -> respx.Route:
    return respx.get("https://grid.example/health").respond(
        json={"features": [FEATURE, SOURCE_FEATURE] if features is None else features}
    )


def test_exports_and_lazy_wiring_preserve_legacy_custom_base() -> None:
    assert isinstance(Grid(api_key="fixture", base_url=BASE).grid.video_jobs, VideoJobs)
    assert isinstance(
        AsyncGrid(api_key="fixture", base_url=BASE).grid.video_jobs, AsyncVideoJobs
    )
    # Access to the new contract, not construction of the legacy client, validates /v1.
    legacy = Grid(api_key="fixture", base_url="https://grid.example/custom").grid
    with pytest.raises(ValueError):
        _ = legacy.video_jobs


@respx.mock
@pytest.mark.parametrize("mode", ["generated", "audio", "video"])
def test_submit_source_modes_and_service_delegation(mode: str) -> None:
    public = health()
    body = dict(BODY)
    if mode != "generated":
        body["reference_audio"] = "data:audio/wav;base64,fixture"
    if mode == "video":
        body.update(reference_video="data:video/mp4;base64,fixture", size="768x512")
    submit = respx.post(BASE + "/videos/jobs").respond(202, json=receipt())
    assert (
        VideoJobs("fixture", BASE).submit(
            body, idempotency_key=KEY, user_token="delegated-fixture"
        )["job_id"]
        == JOB
    )
    assert submit.call_count == 1
    request = submit.calls.last.request
    assert json.loads(request.content) == body
    assert request.headers["Idempotency-Key"] == KEY
    assert request.headers["X-Grid-User-Token"] == "delegated-fixture"
    assert request.headers["Authorization"] == "Bearer fixture"
    assert "authorization" not in public.calls.last.request.headers


@respx.mock
@pytest.mark.parametrize("features", [[], [SOURCE_FEATURE], [FEATURE]])
def test_missing_feature_never_posts(features: list) -> None:
    health(features)
    body = {**BODY, "reference_audio": "fixture"}
    with pytest.raises(VideoJobError, match="contract_unavailable") as exc:
        VideoJobs("fixture", BASE).submit(body, idempotency_key=KEY)
    assert not exc.value.submission_uncertain
    assert all(call.request.method == "GET" for call in respx.calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_cost_micro_usd": 0},
        {"max_cost_micro_usd": True},
        {"max_cost_micro_usd": 1.2},
        {"max_cost_micro_usd": 2**53},
        {"cfg_scale": float("nan")},
        {"model": ""},
        {"prompt": ""},
        {"n": True},
        {"n": 2},
        {"image": "x", "keyframes": [{"image": "y"}]},
        {"reference_video": "x"},
        {"reference_image": "x"},
        {
            "reference_image": "x",
            "reference_audio": "y",
            "size": "768x448",
            "image": "z",
        },
        {
            "reference_image": "x",
            "reference_audio": "y",
            "size": "768x448",
            "keyframes": [{"image": "z"}],
        },
    ],
)
def test_invalid_bodies_fail_before_network(changes: dict) -> None:
    with respx.mock(assert_all_called=False) as mock:
        with pytest.raises(ValueError):
            VideoJobs("fixture", BASE).submit({**BODY, **changes}, idempotency_key=KEY)
        assert not mock.calls


@respx.mock
def test_lost_reply_recovers_by_header_without_post_retry_or_health() -> None:
    health()
    submit = respx.post(BASE + "/videos/jobs").mock(
        side_effect=httpx.ReadTimeout("fixture secret should not leak")
    )
    jobs = VideoJobs("fixture", BASE)
    with pytest.raises(VideoJobError) as exc:
        jobs.submit(BODY, idempotency_key=KEY)
    assert exc.value.submission_uncertain
    assert "secret" not in str(exc.value)
    recover = respx.get(BASE + "/videos/jobs").respond(
        json=receipt("execution_uncertain")
    )
    assert (
        jobs.recover(idempotency_key=KEY, user_token="fixture-token")["state"]
        == "execution_uncertain"
    )
    assert recover.calls.last.request.headers["Idempotency-Key"] == KEY
    assert recover.calls.last.request.headers["X-Grid-User-Token"] == "fixture-token"
    assert str(recover.calls.last.request.url) == BASE + "/videos/jobs"
    assert submit.call_count == 1


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("motion", [False, True])
@pytest.mark.parametrize("attention", [None, 0.25])
async def test_appearance_sources_survive_lost_reply_without_becoming_opening_pins(
    motion: bool, attention: float | None,
) -> None:
    health()
    model = "LTX-2.5 Dev BF16 Ingredients"
    body = {
        **BODY,
        "model": model,
        "size": "768x448",
        "frames": 121,
        "reference_image": "data:image/png;base64,fixture",
        "reference_audio": "data:audio/wav;base64,fixture",
        "reference_strength": 1.0,
    }
    if attention is not None:
        body["reference_attention_strength"] = attention
    if motion:
        body.update(
            reference_video="data:video/mp4;base64,fixture",
            guide_strength=0.5,
            motion_attention_strength=0.25,
        )
    post = respx.post(BASE + "/videos/jobs").mock(
        side_effect=httpx.ReadTimeout("private fixture")
    )
    jobs = AsyncVideoJobs("fixture", BASE)
    with pytest.raises(VideoJobError) as error:
        await jobs.submit(body, idempotency_key=KEY)
    assert error.value.submission_uncertain
    wire = json.loads(post.calls.last.request.content)
    assert wire == body and "image" not in wire and "keyframes" not in wire
    respx.get(BASE + "/videos/jobs").respond(json=receipt(model=model))
    assert (await jobs.recover(idempotency_key=KEY))["model"] == model
    assert post.call_count == 1


@respx.mock
@pytest.mark.parametrize("code", [302, 402, 404, 409, 429, 500, 503])
def test_submit_error_is_sanitized_uncertain_and_never_retried(code: int) -> None:
    health()
    submit = respx.post(BASE + "/videos/jobs").respond(
        code,
        headers={"Location": "https://foreign.example"},
        text="private prompt fixture",
    )
    with pytest.raises(VideoJobError) as exc:
        VideoJobs("fixture", BASE).submit(BODY, idempotency_key=KEY)
    assert exc.value.http_status == code and exc.value.submission_uncertain
    assert "private" not in str(exc.value)
    assert submit.call_count == 1


@respx.mock
def test_wait_gets_only_same_identity_and_completed_result() -> None:
    recover = respx.get(BASE + "/videos/jobs/" + JOB).mock(
        side_effect=[
            httpx.Response(200, json=receipt("execution_uncertain")),
            httpx.Response(200, json=receipt("completed")),
        ]
    )
    assert (
        VideoJobs("fixture", BASE).wait(receipt(), poll_interval=0.001)["result"][
            "media"
        ][0]["sha256"]
        == "b" * 64
    )
    assert recover.call_count == 2
    assert all(call.request.method == "GET" for call in respx.calls)


@respx.mock
@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", KEY),
        ("model", "other"),
        ("request_hash", "c" * 64),
        ("reserved_micro", 11000),
        ("max_cost_micro", 50001),
    ],
)
def test_wait_refuses_changed_identity(field: str, value: Any) -> None:
    respx.get(BASE + "/videos/jobs/" + JOB).respond(json=receipt(**{field: value}))
    with pytest.raises(VideoJobError, match="changed_identity"):
        VideoJobs("fixture", BASE).wait(receipt())


@respx.mock
@pytest.mark.parametrize(
    "changes",
    [
        {"schema": "wrong"},
        {"state": "paid"},
        {"actual_micro": 1},
        {"reserved_micro": True},
        {"reserved_micro": 50001},
        {"max_cost_micro": 2**53},
        {"request_hash": "bad"},
        {"result": {}},
        {"job_id": "../other"},
    ],
)
def test_invalid_status_fails_closed(changes: dict) -> None:
    respx.get(BASE + "/videos/jobs/" + JOB).respond(json=receipt(**changes))
    with pytest.raises(VideoJobError, match="invalid_response"):
        VideoJobs("fixture", BASE).recover(job_id=JOB)


@respx.mock
@pytest.mark.parametrize(
    "payload", [b"not JSON", b"{" + b" " * MAX_JSON, b'{"state":NaN}']
)
def test_invalid_or_oversized_json_never_succeeds(payload: bytes) -> None:
    respx.get(BASE + "/videos/jobs/" + JOB).respond(content=payload)
    with pytest.raises(VideoJobError):
        VideoJobs("fixture", BASE).recover(job_id=JOB)


@respx.mock
@pytest.mark.parametrize("state,code", [("queued", 200), ("completed", 202)])
def test_submit_http_state_and_cost_binding(state: str, code: int) -> None:
    health()
    respx.post(BASE + "/videos/jobs").respond(code, json=receipt(state))
    with pytest.raises(VideoJobError, match="invalid_response") as exc:
        VideoJobs("fixture", BASE).submit(BODY, idempotency_key=KEY)
    assert exc.value.submission_uncertain


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"job_id": JOB, "idempotency_key": KEY},
        {"job_id": "../x"},
        {"idempotency_key": JOB.upper()},
        {"idempotency_key": "00000000-0000-1000-8000-000000000000"},
    ],
)
def test_selector_validation(options: dict) -> None:
    with pytest.raises(ValueError):
        VideoJobs("fixture", BASE).recover(**options)


@pytest.mark.parametrize(
    "token", ["", "private\r\nInjected: x", "private\0", "private\u2603"]
)
def test_invalid_credentials_are_rejected_without_echo_or_network(token: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        with pytest.raises(ValueError) as error:
            VideoJobs("fixture", BASE).recover(job_id=JOB, user_token=token)
        assert "private" not in str(error.value)
        assert not mock.calls


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, 10**300])
def test_wait_timeout_validation(value: float) -> None:
    with pytest.raises(ValueError):
        VideoJobs("fixture", BASE).wait(receipt(), timeout=value)


@respx.mock
def test_deadline_does_not_create_new_job(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(video_jobs.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        video_jobs.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )
    recover = respx.get(BASE + "/videos/jobs/" + JOB).respond(json=receipt())
    with pytest.raises(VideoJobError, match="deadline"):
        VideoJobs("fixture", BASE).wait(receipt(), timeout=0.025, poll_interval=0.01)
    assert recover.call_count == 3
    assert all(call.request.method == "GET" for call in respx.calls)


def test_closed_without_result_is_not_reported_as_refunded() -> None:
    result = receipt("closed_without_result", actual_micro=12000)
    assert VideoJobs("fixture", BASE).wait(result) == result
    assert "refunded" not in result


@respx.mock
@pytest.mark.asyncio
async def test_async_source_submission_lost_reply_and_wait() -> None:
    health()
    submit = respx.post(BASE + "/videos/jobs").mock(
        side_effect=httpx.ReadTimeout("private")
    )
    jobs = AsyncVideoJobs("fixture", BASE)
    with pytest.raises(VideoJobError) as exc:
        await jobs.submit({**BODY, "reference_audio": "fixture"}, idempotency_key=KEY)
    assert exc.value.submission_uncertain
    respx.get(BASE + "/videos/jobs").respond(json=receipt())
    recovered = await jobs.recover(idempotency_key=KEY)
    respx.get(BASE + "/videos/jobs/" + JOB).respond(json=receipt("completed"))
    assert (await jobs.wait(recovered))["state"] == "completed"
    assert submit.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_async_wait_is_cancellable_without_resubmission() -> None:
    respx.get(BASE + "/videos/jobs/" + JOB).respond(json=receipt())
    task = asyncio.create_task(
        AsyncVideoJobs("fixture", BASE).wait(receipt(), poll_interval=30)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(call.request.method == "GET" for call in respx.calls)


@respx.mock
def test_malformed_completed_media_is_refused() -> None:
    value = copy.deepcopy(receipt("completed"))
    value["result"]["media"][0]["url"] = "file:///private/fixture"
    respx.get(BASE + "/videos/jobs/" + JOB).respond(json=value)
    with pytest.raises(VideoJobError, match="invalid_response"):
        VideoJobs("fixture", BASE).recover(job_id=JOB)
