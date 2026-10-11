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
- **`video_jobs.py`** — separate lazy `video_jobs` namespace, public typed
  receipts and sanitized `VideoJobError`; synchronous and asynchronous twins.

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
- `credits()` reads Core's canonical three-pocket account view; SDKs do not
  calculate allowances or maintain local free-use counters.
- The sync and async classes are mirror twins — change both together.
- Candidate `video_jobs.submit(body, idempotency_key=...)` requires an explicit
  model, prompt, positive exact integer micro-USD ceiling and caller-persisted
  UUIDv4 key. It snapshots the body, checks credential-free `/health` features,
  then sends one POST to `/videos/jobs`. Core owns pricing/admission/holds.
- `recover` requires exactly one canonical job UUID or header idempotency key.
  Recovery/wait are GET-only, bypass capability preflight and never re-upload.
  Wait bounds its deadline and checks stable job/model/request hash/hold/ceiling.
  A closed job is not refund proof; completion metadata is not media QC.
- New video HTTP paths refuse redirects, bound JSON replies to 64 KiB, and
  sanitize transport/HTTP errors. Delegated user tokens travel only in headers.
  Request bodies are bounded and money is at most `2**53 - 1` for JS parity.
- `image`/`keyframes` are literal frame constraints, not character identity
  references. Separate `reference_image` PNG plus explicit audio/size forwards
  the dark Ingredients recipe contract without creating frame pins. Reject
  mixing these references with `image`/`keyframes` before HTTP. Core owns
  decoding, fixed profile/knob validation, worker capabilities and admission;
  source-health flags alone do not qualify appearance or enable its price.
  Optional `reference_attention_strength` passes through unchanged, separately
  from denoising and motion attention. Do not insert a default or recompute
  graph/intent authority in the client; Core owns those contracts.
  No x402 rail or adapter execution is implemented by the SDK.

## Work Guidance

—

## Verification

- `pytest ../../tests` (or `pytest` from repo root). `respx` mocks all HTTP.

## Child DOX Index

—
