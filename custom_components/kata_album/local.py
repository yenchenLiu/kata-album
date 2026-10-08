"""Local device client. Auth bytes are computed on exactly what is sent."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator

import aiohttp

from .const import FUNC_LIST_PHOTOS
from .errors import LocalError


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()  # noqa: S324 (device protocol)


def build_list_request(device_id: str, start_s: int, end_s: int) -> tuple[bytes, str]:
    """Return (raw body bytes, request id). Dates are seconds, timestamp is ms."""
    body = {
        "version": "1",
        "code": 3,
        "deviceID": device_id,
        "payload": {
            "functionID": FUNC_LIST_PHOTOS,
            "requestID": str(uuid.uuid4()).upper(),
            "timestamp": int(time.time() * 1000),
            "params": {
                "0": {
                    "is_pic": True,
                    "startTime": int(start_s),
                    "endTime": int(end_s),
                    "face_ids": [],
                }
            },
        },
    }
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    return raw.encode("utf-8"), body["payload"]["requestID"]


class KataLocalClient:
    def __init__(self, session, device_id: str, ip: str, port: int, token: str) -> None:
        self.session = session
        self.device_id = device_id
        self.ip, self.port = ip, int(port)
        self.token = token
        self.base_url = f"http://{ip}:{self.port}"

    def _wrap(self, err: Exception) -> LocalError:
        return LocalError(f"local request failed: {type(err).__name__}")

    async def heartbeat(self) -> None:
        try:
            async with self.session.post(
                f"{self.base_url}/heartbeat",
                data=b"",
                headers={"Auth": md5_hex(self.token)},
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
            ) as r:
                if r.status != 200:
                    raise LocalError(f"heartbeat HTTP {r.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise self._wrap(err) from None

    async def list_photos(self, start_s: int, end_s: int) -> list[dict]:
        raw, _ = build_list_request(self.device_id, start_s, end_s)
        auth = hashlib.md5(raw + self.token.encode("utf-8")).hexdigest()  # noqa: S324
        try:
            async with self.session.post(
                f"{self.base_url}/thing_model/func_request",
                data=raw,
                headers={"Content-Type": "application/json", "Auth": auth},
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=False,
            ) as r:
                if r.status != 200:
                    raise LocalError(f"album HTTP {r.status}")
                result = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise self._wrap(err) from None
        try:
            params = result["payload"]["params"]
            if params["0"] != 0:
                raise LocalError("album request rejected")
            return list(params["1"].get("list", []))
        except (KeyError, TypeError, AttributeError):
            raise LocalError("unexpected album response") from None

    async def open_image(self, path: str):
        """Return an open aiohttp response context for a validated /download path."""
        if not path.startswith("/download/photo/") or ".." in path or "\\" in path:
            raise LocalError("path not allowed")
        try:
            resp = await self.session.get(
                f"{self.base_url}{path}",
                headers={"Auth": md5_hex(self.token)},
                timeout=aiohttp.ClientTimeout(total=60, sock_connect=10),
                allow_redirects=False,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise self._wrap(err) from None
        if resp.status != 200:
            resp.release()
            raise LocalError(f"image HTTP {resp.status}")
        return resp


async def limited_chunks(resp, limit: int) -> AsyncIterator[bytes]:
    total = 0
    async for chunk in resp.content.iter_chunked(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise LocalError("image exceeds size limit")
        yield chunk
