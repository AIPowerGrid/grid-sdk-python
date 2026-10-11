# SDK/Core Qualification

## Purpose

Optional cross-repo checks against an explicitly selected Core checkout and
built JavaScript SDK. Not part of runtime packages or ordinary SDK unit tests.

## Contracts

- Run with Core's locked Python dependencies and `PYTHONPATH` pointing to the
  candidate Core root. The normal SDK test environment cannot run these checks.
- Import Core's scoped-auth/SQL fixtures, not production credentials or URLs.
  Storage, workers, quotes and output bytes are synthetic; SQL/auth are real.
- `AIPG_JS_VIDEO_QUALIFICATION` names the JS peer's `qualification/core-wire.mjs`.
  Build that peer first. Missing peer configuration fails instead of silently
  skipping its parity check.
- Exercise generated/audio/video modes with/without lost accepted replies;
  require one job/hold/payout and one submission per SDK. Recovery after
  admission rollback must be GET-only.
- Use real source decoders for synthetic MP4/WAV. Missing FFmpeg skips are not
  successful media qualification. PostgreSQL runs require an isolated scratch
  `CREDITS_TEST_DB_URL`; never use a live Grid DB.

## Verification

Run `pytest qualification/test_core_video_jobs.py` with those dependencies and
paths. These checks do not qualify GPU output, funded R2 lifecycle or production.
