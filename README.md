# AI Power Grid — Python SDK

Open-model, OpenAI-compatible inference across community-operated GPUs.

> **Release status:** `grid-sdk` is published on PyPI. Use a current release so
> the OpenAI-compatible client and native Grid media helpers stay in sync.

The Grid API speaks the OpenAI protocol, so this SDK is a thin layer over the
official `openai` package: it points at the Grid, reads your key from the
environment, and adds Grid-specific conveniences. Everything you know from the
OpenAI SDK works unchanged.

## Install

```bash
pip install grid-sdk
```

## Quick start

Sign in at the [Grid developer console](https://console.aipowergrid.io/dashboard/api-key),
create an API key, then set it as `AIPG_API_KEY`:

```python
from grid_sdk import Grid

client = Grid()  # reads AIPG_API_KEY from the environment

stream = client.chat.completions.create(
    model="gpt-oss-120b",
    messages=[{"role": "user", "content": "Explain AI Power Grid in one line."}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## See what's online

The Grid's available models change as workers connect and disconnect. Don't
hardcode a model blindly — ask which ones are servable right now:

```python
client = Grid()
print(client.online_models())
# ['gpt-oss-120b', 'qwen3-27b', ...]
```

An empty list means no workers are connected — requests will 503 until one is.

## Credits

```python
credits = client.grid.credits()
print(credits["total_spendable_usd"])
```

This is Core's canonical promotional, daily-free, and purchased account view.
The SDK does not maintain a local free-use counter.

## Async

```python
import asyncio
from grid_sdk import AsyncGrid

async def main():
    client = AsyncGrid()
    resp = await client.chat.completions.create(
        model="gpt-oss-120b",
        messages=[{"role": "user", "content": "Hi"}],
    )
    print(resp.choices[0].message.content)

asyncio.run(main())
```

## Video, img2img, ControlNet, LoRAs — the full Grid

The OpenAI-compatible surface covers text and basic txt2img. For the full media
parameter surface, use `client.grid`, which calls the synchronous `/v1` image
and video endpoints:

```python
client = Grid()

# Video:
result = client.grid.video(
    prompt="a timelapse of a city at night",
    model="LTX-2.3",
    width=768, height=512, seconds=4, fps=24,
)

# img2img / ControlNet / LoRAs — anything the workers support:
result = client.grid.image(
    prompt="make it watercolor",
    models=["FLUX.2 Klein 4B FP8"],
    source_image="<base64>",
    loras=[{"name": "watercolor", "model": 1.0}],
)

# Or full control with a raw payload:
result = client.grid.generate({"prompt": "...", "models": [...], "params": {...}})
```

`client.grid` waits for the synchronous Grid response and returns the finished
OpenAI-shaped result. Use `timeout` for long media jobs. These existing calls
do not use the separate video-jobs lifecycle below.

## Candidate Durable Video Jobs

This branch's `0.2.0a1` adds `client.grid.video_jobs` (and its `AsyncGrid`
twin). It requires the candidate Core `/v1/videos/jobs` contract, which is
default-off and **not a public production feature yet**. Installing this SDK
does not enable admission, qualify a worker or authorize spending.

```python
from uuid import uuid4

jobs = client.grid.video_jobs
key = str(uuid4())
body = {
    "model": "LTX-2.5 Distilled BF16",
    "prompt": "A person waves from inside a parked car",
    "frames": 33,
    "fps": 24,
    "max_cost_micro_usd": 50_000,  # $0.05 ceiling, not a quote
    # Audio-to-video: reference_audio="data:audio/wav;base64,..."
    # Video-to-video: also reference_video="data:video/mp4;base64,..."
    # Video reference requires an explicit size, e.g. size="768x512".
}
# Durably save key + immutable body in your application's private journal FIRST.
# Do not generate a fresh key when recovering this operation.
receipt = jobs.submit(body, idempotency_key=key)
# Save the accepted receipt before waiting or downloading any result.
terminal = jobs.wait(receipt, timeout=600)
```

`submit` checks `/health` contract features without credentials, then sends
**one POST**. Core still owns worker availability, recipe/input validation,
live pricing and the atomic credit hold. There is no model fallback, automatic
POST retry, asset download or client-side billing counter. Costs are integer
micro-USD, limited to `2**53 - 1` for exact parity with JavaScript.

If the reply is lost, malformed, cancelled or fails after POST begins, preserve
the saved key and use `jobs.recover(idempotency_key=key)`. Once you have a job
ID, use `jobs.recover(job_id=receipt["job_id"])` or `jobs.wait(receipt)`.
Recovery is **GET-only**, does not re-upload sources, and bypasses capability
preflight so accepted jobs remain recoverable after new admission is disabled.
404/409/5xx are surfaced; none triggers another submission. A `VideoJobError`
reports sanitized `kind`, `http_status`, and `submission_uncertain`; HTTP errors
after POST are conservatively uncertain, even if Core probably rejected them.
Cancellation also requires recovery; it does not prove the job was cancelled.

`wait` returns `completed` or `closed_without_result`, validating stable job,
model, request hash, held amount and ceiling on every poll. The latter means
no recoverable output, **not proof of a refund**. Timeout does not release a
hold or start another render. The returned hashes are metadata commitments;
the SDK does not download, hash or quality-check the output.

For delegated service calls, pass `user_token=...` to submit/recover/wait;
it travels only in `X-Grid-User-Token`, never a URL. Keep service credentials
server-side. The SDK refuses redirects on the new authenticated paths.

Source inputs must be inline, server-validated WAV/MP4, not arbitrary remote
URLs. Audio uses stereo PCM16 WAV at 48 kHz, exactly `frames * 2000` samples
at 24 fps. Video uses frame-matched 24-fps H.264 MP4 plus a separate WAV and
explicit output size. Current LTX frame/recipe gates remain authoritative.
An `image` or timed `keyframes` pin constrains actual frames: **it is not an
appearance-only identity reference**. Character-reference adapters are separate
qualification work, not supported by this helper. x402 video payments are a
proposal, not an implemented SDK payment rail.

## It's just OpenAI underneath

`Grid` subclasses `openai.OpenAI`, so anything the OpenAI SDK does — images,
tool calling, structured output, the full `.chat`/`.images`/`.models` surface —
works here too. You can also point existing OpenAI code at the Grid by setting
`base_url="https://api.aipowergrid.io/v1"` if you'd rather not switch packages.

## Candidate Qualification

Unit tests mock all HTTP (`pytest tests`). Optional cross-repo tests exercise
Core's real scoped authentication and SQL holds, but synthetic storage/workers,
including accepted-reply loss and recovery after admission rollback. Build the
JS peer first, then run from this SDK checkout with Core's locked test Python:

```bash
PYTHONPATH=/absolute/path/to/candidate-core \
AIPG_JS_VIDEO_QUALIFICATION=/absolute/path/to/js-peer/qualification/core-wire.mjs \
/absolute/path/to/core-test-python -m pytest qualification/test_core_video_jobs.py
```

Use an isolated scratch `CREDITS_TEST_DB_URL` for PostgreSQL; otherwise its
cases skip and only SQLite is proved. Source decoder skips are not successful
qualification. This harness does not run GPUs, use R2 or spend live credits.

## Config

| | |
|---|---|
| `Grid(api_key=...)` | Explicit key (overrides env) |
| `AIPG_API_KEY` | Env var read when no key is passed |
| `Grid(base_url=...)` | Override the endpoint (default `https://api.aipowergrid.io/v1`) |

## Links

- [Docs](https://aipowergrid.io/docs)
- [Get an API key](https://console.aipowergrid.io/dashboard/api-key)
- [Discord](https://discord.gg/W9D8j6HCtC)

## License

MIT
