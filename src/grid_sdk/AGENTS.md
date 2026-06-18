# grid_sdk — the SDK package

## Purpose

The importable package. Two pieces: OpenAI-compatible clients (`client.py`) and the native
raw-Grid escape hatch (`grid.py`) for generation beyond the `/v1` surface.

## Ownership

- **`__init__.py`** — public exports (`__all__`) and `__version__`.
- **`client.py`** — `Grid`/`AsyncGrid` (subclasses of `openai.OpenAI`/`AsyncOpenAI`) plus the
  `AIPG`/`AsyncAIPG` aliases. Owns key resolution (`_resolve_key`), `DEFAULT_BASE_URL`,
  the `AIPG_API_KEY` env var, and `online_models()`.
- **`grid.py`** — `GridRaw`/`AsyncGridRaw` (reached via `client.grid`), `GridError`, and the
  v2-base derivation. Talks directly to the native queue with `httpx`.

## Local Contracts

- **Two base URLs, one input.** Clients take the OpenAI base (`…/v1`). `grid.py`'s
  `_derive_v2_base` strips a trailing `/v1` and appends `/api/v2` for the native queue.
  Keep this derivation correct if either base shape changes.
- **Auth header differs by surface.** The OpenAI surface uses the `openai` client's bearer
  auth; the raw-Grid surface sends the key as the `apikey` header. Do not conflate them.
- **Key resolution:** explicit `api_key=` wins, else `AIPG_API_KEY`, else raise `ValueError`.
- **Raw-Grid job lifecycle:** `submit` → `check` (light poll, returns `{}` on non-200) →
  `status` (full result, raises on non-200) → `wait` (polls `check.done` then `status`).
  `generate(payload, wait=True)` runs the whole flow; `wait=False` returns `{"id": jid}`.
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
