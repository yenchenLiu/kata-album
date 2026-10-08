"""Admin-only album API and streaming image proxy."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAX_ORIGINAL_BYTES, MAX_THUMB_BYTES
from .errors import KataError
from .local import limited_chunks

_LOGGER = logging.getLogger(__name__)
_FLAG = "_kata_views"
DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 31
_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")


def async_register_views(hass: HomeAssistant) -> None:
    if hass.data.get(_FLAG):
        return
    hass.data[_FLAG] = True
    for v in (PhotosView, ImageView):
        hass.http.register_view(v(hass))


def _coordinator(hass, request, entry_id):
    user = request.get("hass_user")
    if user is None or not user.is_admin:
        raise web.HTTPUnauthorized()
    c = hass.data.get(DOMAIN, {}).get(entry_id)
    if c is None:
        raise web.HTTPNotFound()
    return c


class PhotosView(HomeAssistantView):
    url = "/api/kata_album/{entry_id}/photos"
    name = "api:kata_album:photos"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str):
        c = _coordinator(self.hass, request, entry_id)
        q = request.query
        today = dt_util.now().date()
        try:
            if "date" in q:
                first = last = date.fromisoformat(q["date"])
            else:
                last = date.fromisoformat(q["end"]) if "end" in q else today
                first = (date.fromisoformat(q["start"]) if "start" in q
                         else last - timedelta(days=DEFAULT_RANGE_DAYS - 1))
        except ValueError:
            return self.json({"status": "bad_date"}, status_code=400)
        if first > last or (last - first).days + 1 > MAX_RANGE_DAYS:
            return self.json({"status": "bad_range"}, status_code=400)
        try:
            items = await c.list_range(first, last)
        except KataError as err:
            _LOGGER.debug("list failed: %s", err)
            return self.json({"start": first.isoformat(), "end": last.isoformat(),
                              "status": c.state, "items": []}, status_code=502)
        tz = dt_util.get_default_time_zone()
        base = f"/api/kata_album/{entry_id}/photos"
        out = []
        for i in items:
            when = dt_util.utc_from_timestamp(i["ts"]).astimezone(tz) if i["ts"] else None
            out.append({
                "id": i["id"],
                "date": when.date().isoformat() if when else None,
                "captured_at": when.isoformat() if when else None,
                "thumbnail_url": f"{base}/{i['id']}/thumbnail",
                "original_url": f"{base}/{i['id']}/original",
            })
        return self.json(
            {"start": first.isoformat(), "end": last.isoformat(),
             "status": "ready" if out else "empty", "items": out},
            headers={"Cache-Control": "no-store"})


class ImageView(HomeAssistantView):
    url = "/api/kata_album/{entry_id}/photos/{photo_id}/{kind}"
    name = "api:kata_album:image"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str, photo_id: str, kind: str):
        c = _coordinator(self.hass, request, entry_id)
        if kind not in ("thumbnail", "original"):
            raise web.HTTPNotFound()
        path = c.photo_path(photo_id, "thumb" if kind == "thumbnail" else "original")
        if not path or c.local is None:
            raise web.HTTPNotFound()
        limit = MAX_THUMB_BYTES if kind == "thumbnail" else MAX_ORIGINAL_BYTES
        try:
            upstream = await c.local.open_image(path)
        except KataError:
            raise web.HTTPBadGateway() from None
        try:
            ctype = (upstream.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in _IMAGE_TYPES:
                raise web.HTTPBadGateway()
            length = upstream.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > limit:
                raise web.HTTPBadGateway()
            resp = web.StreamResponse(headers={
                "Content-Type": ctype, "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff"})
            await resp.prepare(request)
            try:
                async for chunk in limited_chunks(upstream, limit):
                    await resp.write(chunk)
            except KataError:
                # Headers already sent; abort the connection so the client sees failure.
                request.transport and request.transport.close()
                return resp
            await resp.write_eof()
            return resp
        finally:
            upstream.release()
