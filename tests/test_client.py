# SPDX-License-Identifier: MIT
"""Tests for the AIPG Python SDK.

These don't hit the network — they verify the SDK's own behavior: key
resolution, default base URL, that it really is an OpenAI client, and that
online_models() maps the models response to a list of IDs.
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from grid_sdk import AIPG, AsyncAIPG, DEFAULT_BASE_URL
from openai import AsyncOpenAI, OpenAI


# ── key resolution + config ──


def test_explicit_key_is_used():
    client = AIPG(api_key="grid-explicit")
    assert client.api_key == "grid-explicit"


def test_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("AIPG_API_KEY", "grid-from-env")
    client = AIPG()
    assert client.api_key == "grid-from-env"


def test_missing_key_raises_with_helpful_message(monkeypatch):
    monkeypatch.delenv("AIPG_API_KEY", raising=False)
    with pytest.raises(ValueError) as exc:
        AIPG()
    assert "AIPG_API_KEY" in str(exc.value)
    assert "register" in str(exc.value)  # points the user at getting a key


def test_default_base_url_points_at_grid():
    client = AIPG(api_key="k")
    assert str(client.base_url).rstrip("/") == DEFAULT_BASE_URL.rstrip("/")


def test_base_url_override():
    client = AIPG(api_key="k", base_url="http://localhost:9999/v1")
    assert "localhost:9999" in str(client.base_url)


def test_is_an_openai_client():
    # Subclassing means all openai features (chat, images, streaming) come free.
    assert isinstance(AIPG(api_key="k"), OpenAI)
    assert isinstance(AsyncAIPG(api_key="k"), AsyncOpenAI)


# ── online_models() ──


def test_online_models_maps_to_ids():
    client = AIPG(api_key="k")
    fake_models = SimpleNamespace(
        data=[SimpleNamespace(id="grid/llama-3.3-70b-versatile"), SimpleNamespace(id="grid/qwen3-32b")]
    )
    client.models.list = MagicMock(return_value=fake_models)

    assert client.online_models() == ["grid/llama-3.3-70b-versatile", "grid/qwen3-32b"]


def test_online_models_empty_when_no_workers():
    client = AIPG(api_key="k")
    client.models.list = MagicMock(return_value=SimpleNamespace(data=[]))
    assert client.online_models() == []


@pytest.mark.asyncio
async def test_async_online_models_maps_to_ids():
    client = AsyncAIPG(api_key="k")

    async def fake_list():
        return SimpleNamespace(data=[SimpleNamespace(id="grid/qwen3-32b")])

    client.models.list = fake_list
    assert await client.online_models() == ["grid/qwen3-32b"]
