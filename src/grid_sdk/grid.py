# SPDX-License-Identifier: MIT
"""Raw Grid access — the full generation surface beyond OpenAI compatibility.

The OpenAI-compatible `/v1` endpoints cover text and basic txt2img. The Grid
can do more — video, image-to-image, ControlNet, LoRAs, post-processing — via
its native queue at `/api/v2/generate/async`. This module exposes that as
`client.grid`, so you get the whole platform from the same client.

    client = AIPG()

    # Video (params depend on the model — passed straight through):
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
        source_processing="img2img",
        loras=[{"name": "watercolor", "model": 1.0}],
    )

    # Or full control with a raw payload:
    result = client.grid.generate({"prompt": "...", "models": [...], "params": {...}})
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx


def _derive_v2_base(base_url: str) -> str:
    """Turn the OpenAI base (…/v1) into the native v2 base (…/api/v2)."""
    root = str(base_url).rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return f"{root}/api/v2"


class GridError(RuntimeError):
    pass


class GridRaw:
    """Synchronous raw-Grid client. Reached via ``AIPG().grid``."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 120.0):
        self._headers = {"apikey": api_key, "Content-Type": "application/json"}
        self._base = _derive_v2_base(base_url)
        self._timeout = timeout

    # ── low level ──

    def submit(self, payload: Dict[str, Any]) -> str:
        """Submit a raw job to /api/v2/generate/async. Returns the job id."""
        with httpx.Client(timeout=self._timeout) as c:
            r = c.post(f"{self._base}/generate/async", headers=self._headers, json=payload)
            if r.status_code not in (200, 202):
                raise GridError(f"submit failed [{r.status_code}]: {r.text[:300]}")
            jid = r.json().get("id")
            if not jid:
                raise GridError(f"no job id returned: {r.text[:300]}")
            return jid

    def check(self, job_id: str) -> Dict[str, Any]:
        """Lightweight progress poll (does not return the generation)."""
        with httpx.Client(timeout=self._timeout) as c:
            r = c.get(f"{self._base}/generate/check/{job_id}", headers=self._headers)
            return r.json() if r.status_code == 200 else {}

    def status(self, job_id: str) -> Dict[str, Any]:
        """Full status including generations once done."""
        with httpx.Client(timeout=self._timeout) as c:
            r = c.get(f"{self._base}/generate/status/{job_id}", headers=self._headers)
            if r.status_code != 200:
                raise GridError(f"status failed [{r.status_code}]: {r.text[:300]}")
            return r.json()

    def wait(self, job_id: str, timeout: float = 300.0, interval: float = 2.0) -> Dict[str, Any]:
        """Poll until the job is done (or timeout). Returns the status payload."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(interval)
            if self.check(job_id).get("done"):
                return self.status(job_id)
        raise GridError(f"job {job_id} did not finish within {timeout}s")

    def generate(self, payload: Dict[str, Any], *, wait: bool = True, timeout: float = 300.0) -> Dict[str, Any]:
        """Submit a raw payload and (by default) wait for the result."""
        jid = self.submit(payload)
        return self.wait(jid, timeout=timeout) if wait else {"id": jid}

    # ── ergonomic builders (everything else flows through **params) ──

    def image(
        self,
        prompt: str,
        *,
        models: List[str],
        width: int = 1024,
        height: int = 1024,
        steps: int = 30,
        cfg_scale: float = 7.5,
        sampler_name: str = "k_euler",
        n: int = 1,
        source_image: Optional[str] = None,
        nsfw: bool = False,
        wait: bool = True,
        timeout: float = 300.0,
        **params: Any,
    ) -> Dict[str, Any]:
        """Image generation with the full param surface (img2img, ControlNet,
        LoRAs, post-processing — pass them via keyword and they flow into
        `params`)."""
        body: Dict[str, Any] = {
            "prompt": prompt,
            "models": models,
            "nsfw": nsfw,
            "censor_nsfw": not nsfw,
            "r2": True,
            "params": {
                "n": n,
                "width": width,
                "height": height,
                "steps": steps,
                "cfg_scale": cfg_scale,
                "sampler_name": sampler_name,
                **params,
            },
        }
        if source_image is not None:
            body["source_image"] = source_image
            body["params"].setdefault("source_processing", "img2img")
        return self.generate(body, wait=wait, timeout=timeout)

    def video(
        self,
        prompt: str,
        *,
        models: List[str],
        width: int = 768,
        height: int = 512,
        wait: bool = True,
        timeout: float = 600.0,
        **params: Any,
    ) -> Dict[str, Any]:
        """Video generation. Param names (length, fps, motion, etc.) depend on
        the model and are passed straight through via keyword args."""
        body = {
            "prompt": prompt,
            "models": models,
            "r2": True,
            "params": {"width": width, "height": height, **params},
        }
        return self.generate(body, wait=wait, timeout=timeout)


class AsyncGridRaw:
    """Asynchronous raw-Grid client. Reached via ``AsyncAIPG().grid``."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 120.0):
        self._headers = {"apikey": api_key, "Content-Type": "application/json"}
        self._base = _derive_v2_base(base_url)
        self._timeout = timeout

    async def submit(self, payload: Dict[str, Any]) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(f"{self._base}/generate/async", headers=self._headers, json=payload)
            if r.status_code not in (200, 202):
                raise GridError(f"submit failed [{r.status_code}]: {r.text[:300]}")
            jid = r.json().get("id")
            if not jid:
                raise GridError(f"no job id returned: {r.text[:300]}")
            return jid

    async def check(self, job_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(f"{self._base}/generate/check/{job_id}", headers=self._headers)
            return r.json() if r.status_code == 200 else {}

    async def status(self, job_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(f"{self._base}/generate/status/{job_id}", headers=self._headers)
            if r.status_code != 200:
                raise GridError(f"status failed [{r.status_code}]: {r.text[:300]}")
            return r.json()

    async def wait(self, job_id: str, timeout: float = 300.0, interval: float = 2.0) -> Dict[str, Any]:
        import asyncio

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            if (await self.check(job_id)).get("done"):
                return await self.status(job_id)
        raise GridError(f"job {job_id} did not finish within {timeout}s")

    async def generate(self, payload: Dict[str, Any], *, wait: bool = True, timeout: float = 300.0) -> Dict[str, Any]:
        jid = await self.submit(payload)
        return await self.wait(jid, timeout=timeout) if wait else {"id": jid}
