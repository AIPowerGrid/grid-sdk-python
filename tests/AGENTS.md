# grid-sdk Python tests

## Purpose

Pytest/respx contract tests for the public Python client and synchronous native
Grid media helper.

## Ownership

- `test_client.py` - Grid/OpenAI client defaults, aliases, and public surface.
- `test_grid.py` - `/v1` image/video request and response behavior.

## Local Contracts

- Mock all HTTP. Never use production API keys or consume live credits.
- Assert exact URL, headers, payload, sync behavior, async parity, and errors.
- Keep public aliases/version/export behavior covered.

## Work Guidance

- Add a focused regression test with every public or wire-contract change.
- Prefer respx assertions over implementation-specific internal mocks.

## Verification

- Install with `pip install -e ".[test]"` and run `pytest`.
- Build package metadata when changing exports or versions.

## Child DOX Index

No child guides are currently required; this file owns `tests/`.
