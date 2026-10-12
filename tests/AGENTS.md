# grid-sdk Python tests

## Purpose

Pytest/respx contract tests for the public Python client and synchronous native
Grid media helper.

## Ownership

- `test_client.py` - Grid/OpenAI client defaults, aliases, and public surface.
- `test_grid.py` - `/v1` image/video request and response behavior.
- `test_video_jobs.py` - candidate async-job wire contract, source passthrough,
  delegation, no POST retry, GET recovery, bounded polling and receipt identity.
  Separate appearance tests preserve PNG/audio/optional video and strengths
  through lost-reply recovery, rejecting opening-pin conflicts before HTTP.
  Cover omitted/explicit reference attention in both audio and motion modes;
  the retained request must be unchanged after an uncertain accepted reply.
  Inline fixture strings are transport-only, not decoded media/native proof.
- `test_video_payments.py` - quote-policy, immutable views, disabled-before-
  signer, expiry/failure/cancellation and hidden-signature controls. Mock
  callbacks do not prove ECDSA, wallet UI, funds or HTTP payment.
  Require binding-v3 upfront/EIP-3009 and explicit consent before sync/async
  callbacks; default/false, coerced policy and legacy quotes reject signing.

## Local Contracts

- Mock all HTTP. Never use production API keys or consume live credits.
- Assert exact URL, headers, payload, sync behavior, async parity, and errors.
- Keep public aliases/version/export behavior covered.
- Preserve legacy custom-base construction; only accessing the candidate
  helper requires its `/v1` base. Never replace source/receipt validation with
  live production requests in this suite.

## Work Guidance

- Add a focused regression test with every public or wire-contract change.
- Prefer respx assertions over implementation-specific internal mocks.
- Tests must collect on the SDK's Python 3.9 minimum; postpone annotations
  rather than evaluating newer union-type operators during import.

## Verification

- Install with `pip install -e ".[test]"` and run `pytest`.
- Build package metadata when changing exports or versions.

## Child DOX Index

No child guides are currently required; this file owns `tests/`.
