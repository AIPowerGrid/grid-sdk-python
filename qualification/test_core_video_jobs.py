# SPDX-License-Identifier: MIT
"""Optional Core SQL/auth qualification; never uses a live Grid or funds."""

import asyncio
import base64
import contextlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from grid_api.routers import video_jobs, videos
from grid_api.routers.tests.test_video_jobs import stored
from grid_api.services import accounts, credits, media_jobs, pricing
from grid_api.services.tests.test_media_job_journal import (
    MODEL,
    counts,
    owner,
)
from grid_api.services.tests.test_video_sources import wav
from PIL import Image

pytest_plugins = (
    "grid_api.routers.tests.test_video_jobs",
    "grid_api.services.tests.test_video_sources",
)

# Load the MIT wire module without importing the OpenAI convenience layer into
# Core's dependency environment. Normal SDK tests cover package/client wiring.
spec = importlib.util.spec_from_file_location(
    "sdk_video_qualification", Path(__file__).parents[1] / "src/grid_sdk/video_jobs.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

MODES = [
    "generated",
    "audio",
    "video",
    "appearance-audio",
    "appearance-video",
    "appearance-audio-attention",
    "appearance-video-attention",
]


@pytest.fixture
def video_body(mode, api, mp4, tmp_path, monkeypatch):
    appearance = mode.startswith("appearance-")
    frames = 121 if appearance else 9
    model = "LTX-2.5 Dev BF16 Ingredients" if appearance else MODEL
    if appearance:
        api[-1].return_value = [model]
        # Fixture tariff only; the actual Ingredients recipe stays dark/unpriced.
        monkeypatch.setitem(
            pricing.PRICING,
            model.lower(),
            pricing.ModelPrice(0, 0, video_per_second=0.02),
        )
    body = {
        "model": model,
        "prompt": "A synthetic red ball rolls",
        "frames": frames,
        "fps": 24,
        "size": "768x448" if appearance else "256x256",
        "seed": 42,
        "max_cost_micro_usd": 150_000 if appearance else 100_000,
    }
    if mode != "generated":
        body["reference_audio"] = base64.b64encode(wav(frames)).decode("ascii")
    if appearance:
        image = io.BytesIO()
        Image.new("RGB", (768, 448), "red").save(image, "PNG")
        body["reference_image"] = base64.b64encode(image.getvalue()).decode("ascii")
        body.update(steps=40, cfg_scale=2.0, reference_strength=1.0)
        if mode.endswith("-attention"):
            body["reference_attention_strength"] = 0.25
    if "video" in mode:
        if appearance:
            decoder = shutil.which("ffmpeg")
            if not decoder or not shutil.which("ffprobe"):
                pytest.skip("independent FFmpeg source-decoder gate unavailable")
            path = tmp_path / "appearance-motion.mp4"
            subprocess.run(
                [
                    decoder,
                    "-v",
                    "error",
                    "-nostdin",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=768x448:rate=24",
                    "-frames:v",
                    str(frames),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-threads",
                    "1",
                    "-pix_fmt",
                    "yuv420p",
                    str(path),
                ],
                capture_output=True,
                timeout=15,
                check=True,
                env={"PATH": os.environ["PATH"]},
            )
            mp4 = path.read_bytes()
        body["reference_video"] = base64.b64encode(mp4).decode("ascii")
    return body


def assert_source_contract(row, body):
    appearance = "reference_image" in body
    mode = (
        "video"
        if "reference_video" in body
        else "audio"
        if "reference_audio" in body
        else "generated"
    )
    inputs = row["payload"]["recipe_inputs"]
    assert inputs.get("source_mode", "generated") == mode
    if appearance:
        assert row["payload"]["appearance_profile"] == "ingredients-dev-v1"
        assert "source_image_url" not in row["payload"]
        roles = ["reference_image", "reference_audio"]
        if mode == "video":
            roles.append("reference_video")
        assert [item["role"] for item in row["payload"]["source_media"]] == roles
        assert inputs.get("reference_attention_strength") == body.get(
            "reference_attention_strength"
        )
        guide = row["payload"]["recipe_spec"]["reference_guide"]
        if "reference_attention_strength" in body:
            assert guide["class_type"] == "LTXAddVideoICLoRAGuideAdvanced"
            assert (
                guide["inputs"]["attention_strength"]
                == body["reference_attention_strength"]
            )
        else:
            assert guide["class_type"] == "LTXAddVideoICLoRAGuide"
            assert "attention_strength" not in guide["inputs"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("lost_reply", [False, True])
async def test_sdk_core_auth_hold_recovery_and_js_parity(
    api, video_body, monkeypatch, mode, lost_reply
):
    client, aid, credential, settings, quota, _available = api
    body = video_body
    model, frames = body["model"], body["frames"]
    app = client._transport.app
    features = [module.FEATURE, module.SOURCE_FEATURE]

    @app.get("/health")
    async def synthetic_health():
        return {"features": features}

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.ASGITransport(app=app), **kwargs
        ),
    )
    monkeypatch.setattr(
        videos.video_sources.storage,
        "upload_private_source",
        lambda raw, extension: (
            "https://"
            + "a" * 32
            + ".r2.cloudflarestorage.com/private-synthetic-source/source/"
            + "b" * 32
            + "."
            + extension
            + "?X-Amz-Signature=synthetic"
        ),
    )
    key = str(uuid4())
    if lost_reply:
        reserve = media_jobs.reserve

        async def commit_then_lose(*args, **kwargs):
            await reserve(*args, **kwargs)
            raise ConnectionError("synthetic lost accepted response")

        monkeypatch.setattr(media_jobs, "reserve", commit_then_lose)
    jobs = module.AsyncVideoJobs(credential, "http://test/v1")
    if lost_reply:
        with pytest.raises(module.VideoJobError) as error:
            await jobs.submit(body, idempotency_key=key)
        assert error.value.submission_uncertain and error.value.http_status == 503
        pending = await jobs.recover(idempotency_key=key)
    else:
        pending = await jobs.submit(body, idempotency_key=key)
    assert pending["state"] == "pending_dispatch"
    assert await counts() == (1, 1, 0)
    quota.assert_awaited_once()
    row = await stored(pending["job_id"])
    assert_source_contract(row, body)
    if "reference_image" in body:
        assert pending["reserved_micro"] == 100_834
    assert pending["request_hash"] == video_jobs.request_hash(
        video_jobs.AsyncVideoRequest.model_validate(body)
    )
    worker, token = uuid4(), str(uuid4())
    assert (
        await media_jobs.claim_execution(
            job_id=row["job_id"],
            payload=row["payload"],
            route_models=row["route_models"],
            preferred_worker="",
            selected_model=model,
            worker_id=worker,
            job_type="video",
            execution_token=token,
        )
        == "claimed"
    )
    media = {
        "model": model,
        "worker": "synthetic-worker",
        "gen_time": 1.0,
        "recipe_root": row["payload"]["recipe_root"],
        "media": [
            {
                "url": "https://media.invalid/video.mp4",
                "key": "synthetic/video.mp4",
                "sha256": "a" * 64,
                "seed": 42,
            }
        ],
    }
    values = dict(
        job_id=row["job_id"],
        worker_id=str(worker),
        wallet="",
        model=model,
        job_type="video",
        den=1.0,
        output_units=frames,
        prompt_hash="b" * 64,
        result_hash="c" * 64,
    )
    assert (
        await credits.record_and_settle(
            ledger_values=values,
            exact=True,
            media_result=media,
            media_execution_token=token,
        )
        == "settled"
    )
    settings.media_async_enabled = False
    features.clear()
    terminal = await jobs.wait(pending)
    assert (
        terminal["result"] == media
        and terminal["actual_micro"] == pending["reserved_micro"]
    )
    assert await counts() == (1, 1, 1)
    peer = os.environ.get("AIPG_JS_VIDEO_QUALIFICATION", "")
    assert peer and Path(peer).is_file(), (
        "explicit built JS peer qualification path required"
    )
    node = subprocess.run(
        ["node", peer],
        input=json.dumps(
            {
                "body": body,
                "key": key,
                "pending": pending,
                "terminal": terminal,
                "lost": lost_reply,
            }
        ),
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )
    proof = json.loads(node.stdout)
    assert proof["body"] == body and proof["post_count"] == 1
    assert proof["terminal"] == terminal
    assert (
        video_jobs.request_hash(
            video_jobs.AsyncVideoRequest.model_validate(proof["body"])
        )
        == pending["request_hash"]
    )


@contextlib.asynccontextmanager
async def loopback_core(app: FastAPI) -> AsyncIterator[str]:
    """Serve only this test's router; no Core lifespan or production loops."""
    import uvicorn

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, lifespan="off", access_log=False, log_level="critical")
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:

            async def ready() -> None:
                while not server.started:
                    if serving.done():
                        await serving
                        raise RuntimeError("isolated Core server did not start")
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(ready(), timeout=10)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=10)


async def child_record(process: asyncio.subprocess.Process) -> dict[str, Any]:
    assert process.stdout is not None
    line = await asyncio.wait_for(process.stdout.readline(), timeout=15)
    assert line and len(line) <= 128 * 1024, "bounded SDK qualification reply required"
    value = json.loads(line)
    assert value.get("stage") != "failed", (
        "real SDK/Core transport rejected the fixture"
    )
    return cast(dict[str, Any], value)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("lost_reply", [False, True])
async def test_js_sdk_real_http_admission_and_recovery(
    api, video_body, monkeypatch, mode, lost_reply
):
    client, aid, credential, settings, quota, _available = api
    body = video_body
    model, frames = body["model"], body["frames"]
    app = client._transport.app
    features = [module.FEATURE, module.SOURCE_FEATURE]
    trace, submissions = [], []

    @app.middleware("http")
    async def observe_request(request, call_next):
        trace.append(
            (
                request.method,
                request.url.path,
                bool(
                    request.headers.get("apikey")
                    or request.headers.get("authorization")
                ),
            )
        )
        if request.method == "POST":
            submissions.append(json.loads(await request.body()))
        return await call_next(request)

    @app.get("/health")
    async def synthetic_health():
        return {"features": features}

    monkeypatch.setattr(
        videos.video_sources.storage,
        "upload_private_source",
        lambda _raw, extension: (
            "https://"
            + "a" * 32
            + ".r2.cloudflarestorage.com/private-synthetic-source/source/"
            + "b" * 32
            + "."
            + extension
            + "?X-Amz-Signature=synthetic"
        ),
    )
    if lost_reply:
        reserve = media_jobs.reserve

        async def commit_then_lose(*args, **kwargs):
            await reserve(*args, **kwargs)
            raise ConnectionError("synthetic lost accepted response")

        monkeypatch.setattr(media_jobs, "reserve", commit_then_lose)
    configured_peer = os.environ.get("AIPG_JS_VIDEO_QUALIFICATION", "")
    assert configured_peer, "explicit built JS peer qualification path required"
    peer = Path(configured_peer).with_name("core-http.mjs")
    assert peer.is_file(), "explicit built JS peer qualification path required"
    key = str(uuid4())
    async with loopback_core(app) as origin:
        process = await asyncio.create_subprocess_exec(
            "node",
            str(peer),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": os.environ["PATH"]},
            limit=128 * 1024,
        )
        try:
            process.stdin.write(
                (
                    json.dumps(
                        {
                            "origin": origin,
                            "credential": credential,
                            "body": body,
                            "key": key,
                            "lost": lost_reply,
                        }
                    )
                    + "\n"
                ).encode()
            )
            await process.stdin.drain()
            pending = (await child_record(process))["pending"]
            assert pending["state"] == "pending_dispatch"
            assert pending["request_hash"] == video_jobs.request_hash(
                video_jobs.AsyncVideoRequest.model_validate(body)
            )
            assert submissions == [body] and await counts() == (1, 1, 0)
            quota.assert_awaited_once()
            accepted_requests = len(trace)
            row = await stored(pending["job_id"])
            assert_source_contract(row, body)
            if "reference_image" in body:
                assert pending["reserved_micro"] == 100_834
            worker, token = uuid4(), str(uuid4())
            assert (
                await media_jobs.claim_execution(
                    job_id=row["job_id"],
                    payload=row["payload"],
                    route_models=row["route_models"],
                    preferred_worker="",
                    selected_model=model,
                    worker_id=worker,
                    job_type="video",
                    execution_token=token,
                )
                == "claimed"
            )
            result = {
                "model": model,
                "worker": "synthetic-worker",
                "gen_time": 1.0,
                "recipe_root": row["payload"]["recipe_root"],
                "media": [
                    {
                        "url": "https://media.invalid/video.mp4",
                        "key": "synthetic/video.mp4",
                        "sha256": "a" * 64,
                        "seed": 42,
                    }
                ],
            }
            assert (
                await credits.record_and_settle(
                    ledger_values={
                        "job_id": row["job_id"],
                        "worker_id": str(worker),
                        "wallet": "",
                        "model": model,
                        "job_type": "video",
                        "den": 1.0,
                        "output_units": frames,
                        "prompt_hash": "b" * 64,
                        "result_hash": "c" * 64,
                    },
                    exact=True,
                    media_result=result,
                    media_execution_token=token,
                )
                == "settled"
            )
            settings.media_async_enabled = False
            features.clear()
            foreign_key = await accounts.issue_key(
                await owner(), scopes=["inference.submit"]
            )
            observer = await accounts.issue_key(aid, scopes=["account.read"])
            process.stdin.write(
                (
                    json.dumps(
                        {
                            "denied": [
                                ["invalid-fixture", 401],
                                [observer, 403],
                                [foreign_key, 404],
                            ],
                        }
                    )
                    + "\n"
                ).encode()
            )
            await process.stdin.drain()
            proof = await child_record(process)
            assert proof["stage"] == "completed" and proof["denied"] == [401, 403, 404]
            terminal = proof["terminal"]
            assert terminal["state"] == "completed" and terminal["result"] == result
            assert terminal["actual_micro"] == pending["reserved_micro"]
            assert await counts() == (1, 1, 1)
            assert sum(method == "POST" for method, *_ in trace) == 1
            assert [item for item in trace if item[1] == "/health"] == [
                ("GET", "/health", False)
            ]
            assert all(authorized for _, path, authorized in trace if path != "/health")
            assert all(method == "GET" for method, *_ in trace[accepted_requests:])
            assert {path for _, path, _ in trace} == {
                "/health",
                "/v1/videos/jobs",
                "/v1/videos/jobs/" + pending["job_id"],
            }
            await asyncio.wait_for(process.wait(), timeout=10)
            assert process.returncode == 0
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
