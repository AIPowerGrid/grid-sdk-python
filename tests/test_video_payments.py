# SPDX-License-Identifier: MIT
"""Hermetic wallet-policy controls, not real payments or ECDSA proof."""

import asyncio
import hashlib
import json
from unittest.mock import Mock

import pytest

from grid_sdk import (
    VideoPaymentError,
    async_sign_video_authorization,
    prepare_video_authorization,
    sign_video_authorization,
)
from grid_sdk import video_payments as payments

NOW = 2_000_000_000
SIG = "0x" + "12" * 64 + "1b"


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setattr(payments.time, "time", lambda: NOW)
    commitment = "c" * 64
    nonce = (
        "0x"
        + hashlib.sha256(
            json.dumps(
                {"quote": commitment, "schema": "aipg.video-authorization.v1"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
    )
    asset = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
    quote = {
        "schema": "aipg.video-quote.v1",
        "binding_schema": "aipg.video-quote-binding.v2",
        "quote_id": "11111111-1111-4111-8111-111111111111",
        "job_id": "22222222-2222-4222-8222-222222222222",
        "state": "quoted",
        "payment_enabled": False,
        "created": NOW,
        "expires": NOW + 300,
        "model": "LTX-2.5 Distilled BF16",
        "request_hash": "a" * 64,
        "plan_hash": "b" * 64,
        "commitment": commitment,
        "authorization_nonce": nonce,
        "max_cost_micro_usd": 100_000,
        "payment": {
            "scheme": "exact",
            "network": "eip155:84532",
            "asset": asset,
            "pay_to": "0x" + "1" * 40,
            "amount_micro": 7500,
            "valid_after": 0,
            "valid_before": NOW + 300,
            "eip712_domain": {
                "name": "USDC",
                "version": "2",
                "chainId": 84532,
                "verifyingContract": asset,
            },
        },
    }
    policy = {
        "payer": "0x" + "2" * 40,
        "expected_model": quote["model"],
        "expected_request_hash": "a" * 64,
        "expected_recipient": "0x" + "1" * 40,
        "network": "eip155:84532",
        "max_cost_micro_usd": 100_000,
    }
    return quote, policy


def test_preview_never_calls_wallet_and_request_views_are_immutable(fixture):
    quote, policy = fixture
    request = prepare_video_authorization(quote, **policy)
    assert request.authorization["nonce"] == quote["authorization_nonce"]
    assert request.typed_data["message"]["value"] == "7500"
    assert "EIP712Domain" in request.typed_data["types"]
    request.typed_data["domain"]["name"] = "changed"
    quote["payment"]["amount_micro"] = 1
    assert (
        request.authorization["value"] == "7500"
        and request.typed_data["domain"]["name"] == "USDC"
    )
    signer = Mock(return_value=SIG)
    with pytest.raises(VideoPaymentError, match="payment_disabled"):
        sign_video_authorization(request, signer)
    signer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_model", "wrong"),
        ("expected_request_hash", "b" * 64),
        ("expected_recipient", "0x" + "3" * 40),
        ("network", "eip155:8453"),
        ("max_cost_micro_usd", 99_999),
        ("max_cost_micro_usd", True),
        ("payer", "0x" + "1" * 40),
    ],
)
def test_independent_policy_mismatch_refuses_before_wallet(fixture, field, value):
    quote, policy = fixture
    with pytest.raises(VideoPaymentError):
        prepare_video_authorization(quote, **{**policy, field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("binding_schema", "aipg.video-quote-binding.v1"),
        ("payment_enabled", "false"),
        ("authorization_nonce", "0x" + "0" * 64),
        ("expires", NOW),
        ("created", NOW + 1),
        ("max_cost_micro_usd", True),
        ("state", "funded"),
    ],
)
def test_wrong_quote_identity_window_and_types_are_private_errors(
    fixture, field, value
):
    quote, policy = fixture
    with pytest.raises(VideoPaymentError) as error:
        prepare_video_authorization({**quote, field: value}, **policy)
    assert value not in str(error.value) if isinstance(value, str) else True


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_micro", 100_001),
        ("amount_micro", True),
        ("asset", "0x" + "3" * 40),
        ("valid_after", 1),
        ("valid_before", NOW + 301),
        ("scheme", "upto"),
        ("network", "eip155:1"),
    ],
)
def test_changed_payment_fields_are_rejected(fixture, field, value):
    quote, policy = fixture
    quote["payment"][field] = value
    with pytest.raises(VideoPaymentError):
        prepare_video_authorization(quote, **policy)


def test_domain_nonfinite_and_unbounded_data_are_rejected(fixture):
    quote, policy = fixture
    quote["payment"]["eip712_domain"]["chainId"] = 1
    with pytest.raises(VideoPaymentError):
        prepare_video_authorization(quote, **policy)
    quote["payment"]["eip712_domain"]["chainId"] = 84532
    for item in (float("nan"), "private-marker" * 6000):
        with pytest.raises(VideoPaymentError) as error:
            prepare_video_authorization({**quote, "unused": item}, **policy)
        assert "private-marker" not in str(error.value)


def test_sign_callback_is_explicit_and_spending_capability_is_not_in_repr(fixture):
    quote, policy = fixture
    quote["payment_enabled"] = True  # Synthetic future server; actual Core stays false.
    request = prepare_video_authorization(quote, **policy)
    signer = Mock(return_value=SIG)
    signed = sign_video_authorization(request, signer)
    signer.assert_called_once_with(request.typed_data)
    assert signed.payload == {"authorization": request.authorization, "signature": SIG}
    assert SIG not in repr(signed)
    signed.payload["signature"] = "changed"
    assert signed.payload["signature"] == SIG


def test_expiry_after_wallet_and_signer_failure_are_sanitized(fixture, monkeypatch):
    quote, policy = fixture
    quote["payment_enabled"] = True
    request = prepare_video_authorization(quote, **policy)

    def slow(_data):
        monkeypatch.setattr(payments.time, "time", lambda: NOW + 300)
        return SIG

    with pytest.raises(VideoPaymentError, match="expired_quote"):
        sign_video_authorization(request, slow)
    monkeypatch.setattr(payments.time, "time", lambda: NOW)
    with pytest.raises(VideoPaymentError) as error:
        sign_video_authorization(
            request, Mock(side_effect=RuntimeError("private-signer-marker"))
        )
    assert "private-signer-marker" not in str(error.value)
    with pytest.raises(VideoPaymentError, match="unsupported_signature"):
        sign_video_authorization(request, Mock(return_value="private-signer-marker"))


@pytest.mark.asyncio
async def test_async_wallet_parity_preview_and_cancellation(fixture):
    quote, policy = fixture

    async def signer(data):
        assert data["message"]["nonce"] == quote["authorization_nonce"]
        return SIG

    with pytest.raises(VideoPaymentError, match="payment_disabled"):
        await async_sign_video_authorization(
            prepare_video_authorization(quote, **policy), signer
        )
    quote["payment_enabled"] = True
    request = prepare_video_authorization(quote, **policy)
    assert (
        await async_sign_video_authorization(request, signer)
    ).payload == sign_video_authorization(request, lambda _data: SIG).payload

    async def cancel(_data):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await async_sign_video_authorization(request, cancel)
