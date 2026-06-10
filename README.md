# AI Power Grid — Python SDK

Free, decentralized, OpenAI-compatible AI inference.

The Grid API speaks the OpenAI protocol, so this SDK is a thin layer over the
official `openai` package: it points at the Grid, reads your key from the
environment, and adds Grid-specific conveniences. Everything you know from the
OpenAI SDK works unchanged.

## Install

```bash
pip install grid-sdk
```

## Quick start

Get a free API key at [api.aipowergrid.io/register](https://api.aipowergrid.io/register),
then set it as `AIPG_API_KEY`:

```python
from grid_sdk import Grid

client = Grid()  # reads AIPG_API_KEY from the environment

stream = client.chat.completions.create(
    model="grid/llama-3.3-70b-versatile",
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
# ['grid/llama-3.3-70b-versatile', 'grid/qwen3-32b', ...]
```

An empty list means no workers are connected — requests will 503 until one is.

## Async

```python
import asyncio
from grid_sdk import AsyncGrid

async def main():
    client = AsyncGrid()
    resp = await client.chat.completions.create(
        model="grid/llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Hi"}],
    )
    print(resp.choices[0].message.content)

asyncio.run(main())
```

## Video, img2img, ControlNet, LoRAs — the full Grid

The OpenAI-compatible surface covers text and basic txt2img. For everything
else the Grid can do, use `client.grid`, which talks to the native queue:

```python
client = Grid()

# Video — param names (length, fps, motion) depend on the model:
result = client.grid.video(
    prompt="a timelapse of a city at night",
    models=["LTX-2"],
    width=768, height=512, length=97,
)

# img2img / ControlNet / LoRAs — anything the workers support:
result = client.grid.image(
    prompt="make it watercolor",
    models=["FLUX.1-dev"],
    source_image="<base64>",
    loras=[{"name": "watercolor", "model": 1.0}],
)

# Or full control with a raw payload:
result = client.grid.generate({"prompt": "...", "models": [...], "params": {...}})
```

`client.grid` submits, polls, and returns the finished result. Pass
`wait=False` to get the job id back immediately and poll yourself with
`client.grid.status(job_id)`.

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
- [Get a free API key](https://api.aipowergrid.io/register)
- [Discord](https://discord.gg/W9D8j6HCtC)

## License

MIT
