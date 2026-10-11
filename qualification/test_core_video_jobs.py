# SPDX-License-Identifier: MIT
"""Optional Core SQL/auth qualification; never uses a live Grid or funds."""

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from grid_api.routers import video_jobs, videos
from grid_api.routers.tests.test_video_jobs import stored
from grid_api.services import credits, media_jobs
from grid_api.services.tests.test_media_job_journal import (
    MODEL,
    counts,
)
from grid_api.services.tests.test_video_sources import wav

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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["generated", "audio", "video"])
@pytest.mark.parametrize("lost_reply", [False, True])
async def test_sdk_core_auth_hold_recovery_and_js_parity(
    api, mp4, monkeypatch, mode, lost_reply
):
    client, aid, credential, settings, quota, _available = api
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
    body = {
        "model": MODEL,
        "prompt": "A synthetic red ball rolls",
        "frames": 9,
        "fps": 24,
        "size": "256x256",
        "seed": 42,
        "max_cost_micro_usd": 100_000,
    }
    if mode != "generated":
        body["reference_audio"] = base64.b64encode(wav(9)).decode("ascii")
    if mode == "video":
        body["reference_video"] = base64.b64encode(mp4).decode("ascii")
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
    assert row["payload"]["recipe_inputs"].get("source_mode", "generated") == mode
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
            selected_model=MODEL,
            worker_id=worker,
            job_type="video",
            execution_token=token,
        )
        == "claimed"
    )
    media = {
        "model": MODEL,
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
        model=MODEL,
        job_type="video",
        den=1.0,
        output_units=9,
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
