# SPDX-License-Identifier: MIT
"""Raw Grid media access — video + advanced image beyond OpenAI-compat chat.

The OpenAI-compatible ``/v1`` endpoints cover text and basic txt2img. This adds
the grid's SYNCHRONOUS media endpoints — ``/v1/images/generations`` (full param
surface: img2img, LoRAs, styles, samplers) and ``/v1/videos/generations`` — as
``client.grid``. Both are synchronous: the call returns the finished result
(hosted media.aipg.art URLs), no submit/poll. (Replaces the retired horde
``/api/v2`` async queue.)

    client = AIPG()

    vid = client.grid.video("a city timelapse", model="LTX-2.3",
                            width=768, height=512, seconds=4)
    print(vid["data"][0]["url"])

    img = client.grid.image("make it watercolor", model="FLUX.2 Klein 4B FP8",
                            source_image="<base64>", strength=0.6,
                            loras=[{"name": "watercolor", "model": 1.0}])
    print(img["data"][0]["url"])
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx


class GridError(RuntimeError):
    pass


def _v1_base(base_url: str) -> str:
    """The client base already ends in /v1; just strip trailing slashes."""
    return str(base_url).rstrip("/")


def _image_body(
    prompt: str,
    model: Optional[str],
    models: Optional[List[str]],
    width: int,
    height: int,
    steps: Optional[int],
    cfg_scale: Optional[float],
    sampler_name: Optional[str],
    n: int,
    source_image: Optional[str],
    strength: Optional[float],
    negative_prompt: Optional[str],
    loras: Optional[list],
    style: Optional[str],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model or (models[0] if models else None),
        "prompt": prompt,
        "n": n,
        "size": f"{width}x{height}",
    }
    if steps is not None:
        body["steps"] = steps
    if cfg_scale is not None:
        body["cfg_scale"] = cfg_scale
    if sampler_name is not None:
        body["sampler"] = sampler_name
    if negative_prompt is not None:
        body["negative_prompt"] = negative_prompt
    if loras is not None:
        body["loras"] = loras
    if style is not None:
        body["style"] = style
    if source_image is not None:
        body["image"] = source_image
        if strength is not None:
            body["strength"] = strength
    body.update(params)
    return body


def _video_body(
    prompt: str,
    model: Optional[str],
    models: Optional[List[str]],
    width: int,
    height: int,
    seconds: Optional[float],
    fps: Optional[int],
    source_image: Optional[str],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model or (models[0] if models else None),
        "prompt": prompt,
        "size": f"{width}x{height}",
    }
    if seconds is not None:
        body["seconds"] = seconds
    if fps is not None:
        body["fps"] = fps
    if source_image is not None:
        body["image"] = source_image
    body.update(params)
    return body


class GridRaw:
    """Synchronous raw-Grid media client. Reached via ``AIPG().grid``."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 300.0):
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._base = _v1_base(base_url)
        self._timeout = timeout

    def _post(self, path: str, body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(f"{self._base}{path}", headers=self._headers, json=body)
            if r.status_code != 200:
                raise GridError(f"{path} failed [{r.status_code}]: {r.text[:300]}")
            return r.json()

    def _get(self, path: str, timeout: float = 30.0) -> Dict[str, Any]:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(f"{self._base}{path}", headers=self._headers)
            if r.status_code != 200:
                raise GridError(f"{path} failed [{r.status_code}]: {r.text[:300]}")
            return r.json()

    def credits(self, *, timeout: float = 30.0) -> Dict[str, Any]:
        """Return promotional, daily-free, purchased, and spendable credit pockets."""
        return self._get("/account/credits", timeout)

    def generate(
        self, body: Dict[str, Any], *, endpoint: str = "/images/generations", timeout: float = 300.0
    ) -> Dict[str, Any]:
        """Raw passthrough: POST an arbitrary body to a media endpoint
        (default ``/images/generations``). Returns the OpenAI-shaped response."""
        return self._post(endpoint, body, timeout)

    def image(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        models: Optional[List[str]] = None,
        width: int = 1024,
        height: int = 1024,
        steps: Optional[int] = None,
        cfg_scale: Optional[float] = None,
        sampler_name: Optional[str] = None,
        n: int = 1,
        source_image: Optional[str] = None,
        strength: Optional[float] = None,
        negative_prompt: Optional[str] = None,
        loras: Optional[list] = None,
        style: Optional[str] = None,
        timeout: float = 300.0,
        **params: Any,
    ) -> Dict[str, Any]:
        """Image generation with the full param surface (img2img, LoRAs, styles).
        ``models=[id]`` is accepted for back-compat; ``model=id`` is preferred.
        Extra keywords (seed, scheduler, …) flow through to the request body."""
        body = _image_body(
            prompt, model, models, width, height, steps, cfg_scale, sampler_name,
            n, source_image, strength, negative_prompt, loras, style, params,
        )
        return self._post("/images/generations", body, timeout)

    def video(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        models: Optional[List[str]] = None,
        width: int = 768,
        height: int = 512,
        seconds: Optional[float] = None,
        fps: Optional[int] = None,
        source_image: Optional[str] = None,
        timeout: float = 600.0,
        **params: Any,
    ) -> Dict[str, Any]:
        """Video generation (txt2video / img2video)."""
        body = _video_body(prompt, model, models, width, height, seconds, fps, source_image, params)
        return self._post("/videos/generations", body, timeout)


class AsyncGridRaw:
    """Asynchronous raw-Grid media client. Reached via ``AsyncAIPG().grid``."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 300.0):
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._base = _v1_base(base_url)
        self._timeout = timeout

    async def _post(self, path: str, body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{self._base}{path}", headers=self._headers, json=body)
            if r.status_code != 200:
                raise GridError(f"{path} failed [{r.status_code}]: {r.text[:300]}")
            return r.json()

    async def _get(self, path: str, timeout: float = 30.0) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"{self._base}{path}", headers=self._headers)
            if r.status_code != 200:
                raise GridError(f"{path} failed [{r.status_code}]: {r.text[:300]}")
            return r.json()

    async def credits(self, *, timeout: float = 30.0) -> Dict[str, Any]:
        """Async variant of :meth:`GridRaw.credits`."""
        return await self._get("/account/credits", timeout)

    async def generate(
        self, body: Dict[str, Any], *, endpoint: str = "/images/generations", timeout: float = 300.0
    ) -> Dict[str, Any]:
        return await self._post(endpoint, body, timeout)

    async def image(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        models: Optional[List[str]] = None,
        width: int = 1024,
        height: int = 1024,
        steps: Optional[int] = None,
        cfg_scale: Optional[float] = None,
        sampler_name: Optional[str] = None,
        n: int = 1,
        source_image: Optional[str] = None,
        strength: Optional[float] = None,
        negative_prompt: Optional[str] = None,
        loras: Optional[list] = None,
        style: Optional[str] = None,
        timeout: float = 300.0,
        **params: Any,
    ) -> Dict[str, Any]:
        body = _image_body(
            prompt, model, models, width, height, steps, cfg_scale, sampler_name,
            n, source_image, strength, negative_prompt, loras, style, params,
        )
        return await self._post("/images/generations", body, timeout)

    async def video(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        models: Optional[List[str]] = None,
        width: int = 768,
        height: int = 512,
        seconds: Optional[float] = None,
        fps: Optional[int] = None,
        source_image: Optional[str] = None,
        timeout: float = 600.0,
        **params: Any,
    ) -> Dict[str, Any]:
        body = _video_body(prompt, model, models, width, height, seconds, fps, source_image, params)
        return await self._post("/videos/generations", body, timeout)
