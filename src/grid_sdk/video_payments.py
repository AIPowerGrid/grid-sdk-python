# SPDX-License-Identifier: MIT
"""Opt-in unsigned video payment preparation; no HTTP, key handling or sending."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Mapping, cast
from uuid import UUID

_MAX_MONEY = 2**53 - 1
_DOMAINS = {
    "eip155:8453": (8453, "USD Coin", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"),
    "eip155:84532": (84532, "USDC", "0x036cbd53842c5426634e7929541ec2318f3dcf7e"),
}
_TYPES = {
    "EIP712Domain": [
        {"name": name, "type": kind}
        for name, kind in (
            ("name", "string"),
            ("version", "string"),
            ("chainId", "uint256"),
            ("verifyingContract", "address"),
        )
    ],
    "TransferWithAuthorization": [
        {"name": name, "type": kind}
        for name, kind in (
            ("from", "address"),
            ("to", "address"),
            ("value", "uint256"),
            ("validAfter", "uint256"),
            ("validBefore", "uint256"),
            ("nonce", "bytes32"),
        )
    ],
}


class VideoPaymentError(RuntimeError):
    """Sanitized error, without quote values, signer messages or signatures."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(f"Grid video payment {kind}")


def _address(value: object) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value)
        or int(value[2:], 16) == 0
    ):
        raise ValueError
    return value.lower()


def _digest(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError
    return value


def _uuid(value: object) -> str:
    if (
        not isinstance(value, str)
        or str(UUID(value)) != value
        or UUID(value).version != 4
    ):
        raise ValueError
    return value


def _integer(value: object, *, positive: bool = True) -> int:
    if type(value) is not int or not (1 if positive else 0) <= value <= _MAX_MONEY:
        raise ValueError
    return value


@dataclass(frozen=True)
class VideoAuthorizationRequest:
    quote_id: str
    job_id: str
    request_hash: str
    expires: int
    payment_enabled: bool
    _encoded: str = field(repr=False)
    accepts_upfront_payment: bool = False

    @property
    def authorization(self) -> Dict[str, str]:
        return cast(Dict[str, str], json.loads(self._encoded)["authorization"])

    @property
    def typed_data(self) -> Dict[str, object]:
        return cast(Dict[str, object], json.loads(self._encoded)["typed_data"])

    def _signable(self) -> None:
        if not self.payment_enabled:
            raise VideoPaymentError("payment_disabled")
        if self.accepts_upfront_payment is not True:
            raise VideoPaymentError("upfront_payment_not_accepted")
        if int(time.time()) >= self.expires:
            raise VideoPaymentError("expired_quote")


@dataclass(frozen=True)
class SignedVideoAuthorization:
    """A temporary spending capability; explicitly export, never log it."""

    quote_id: str
    job_id: str
    _encoded: str = field(repr=False)

    @property
    def payload(self) -> Dict[str, object]:
        return cast(Dict[str, object], json.loads(self._encoded))


def prepare_video_authorization(
    quote: Mapping[str, object],
    *,
    payer: str,
    expected_model: str,
    expected_request_hash: str,
    expected_recipient: str,
    network: str,
    max_cost_micro_usd: int,
    accept_upfront_payment: bool = False,
) -> VideoAuthorizationRequest:
    """Check a trusted Core quote against independently retained intent/policy.

    Preview quotes can be inspected, but signing requires payment_enabled=true.
    This does not independently verify Core's hidden plan or an on-chain token.
    """
    try:
        encoded = json.dumps(
            dict(quote), allow_nan=False, ensure_ascii=True, separators=(",", ":")
        )
        if len(encoded) > 64 * 1024:
            raise ValueError
        value = json.loads(encoded)
        _integer(max_cost_micro_usd)
        if type(accept_upfront_payment) is not bool:
            raise ValueError
        intent = _digest(expected_request_hash)
        payer, recipient = _address(payer), _address(expected_recipient)
        chain, name, asset = _DOMAINS[network]
        quote_id, job_id = _uuid(value["quote_id"]), _uuid(value["job_id"])
        created, expires = _integer(value["created"]), _integer(value["expires"])
        if (
            value["schema"] != "aipg.video-quote.v1"
            or value["binding_schema"] != "aipg.video-quote-binding.v3"
            or value["state"] != "quoted"
            or type(value["payment_enabled"]) is not bool
            or not isinstance(expected_model, str)
            or not expected_model
            or value["model"] != expected_model
            or value["request_hash"] != intent
            or value["max_cost_micro_usd"] != max_cost_micro_usd
            or type(value["max_cost_micro_usd"]) is not int
            or payer == recipient
            or expires - created != 300
            or not created <= int(time.time()) < expires
        ):
            raise ValueError
        _digest(value["plan_hash"])
        commitment = _digest(value["commitment"])
        sealed = json.dumps(
            {"quote": commitment, "schema": "aipg.video-authorization.v1"},
            sort_keys=True,
            separators=(",", ":"),
        )
        nonce = "0x" + hashlib.sha256(sealed.encode("ascii")).hexdigest()
        if value["authorization_nonce"] != nonce:
            raise ValueError
        payment = value["payment"]
        amount = _integer(payment["amount_micro"])
        domain = {
            "name": name,
            "version": "2",
            "chainId": chain,
            "verifyingContract": asset,
        }
        if (
            payment["scheme"] != "exact"
            or payment["payment_flow"] != "upfront"
            or payment["asset_transfer_method"] != "eip3009"
            or payment["network"] != network
            or payment["asset"] != asset
            or _address(payment["pay_to"]) != recipient
            or payment["eip712_domain"] != domain
            or type(payment["valid_after"]) is not int
            or payment["valid_after"] != 0
            or type(payment["valid_before"]) is not int
            or payment["valid_before"] != expires
            or amount > max_cost_micro_usd
        ):
            raise ValueError
        authorization = {
            "from": payer,
            "to": recipient,
            "value": str(amount),
            "validAfter": "0",
            "validBefore": str(expires),
            "nonce": nonce,
        }
        typed = {
            "domain": domain,
            "types": _TYPES,
            "primaryType": "TransferWithAuthorization",
            "message": dict(authorization),
        }
        frozen = json.dumps(
            {"authorization": authorization, "typed_data": typed}, separators=(",", ":")
        )
        return VideoAuthorizationRequest(
            quote_id,
            job_id,
            intent,
            expires,
            value["payment_enabled"],
            frozen,
            accept_upfront_payment,
        )
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise VideoPaymentError("invalid_quote_or_policy") from None


def _signed(
    request: VideoAuthorizationRequest, signature: str
) -> SignedVideoAuthorization:
    request._signable()
    if (
        not isinstance(signature, str)
        or not re.fullmatch(r"0x[0-9a-fA-F]{130}", signature)
        or int(signature[-2:], 16) not in {27, 28}
    ):
        raise VideoPaymentError("unsupported_signature")
    payload = {"authorization": request.authorization, "signature": signature}
    return SignedVideoAuthorization(
        request.quote_id, request.job_id, json.dumps(payload, separators=(",", ":"))
    )


def sign_video_authorization(
    request: VideoAuthorizationRequest,
    signer: Callable[[Dict[str, object]], str],
) -> SignedVideoAuthorization:
    request._signable()
    try:
        signature = signer(request.typed_data)
    except Exception:
        raise VideoPaymentError("signer_failed") from None
    return _signed(request, signature)


async def async_sign_video_authorization(
    request: VideoAuthorizationRequest,
    signer: Callable[[Dict[str, object]], Awaitable[str]],
) -> SignedVideoAuthorization:
    request._signable()
    try:
        signature = await signer(request.typed_data)
    except Exception:
        raise VideoPaymentError("signer_failed") from None
    return _signed(request, signature)
