# grid_sdk — the SDK package

## Purpose

The importable package. Two pieces: OpenAI-compatible clients (`client.py`) and the native
raw-Grid escape hatch (`grid.py`) for generation beyond the `/v1` surface.

## Ownership

- **`__init__.py`** — public exports (`__all__`) and `__version__`.
- **`client.py`** — `Grid`/`AsyncGrid` (subclasses of `openai.OpenAI`/`AsyncOpenAI`) plus the
  `AIPG`/`AsyncAIPG` aliases. Owns key resolution (`_resolve_key`), `DEFAULT_BASE_URL`,
  the `AIPG_API_KEY` env var, and `online_models()`.
- **`grid.py`** — `GridRaw`/`AsyncGridRaw` (reached via `client.grid`) and `GridError`. POSTs
  synchronously to the `/v1` media endpoints with `httpx`.

## Local Contracts

- **One base, `/v1`.** Clients take the OpenAI base (`…/v1`); `grid.py`'s `GridRaw`/`AsyncGridRaw`
  POST synchronously to `/v1/images/generations` and `/v1/videos/generations` under it.
- **Auth is uniform.** Both the OpenAI surface and the raw-Grid surface use
  `Authorization: Bearer <key>`.
- **Key resolution:** explicit `api_key=` wins, else `AIPG_API_KEY`, else raise `ValueError`.
- **Raw-Grid lifecycle is synchronous:** `generate(payload, endpoint=...)` POSTs and returns the
  finished OpenAI-shaped result directly — no `submit`/`check`/`status`/`wait` poll cycle.
  Errors raise `GridError`; preserve that contract.
- **Builders are thin.** `image()`/`video()` set sane defaults and forward all extra
  keywords into `params`. Add convenience, never gate features the workers support.
- The sync and async classes are mirror twins — change both together.

## Work Guidance

—

## Verification

- `pytest ../../tests` (or `pytest` from repo root). `respx` mocks all HTTP.

## Child DOX Index

—
