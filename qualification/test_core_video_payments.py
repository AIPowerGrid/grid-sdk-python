# SPDX-License-Identifier: MIT
"""Real quote HTTP/SQL plus SDK/crypto IPC; no chain, payment, upload or GPU."""

import asyncio
import base64
import importlib.util
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from grid_api.routers.tests import test_video_quotes as router_tests
from grid_api.services import credits, video_eip3009, video_quotes
from grid_api.services.tests.test_media_job_journal import OPENING, counts
from grid_api.services.tests.test_video_sources import wav

pytest_plugins = (
    "grid_api.routers.tests.test_video_quotes",
    "grid_api.services.tests.test_video_sources",
)

# Keep the OpenAI convenience layer out of Core's dependency environment.
spec = importlib.util.spec_from_file_location(
    "sdk_video_payment_qualification",
    Path(__file__).parents[1] / "src/grid_sdk/video_payments.py",
)
sdk = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sdk
spec.loader.exec_module(sdk)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["generated", "audio", "video"])
@pytest.mark.parametrize("network", ["eip155:8453", "eip155:84532"])
async def test_actual_quote_and_both_sdk_wallet_callbacks_match_core(
    quote_api, mp4, mode, network
):
    client, aid, credential, *_ = quote_api
    quote_api[3].video_x402_quote_network = network
    key = uuid4()
    body = {"frames": 9, "size": "256x256", "seed": 42}
    if mode != "generated":
        body["reference_audio"] = base64.b64encode(wav()).decode("ascii")
    if mode == "video":
        body["reference_video"] = base64.b64encode(mp4).decode("ascii")
    response = await router_tests.post(quote_api, key=key, body=body)
    assert response.status_code == 201
    quote = response.json()
    row = await video_quotes.lookup(aid, idempotency_key=str(key))
    wallet = Account.create()  # Unfunded throwaway signer; never crosses IPC.
    policy = {
        "payer": wallet.address,
        "expected_model": quote["model"],
        "expected_request_hash": quote["request_hash"],
        "expected_recipient": quote["payment"]["pay_to"],
        "network": quote["payment"]["network"],
        "max_cost_micro_usd": 100_000,
    }
    preview = sdk.prepare_video_authorization(quote, **policy)
    called = []
    with pytest.raises(sdk.VideoPaymentError, match="payment_disabled"):
        sdk.sign_video_authorization(preview, lambda data: called.append(data))
    assert not called
    unsigned = sdk.prepare_video_authorization(
        {**quote, "payment_enabled": True}, **policy
    )
    signed = sdk.sign_video_authorization(
        unsigned,
        lambda data: "0x"
        + wallet.sign_message(encode_typed_data(full_message=data)).signature.hex(),
    )
    result = video_eip3009.verify(row, signed.payload, expected_payer=wallet.address)
    assert result.job_id == quote["job_id"] and result.amount_micro == 7500
    assert signed.payload["signature"] not in repr(signed)

    script = os.environ.get("AIPG_JS_VIDEO_PAYMENTS_QUALIFICATION", "")
    node = os.environ.get("AIPG_VIDEO_QUALIFICATION_NODE", "node")
    if not script or not Path(script).is_file():
        pytest.fail("explicit built JS video-payments qualification required")
    child = await asyncio.create_subprocess_exec(
        node,
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PATH": os.environ.get("PATH", "")},
    )
    try:
        js_policy = {
            "payer": wallet.address,
            "expectedModel": policy["expected_model"],
            "expectedRequestHash": policy["expected_request_hash"],
            "expectedRecipient": policy["expected_recipient"],
            "network": policy["network"],
            "maxCostMicroUsd": policy["max_cost_micro_usd"],
        }
        child.stdin.write(
            (json.dumps({"quote": quote, "policy": js_policy}) + "\n").encode()
        )
        await child.stdin.drain()
        first = await asyncio.wait_for(child.stdout.readline(), timeout=10)
        assert 0 < len(first) <= 16 * 1024
        data = json.loads(first)
        assert (
            data["phase"] == "unsigned"
            and data["previewBlocked"]
            and not data["called"]
        )
        assert (
            data["authorization"] == unsigned.authorization
            and data["typedData"] == unsigned.typed_data
        )
        signature = (
            "0x"
            + wallet.sign_message(
                encode_typed_data(full_message=data["typedData"])
            ).signature.hex()
        )
        child.stdin.write((json.dumps({"signature": signature}) + "\n").encode())
        await child.stdin.drain()
        child.stdin.close()
        second = await asyncio.wait_for(child.stdout.readline(), timeout=10)
        assert 0 < len(second) <= 4096
        forwarded = json.loads(second)
        assert forwarded["phase"] == "signed" and forwarded["hidden"]
        assert (
            forwarded["quoteId"] == quote["quote_id"]
            and forwarded["jobId"] == quote["job_id"]
        )
        assert (
            video_eip3009.verify(
                row, forwarded["payload"], expected_payer=wallet.address
            )
            == result
        )
        assert await asyncio.wait_for(child.wait(), timeout=10) == 0
        assert await child.stderr.read() == b""
    finally:
        if child.returncode is None:
            child.terminate()
            await asyncio.wait_for(child.wait(), timeout=5)
    assert await credits.get_balance(aid) == OPENING and await counts() == (0, 0, 0)
    assert (
        await client.get(response.headers["location"], headers={"apikey": credential})
    ).json() == quote
