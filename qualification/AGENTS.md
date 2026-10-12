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
- Also exercise separate Dev Ingredients audio/appearance and motion/appearance
  profiles, with reference attention omitted or explicit, using decoded
  synthetic PNG/WAV/MP4 and an explicit isolated fixture tariff. Require the
  appearance worker feature, no opening pin, distinct private bindings and
  100,834-micro hold/charge. This does not price/admit the real candidate or
  qualify native GPU/R2/identity, even when the SQL proof runs on Postgres.
- Real JavaScript transport cases additionally serve the isolated router on an
  ephemeral IPv4 loopback socket and run the peer's `core-http.mjs`, without
  mocking fetch. Supply fixture credentials over stdin only and clear the child
  environment except PATH. These include both appearance modes/attention
  choices, not just the ordinary source protocol. Require unauthenticated
  health, one actual POST, the committed guide/control, owner/key GET recovery,
  and real 401/403/404 isolation after settlement and
  admission rollback. Stop the child and local server in every terminal path.
  Lost replies here are a post-commit 503, not a physical network outage.
- Use real source decoders for synthetic MP4/WAV. Missing FFmpeg skips are not
  successful media qualification. PostgreSQL runs require an isolated scratch
  `CREDITS_TEST_DB_URL`; never use a live Grid DB.

## Verification

Run `pytest qualification/test_core_video_jobs.py` with those dependencies and
paths. These checks do not qualify GPU output, funded R2 lifecycle or production.

`test_core_video_payments.py` uses real scoped quote HTTP/SQL, decoded
generated/audio/video fixtures and the standalone MIT payment module. Set
`AIPG_JS_VIDEO_PAYMENTS_QUALIFICATION` to the built peer's
`qualification/video-payments.mjs`; optionally choose its Node executable with
`AIPG_VIDEO_QUALIFICATION_NODE`. Missing peer configuration fails. Both clients
must block signing the actual preview quote; only a local future-enabled copy
exercises new unfunded signatures and Core's actual verifier. Private two-phase
IPC never carries keys/credentials; synthetic signatures are transient private
data, not logged evidence. Terminate children on every path and require
unchanged balance plus zero holds/jobs/ledgers.
Both SDKs must refuse callbacks on an enabled test copy when upfront consent is
omitted or false, then sign only with explicit acceptance of binding-v3 terms.
This is protocol/crypto proof, not wallet UI, live contract/facilitator, receipts,
replay exclusion or funding.
