# SPDX-License-Identifier: MIT
"""AI Power Grid Python SDK.

The Grid API is OpenAI-compatible, so this SDK is a thin layer over the
official `openai` client: it pre-points at the Grid, reads your key from the
environment, and adds a couple of Grid-specific conveniences (listing the
models that actually have workers online). Anything you can do with the
`openai` package, you can do here — same `.chat`, `.images`, `.models`.

    from aipg import AIPG

    client = AIPG()  # reads AIPG_API_KEY from the environment

    stream = client.chat.completions.create(
        model="grid/llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Hello!"}],
        stream=True,
    )
    for chunk in stream:
        print(chunk.choices[0].delta.content or "", end="")
"""

from .client import AIPG, AsyncAIPG, DEFAULT_BASE_URL

__all__ = ["AIPG", "AsyncAIPG", "DEFAULT_BASE_URL"]
__version__ = "0.1.0"
