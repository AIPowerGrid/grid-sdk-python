# SPDX-License-Identifier: MIT
"""Tests for the raw-Grid media client (client.grid) on /v1.

Verifies the image/video builders POST the right OpenAI-shaped body to the
synchronous /v1 media endpoints (img2img, LoRAs, passthrough params). Network
calls are stubbed.
"""

from unittest.mock import MagicMock

from grid_sdk import AIPG
from grid_sdk.grid import GridRaw


def test_client_exposes_grid():
    client = AIPG(api_key="k")
    assert isinstance(client.grid, GridRaw)
    assert client.grid._base == "https://api.aipowergrid.io/v1"
    assert client.grid._headers["Authorization"] == "Bearer k"


def _capture(grid: GridRaw):
    """Replace _post with a capturing stub; return the captured call."""
    cap = {}
    grid._post = MagicMock(
        side_effect=lambda path, body, timeout: cap.update({"path": path, "body": body})
        or {"data": [{"url": "https://media.aipg.art/x.webp"}]}
    )
    return cap


def test_image_posts_openai_shape():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.image("a cat", model="FLUX.2 Klein 4B FP8", width=512, height=768, steps=20, cfg_scale=3.5)
    assert cap["path"] == "/images/generations"
    b = cap["body"]
    assert b["model"] == "FLUX.2 Klein 4B FP8"
    assert b["prompt"] == "a cat"
    assert b["size"] == "512x768"
    assert b["steps"] == 20
    assert b["cfg_scale"] == 3.5


def test_models_list_back_compat():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.image("x", models=["z-image-turbo"])
    assert cap["body"]["model"] == "z-image-turbo"


def test_image_img2img_fields():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.image("watercolor", model="m", source_image="BASE64", strength=0.6)
    assert cap["body"]["image"] == "BASE64"
    assert cap["body"]["strength"] == 0.6


def test_image_loras_and_passthrough():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.image("x", model="m", loras=[{"name": "watercolor", "model": 1.0}], seed=42)
    assert cap["body"]["loras"] == [{"name": "watercolor", "model": 1.0}]
    assert cap["body"]["seed"] == 42


def test_video_posts_to_videos_endpoint():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.video("a timelapse", model="LTX-2.3", width=768, height=512, seconds=4, fps=24)
    assert cap["path"] == "/videos/generations"
    b = cap["body"]
    assert b["model"] == "LTX-2.3"
    assert b["size"] == "768x512"
    assert b["seconds"] == 4
    assert b["fps"] == 24
