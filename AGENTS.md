# DOX framework

- DOX is a hierarchy of AGENTS.md files that carry the durable contracts for this repo.
- Agents must follow the DOX chain on every edit.

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees.
- Any work product must stay understandable from the nearest AGENTS.md plus every parent above it.

## Read Before Editing

1. Read this root AGENTS.md.
2. Identify every path you expect to touch.
3. Walk from repo root to each target, reading every AGENTS.md on the way.
4. The nearest AGENTS.md is the local contract; parents hold repo-wide rules.
5. If docs conflict, the closer doc controls local detail, but no child may weaken DOX.

Do not rely on memory — re-read the applicable chain in-session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done. Update the closest
owning AGENTS.md when a change affects: purpose/scope/ownership; durable structure,
contracts, or workflows; inputs/outputs/permissions/side-effects; or the Child DOX Index.
Remove stale text immediately. Refresh affected parent and child indexes.

## Style

Concise, current, operational. Stable contracts, not diary entries. Broad rules in parents,
concrete detail in children. Delete stale notes instead of explaining history.

---

# grid-sdk — Python SDK for the AI Power Grid

## Purpose

A thin Python client for the Grid API. The Grid speaks the OpenAI protocol, so the SDK
subclasses the official `openai` client, pre-points it at the Grid, reads the key from the
environment, and adds Grid-specific conveniences (`online_models()`, and `client.grid` for
the native v2 generation queue: video / img2img / ControlNet / LoRAs). Published to PyPI as
`grid-sdk`; importable as `grid_sdk`.

## Ownership

- **`src/grid_sdk/`** — the package (clients + raw-Grid helpers). Owned in its own AGENTS.md.
- **`tests/`** — pytest suite (`test_client.py`, `test_grid.py`); uses `respx` to mock HTTP.
- **`pyproject.toml`** — setuptools build, `src/` layout, deps, pytest config.
- `dist/`, `.venv/`, `*.egg-info/` — build/vendored artifacts; do not edit or document.

## Local Contracts

- **Inherit org engineering standards:** `aipg-documentation/engineering-standards/`
  (core + `git.md` + the matching language file).
- **Stay a thin layer.** The OpenAI-compatible surface comes from subclassing `openai`; do
  not re-wrap or shadow it. Only override defaults (base URL, key source) and add helpers.
- **One runtime dependency:** `openai>=1.0.0` (`httpx` ships transitively with it). Do not
  add dependencies casually — thinness is the product.
- **Public API is `__init__.__all__`:** `Grid`, `AsyncGrid`, `AIPG`, `AsyncAIPG`,
  `DEFAULT_BASE_URL`. `AIPG`/`AsyncAIPG` are aliases of `Grid`/`AsyncGrid` and must stay so.
- **Keep `__version__` (in `__init__.py`) in sync with `version` in `pyproject.toml`.**

## Work Guidance

- New public symbols must be added to `__all__` and covered by a test.
- Match existing style: keyword-only params for builders, extra kwargs flow through `**params`.

## Verification

- `pytest` (install with `pip install -e ".[test]"`). 18 tests across client + raw-Grid; HTTP
  is mocked via `respx`, so no live Grid is required.

## Child DOX Index

- [src/grid_sdk/AGENTS.md](src/grid_sdk/AGENTS.md) — the SDK package: clients + raw-Grid access.
