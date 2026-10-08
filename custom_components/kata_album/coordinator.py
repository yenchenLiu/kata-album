"""Health check coordinator, recovery manager and photo registry."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import time
from datetime import datetime, timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .auth import KataAuth
from .cloud import KataCloud
from .const import (
    CONF_ACCOUNT, CONF_DEVICE_ID, CONF_LOCAL, CONF_NOTIFY, DOMAIN,
    FAILURES_BEFORE_RECOVERY, LIST_CACHE_SECONDS, MAX_THUMB_BYTES,
    RECOVERY_COOLDOWN, RECOVERY_POLL_SECONDS, SCAN_INTERVAL, STATE_AUTH_REQUIRED,
    STATE_EMPTY, STATE_ERROR, STATE_HEALTHY, STATE_RECOVERING,
    THUMB_PROBE_INTERVAL,
)
from .errors import AuthRejected, KataError, LocalError, NotConfigured
from .local import KataLocalClient, limited_chunks

_LOGGER = logging.getLogger(__name__)


_ID_RE = re.compile(r"^photo/[0-9A-Za-z_-]+$")


def _photo_paths(item: dict) -> tuple[str, str] | None:
    """Build (thumbnail, original) download paths from a 9217 list item.

    Confirmed from the App: /download/<path>_thumb.jpg, _mini.jpg, <path>.png.
    Only device-listed, strictly shaped paths are ever turned into URLs.
    """
    path = item.get("path")
    if not isinstance(path, str) or not _ID_RE.match(path):
        return None
    return f"/download/{path}_thumb.jpg", f"/download/{path}.png"


def day_bounds(day) -> tuple[int, int]:
    """Local midnight -> next local midnight as Unix seconds (DST-safe)."""
    tz = dt_util.get_default_time_zone()
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    return int(start.timestamp()), int(end.timestamp())


class KataCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=SCAN_INTERVAL)
        self.entry = entry
        session = async_get_clientsession(hass)
        self.session = session
        self.device_id = entry.data[CONF_DEVICE_ID]
        self.auth = KataAuth(session, entry.data[CONF_ACCOUNT], self._persist_account)
        self.cloud = KataCloud(session, self.auth, self.device_id,
                               entry.data.get(CONF_NOTIFY))
        self.local: KataLocalClient | None = None
        self._lock = asyncio.Lock()
        self._salt = secrets.token_hex(8)
        self._photos: dict[str, dict] = {}
        self._list_cache: dict[str, tuple[float, list[dict]]] = {}
        self.failures = 0
        self.last_recovery: datetime | None = None
        self.last_success: datetime | None = None
        self._last_probe: datetime | None = None
        self._notified = False
        self.state = STATE_ERROR
        self.today_count = 0
        loc = entry.data.get(CONF_LOCAL)
        if loc:
            self._set_local(loc)

    # ---- persistence ------------------------------------------------------
    async def _persist_account(self, account: dict) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_ACCOUNT: account})

    def _set_local(self, info: dict) -> None:
        self.local = KataLocalClient(self.session, self.device_id,
                                     info["ip"], info["port"], info["token"])

    async def _refresh_local_info(self) -> None:
        info = await self.cloud.get_local_info()
        self._set_local(info)
        if info != self.entry.data.get(CONF_LOCAL):
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_LOCAL: info})

    # ---- photo listing ------------------------------------------------------
    async def _fetch_day(self, day, use_cache: bool = True) -> list[dict]:
        key = day.isoformat()
        hit = self._list_cache.get(key)
        if use_cache and hit and time.monotonic() - hit[0] < LIST_CACHE_SECONDS:
            return hit[1]
        if self.local is None:
            raise LocalError("no local service info")
        start, end = day_bounds(day)
        raw = await self.local.list_photos(start, end)
        items = []
        for it in raw:
            paths = _photo_paths(it)
            if not paths:
                continue
            ts = it.get("start_time") or 0  # milliseconds
            ts = int(ts) // 1000
            pid = hashlib.sha256(f"{self._salt}{it['path']}".encode()).hexdigest()[:20]
            self._photos[pid] = {"thumb": paths[0], "original": paths[1]}
            items.append({"id": pid, "ts": ts})
        items.sort(key=lambda i: i["ts"])
        self._list_cache[key] = (time.monotonic(), items)
        return items

    async def list_day(self, day) -> list[dict]:
        async with self._lock:
            return await self._fetch_day(day)

    def photo_path(self, photo_id: str, kind: str) -> str | None:
        p = self._photos.get(photo_id)
        return p[kind] if p else None

    # ---- checks -----------------------------------------------------------
    async def _check_local(self) -> int:
        if self.local is None:
            await self._refresh_local_info()
        await self.local.heartbeat()  # type: ignore[union-attr]
        items = await self._fetch_day(dt_util.now().date(), use_cache=False)
        await self._maybe_probe_thumb(items)
        return len(items)

    async def _maybe_probe_thumb(self, items: list[dict]) -> None:
        now = dt_util.utcnow()
        if not items or (self._last_probe and now - self._last_probe < THUMB_PROBE_INTERVAL):
            return
        self._last_probe = now
        path = self._photos[items[-1]["id"]]["thumb"]
        resp = await self.local.open_image(path)  # type: ignore[union-attr]
        try:
            async for _ in limited_chunks(resp, MAX_THUMB_BYTES):
                pass
        finally:
            resp.release()

    async def _async_update_data(self) -> dict:
        async with self._lock:
            await self._run_check()
        return self._snapshot()

    async def async_manual_check(self) -> None:
        async with self._lock:
            await self._run_check()
        self.async_set_updated_data(self._snapshot())

    def _snapshot(self) -> dict:
        return {"state": self.state, "last_success": self.last_success,
                "today_count": self.today_count}

    async def _run_check(self) -> None:
        try:
            count = await self._try_local_with_refresh()
        except AuthRejected:
            self.state = STATE_AUTH_REQUIRED
            raise ConfigEntryAuthFailed("refresh token rejected") from None
        except KataError as err:
            _LOGGER.debug("check failed: %s", err)
            self._fail(STATE_ERROR)
            await self._maybe_recover()
            return
        self.failures = 0
        self.today_count = count
        self.last_success = dt_util.utcnow()
        self.state = STATE_HEALTHY if count else STATE_EMPTY
        if self._notified:
            persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_{self.entry.entry_id}")
            self._notified = False

    async def _try_local_with_refresh(self) -> int:
        """Local check; on failure re-read 9230 and retry once."""
        try:
            return await self._check_local()
        except LocalError:
            await self._refresh_local_info()
            return await self._check_local()

    def _fail(self, state: str) -> None:
        self.failures += 1
        self.state = state

    # ---- recovery -----------------------------------------------------------
    def _cooldown_ok(self) -> bool:
        return (self.last_recovery is None
                or dt_util.utcnow() - self.last_recovery >= RECOVERY_COOLDOWN)

    async def _maybe_recover(self) -> None:
        if self.failures >= FAILURES_BEFORE_RECOVERY and self._cooldown_ok():
            await self._recover()

    async def async_manual_recover(self) -> bool:
        async with self._lock:
            ok = await self._recover(force=True)
        self.async_set_updated_data(self._snapshot())
        return ok

    async def _recover(self, force: bool = False) -> bool:
        """Caller holds the lock. Success == local service actually usable."""
        if not force and not self._cooldown_ok():
            return False
        if force and not self._cooldown_ok():
            _LOGGER.warning("Recovery requested inside cooldown; skipped")
            return False
        self.last_recovery = dt_util.utcnow()
        self.state = STATE_RECOVERING
        try:
            await self.cloud.open_local_service()
        except NotConfigured:
            self._notify("MQTT callback is not configured; cannot reopen local service.")
            self.state = STATE_ERROR
            return False
        except AuthRejected:
            self.state = STATE_AUTH_REQUIRED
            raise ConfigEntryAuthFailed("refresh token rejected") from None
        except KataError as err:
            _LOGGER.warning("1021 failed: %s", err)
            self.state = STATE_ERROR
            self._notify("Reopening the local album service failed.")
            return False
        deadline = time.monotonic() + RECOVERY_POLL_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(5)
            try:
                await self._refresh_local_info()
                count = await self._check_local()
            except AuthRejected:
                self.state = STATE_AUTH_REQUIRED
                raise ConfigEntryAuthFailed("refresh token rejected") from None
            except KataError:
                continue
            self.failures, self.today_count = 0, count
            self.last_success = dt_util.utcnow()
            self.state = STATE_HEALTHY if count else STATE_EMPTY
            if self._notified:
                persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_{self.entry.entry_id}")
                self._notified = False
            return True
        self.state = STATE_ERROR
        self._notify("Album service did not recover after 1021.")
        return False

    def _notify(self, message: str) -> None:
        if self._notified:
            return
        self._notified = True
        persistent_notification.async_create(
            self.hass, message, title="Kata Album",
            notification_id=f"{DOMAIN}_{self.entry.entry_id}")
