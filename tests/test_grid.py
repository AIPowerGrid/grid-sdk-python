# SPDX-License-Identifier: MIT
"""Tests for the raw-Grid escape hatch (client.grid).

Verifies base-URL derivation and that the image/video builders produce the
correct /api/v2 payloads (including img2img, LoRAs, and arbitrary passthrough
params). Network calls are stubbed.
"""

from unittest.mock import MagicMock

import pytest

from grid_sdk import AIPG
from grid_sdk.grid import GridRaw, _derive_v2_base


# ── base derivation ──


def test_derive_v2_base_from_v1():
    assert _derive_v2_base("https://api.aipowergrid.io/v1") == "https://api.aipowergrid.io/api/v2"


def test_derive_v2_base_trailing_slash():
    assert _derive_v2_base("https://api.aipowergrid.io/v1/") == "https://api.aipowergrid.io/api/v2"


def test_derive_v2_base_custom_host():
    assert _derive_v2_base("http://localhost:7002/v1") == "http://localhost:7002/api/v2"


# ── client wiring ──


def test_client_exposes_grid():
    client = AIPG(api_key="k")
    assert isinstance(client.grid, GridRaw)
    assert client.grid._base == "https://api.aipowergrid.io/api/v2"
    assert client.grid._headers["apikey"] == "k"


# ── payload builders (capture what generate() would submit) ──


def _capture(grid: GridRaw):
    """Replace generate() with a capturing stub; return the captured payloads."""
    captured = {}
    grid.generate = MagicMock(side_effect=lambda payload, **kw: captured.update({"payload": payload, "kw": kw}) or {"ok": True})
    return captured


def test_image_builder_basic_payload():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.image("a cat", models=["FLUX.1-dev"], width=512, height=768, steps=20)

    p = cap["payload"]
    assert p["prompt"] == "a cat"
    assert p["models"] == ["FLUX.1-dev"]
    assert p["params"]["width"] == 512
    assert p["params"]["height"] == 768
    assert p["params"]["steps"] == 20
    assert p["r2"] is True


def test_image_builder_img2img_sets_source_processing():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.image("watercolor", models=["FLUX.1-dev"], source_image="BASE64DATA")

    p = cap["payload"]
    assert p["source_image"] == "BASE64DATA"
    assert p["params"]["source_processing"] == "img2img"


def test_image_builder_passthrough_params():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.image(
        "x",
        models=["m"],
        loras=[{"name": "watercolor", "model": 1.0}],
        control_type="canny",
    )
    params = cap["payload"]["params"]
    assert params["loras"] == [{"name": "watercolor", "model": 1.0}]
    assert params["control_type"] == "canny"


def test_video_builder_payload_and_passthrough():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.video("a timelapse", models=["LTX-2"], width=768, height=512, length=97, fps=24)

    p = cap["payload"]
    assert p["prompt"] == "a timelapse"
    assert p["models"] == ["LTX-2"]
    assert p["params"]["width"] == 768
    assert p["params"]["length"] == 97  # passthrough video param
    assert p["params"]["fps"] == 24


def test_nsfw_flag_flips_censor():
    grid = GridRaw("k", "https://api.aipowergrid.io/v1")
    cap = _capture(grid)
    grid.image("x", models=["m"], nsfw=True)
    assert cap["payload"]["nsfw"] is True
    assert cap["payload"]["censor_nsfw"] is False
