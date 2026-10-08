"""Cloud client: 9230 shadow query and 1021 invoke.

The 1021 body/headers mirror the App request captured from its log. Whether
`notify` is optional is untested, so it is required here (see README).
"""
from __future__ import annotations

import asyncio
import uuid

import aiohttp

from .auth import KataAuth
from .const import (
    APP_VERSION, COMMAND_BASE, DEVICE_BASE, FUNC_OPEN_LOCAL, INVOKE_PATH,
    PROP_LOCAL_INFO, SHADOW_PATH,
)
from .errors import AuthRejected, CloudError, LocalServiceDisabled, NotConfigured



class KataCloud:
    def __init__(self, session, auth: KataAuth, device_id: str, notify: dict | None):
        self.session, self.auth = session, auth
        self.device_id, self.notify = device_id, notify

    async def _post(self, base: str, path: str, body: dict) -> dict:
        for attempt in (0, 1):
            token = await self.auth.ensure_access_token()
            try:
                async with self.session.post(
                    base + path,
                    json=body,
                    headers={
                        "Authorization": token,
                        "appVersion": APP_VERSION,
                        "versionFlag": APP_VERSION,
                        "requestID": str(uuid.uuid4()),
                        "terminalID": self.auth.account["terminal_device_id"],
                        "uuid": self.auth.account["terminal_device_id"],
                        "UserID": self.auth.account["user_id"],
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=False,
                ) as r:
                    expired = r.status == 401
                    if not expired:
                        if r.status >= 400:
                            raise CloudError(f"cloud HTTP {r.status}")
                        return await r.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise CloudError(f"cloud network error: {type(err).__name__}") from None
            if attempt == 0:  # explicit expiry: refresh once, retry once
                self.auth.invalidate()
                continue
            raise AuthRejected("access token rejected after refresh")
        raise CloudError("unreachable")

    async def get_local_info(self) -> dict:
        """Return {'ip','port','token'} from property 9230.

        Confirmed request: {"deviceID": ..., "propertyIDs": [9230]}; success is
        resultCode 100 with data["9230"]["value"]. When the local service is off
        the value is {"is_enable": false} and carries no connection info.
        """
        res = await self._post(
            DEVICE_BASE, SHADOW_PATH,
            {"deviceID": self.device_id, "propertyIDs": [PROP_LOCAL_INFO]},
        )
        if res.get("resultCode") != 100:
            raise CloudError(f"shadow resultCode {res.get('resultCode')}")
        try:
            value = res["data"][str(PROP_LOCAL_INFO)]["value"]
        except (KeyError, TypeError):
            raise CloudError("unexpected shadow response") from None
        if not isinstance(value, dict) or not value.get("is_enable"):
            raise LocalServiceDisabled("local service is disabled")
        try:
            return {"ip": value["ip"], "port": int(value["port"]), "token": value["token"]}
        except (KeyError, TypeError, ValueError):
            raise CloudError("shadow value missing connection info") from None

    async def open_local_service(self) -> None:
        """Send 1021. HTTP success only means the command was accepted."""
        if not self.notify:
            raise NotConfigured("MQTT callback topic missing")
        res = await self._post(
            COMMAND_BASE, INVOKE_PATH,
            {
                "functionID": FUNC_OPEN_LOCAL,
                "params": {},
                "deviceID": self.device_id,
                "notify": self.notify,
            },
        )
        if res.get("resultCode") != 100:
            raise CloudError(f"invoke resultCode {res.get('resultCode')}")
