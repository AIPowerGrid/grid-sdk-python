# SPDX-License-Identifier: MIT
"""AIPG clients — thin subclasses of the OpenAI client.

We subclass rather than wrap so every current and future feature of the
`openai` package (chat, images, streaming, tool use, etc.) is available with
zero extra surface area. We only override the defaults (base URL, key source)
and add Grid-specific helpers.
"""

from __future__ import annotations

import os
from typing import List, Optional

from openai import AsyncOpenAI, OpenAI

DEFAULT_BASE_URL = "https://api.aipowergrid.io/v1"
API_KEY_ENV = "AIPG_API_KEY"


def _resolve_key(api_key: Optional[str]) -> str:
    key = api_key or os.getenv(API_KEY_ENV)
    if not key:
        raise ValueError(
            f"No API key provided. Pass api_key=... or set the {API_KEY_ENV} "
            f"environment variable. Get a free key at https://api.aipowergrid.io/register"
        )
    return key


class AIPG(OpenAI):
    """Synchronous AI Power Grid client.

    Drop-in for `openai.OpenAI`, pre-configured for the Grid:

        client = AIPG()                       # key from AIPG_API_KEY
        client = AIPG(api_key="grid-...")     # or explicit

    Use `client.chat`, `client.images`, etc. exactly as you would with the
    OpenAI SDK. Plus `client.online_models()` to see what's actually servable
    right now (the Grid's model set changes as workers connect/disconnect).
    """

    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL, **kwargs):
        super().__init__(api_key=_resolve_key(api_key), base_url=base_url, **kwargs)

    def online_models(self) -> List[str]:
        """Return the model IDs currently served by connected workers.

        An empty list means no workers are online right now — requests will
        return 503 until one connects. Prefer this over a hardcoded model
        name, since the Grid's available models shift with worker presence.
        """
        return [m.id for m in self.models.list().data]


class AsyncAIPG(AsyncOpenAI):
    """Asynchronous AI Power Grid client. Async twin of :class:`AIPG`."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL, **kwargs):
        super().__init__(api_key=_resolve_key(api_key), base_url=base_url, **kwargs)

    async def online_models(self) -> List[str]:
        """Async variant of :meth:`AIPG.online_models`."""
        models = await self.models.list()
        return [m.id for m in models.data]
