# AI Power Grid — Python SDK

Open-model, OpenAI-compatible inference across community-operated GPUs.

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
OpenAI-shaped result. Use `timeout` for long media jobs; there is no SDK
submit/poll mode on this `/v1` client.

## It's just OpenAI underneath

`Grid` subclasses `openai.OpenAI`, so anything the OpenAI SDK does — images,
tool calling, structured output, the full `.chat`/`.images`/`.models` surface —
works here too. You can also point existing OpenAI code at the Grid by setting
`base_url="https://api.aipowergrid.io/v1"` if you'd rather not switch packages.

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
