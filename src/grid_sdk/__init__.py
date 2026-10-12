# SPDX-License-Identifier: MIT
"""AI Power Grid Python SDK.

The Grid API is OpenAI-compatible, so this SDK is a thin layer over the
official `openai` client: it pre-points at the Grid, reads your key from the
environment, and adds Grid-specific conveniences (listing online models, and
`client.grid` for video / advanced image generation). Anything you can do
with the `openai` package, you can do here — same `.chat`, `.images`,
`.models`.

    from grid_sdk import Grid

    client = Grid()  # reads AIPG_API_KEY from the environment

    stream = client.chat.completions.create(
        model="grid/llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Hello!"}],
        stream=True,
    )
    for chunk in stream:
        print(chunk.choices[0].delta.content or "", end="")

`AIPG` / `AsyncAIPG` are kept as aliases of `Grid` / `AsyncGrid`.
"""

from .client import AIPG, AsyncAIPG, AsyncGrid, Grid, DEFAULT_BASE_URL
from .video_jobs import (
    AsyncVideoJobs,
    VideoJob,
    VideoJobError,
    VideoJobs,
    VideoMedia,
    VideoResult,
)
from .video_payments import (
    SignedVideoAuthorization,
    VideoAuthorizationRequest,
    VideoPaymentError,
    async_sign_video_authorization,
    prepare_video_authorization,
    sign_video_authorization,
)

__all__ = [
    "Grid",
    "AsyncGrid",
    "AIPG",
    "AsyncAIPG",
    "DEFAULT_BASE_URL",
    "VideoJobs",
    "AsyncVideoJobs",
    "VideoJob",
    "VideoJobError",
    "VideoMedia",
    "VideoResult",
    "VideoAuthorizationRequest",
    "SignedVideoAuthorization",
    "VideoPaymentError",
    "prepare_video_authorization",
    "sign_video_authorization",
    "async_sign_video_authorization",
]
__version__ = "0.2.0a3"
