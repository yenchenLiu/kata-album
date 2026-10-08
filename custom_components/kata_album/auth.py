"""accessToken management: one lock, 5-minute margin, no credential leaks."""
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections.abc import Awaitable, Callable

import aiohttp

from .const import ACCOUNT_BASE, APP_VERSION, REFRESH_PATH, TOKEN_REFRESH_MARGIN
from .errors import AuthRejected, CloudError

# Status codes meaning "refreshToken is no longer usable". 2006 is the Cognito
# branch we deliberately do not emulate.
_REJECTED_CODES = {2006, 110, 111, 112, 401, 403}


def jwt_exp(token: str) -> int:
    segment = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    return int(claims["exp"])


class KataAuth:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        account: dict,
        persist: Callable[[dict], Awaitable[None]] | None = None,
        base_url: str = ACCOUNT_BASE,
    ) -> None:
        self.session = session
        self.account = dict(account)
        self._persist = persist
        self._base = base_url
        self.access_token: str | None = None
        self.expires_at = 0
        self._lock = asyncio.Lock()

    def _fresh(self) -> bool:
        return bool(
            self.access_token and time.time() < self.expires_at - TOKEN_REFRESH_MARGIN
        )

    def invalidate(self) -> None:
        self.access_token = None
        self.expires_at = 0

    async def ensure_access_token(self) -> str:
        async with self._lock:
            if self._fresh():
                return self.access_token  # type: ignore[return-value]
            return await self._refresh()

    async def _refresh(self) -> str:
        a = self.account
        body = {
            "refreshToken": a["refresh_token"],
            "clientSecret": a["client_secret"],
            "deviceId": a["terminal_device_id"],
            "clientId": a["client_id"],
            "userId": a["user_id"],
        }
        try:
            async with self.session.post(
                self._base + REFRESH_PATH,
                json=body,
                headers={
                    "appVersion": APP_VERSION,
                    "versionFlag": APP_VERSION,
                    "requestID": str(uuid.uuid4()),
                },
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise AuthRejected("refresh rejected by server")
                if response.status >= 400:
                    raise CloudError(f"refresh HTTP {response.status}")
                result = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            # Network trouble is never evidence of an invalid refreshToken.
            raise CloudError(f"refresh network error: {type(err).__name__}") from None

        code = result.get("statusCode")
        if code != 100:
            if code in _REJECTED_CODES:
                raise AuthRejected(f"refresh rejected (statusCode {code})")
            raise CloudError(f"refresh failed (statusCode {code})")

        data = result["body"]
        token = data["access_token"]
        self.access_token = token
        self.expires_at = jwt_exp(token)

        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != a["refresh_token"]:
            a["refresh_token"] = new_refresh
            if self._persist:
                await self._persist(dict(a))
        return token
