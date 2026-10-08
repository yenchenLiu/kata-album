"""Admin-only album API and streaming image proxy."""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAX_ORIGINAL_BYTES, MAX_PREVIEW_BYTES, MAX_THUMB_BYTES
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
    for v in (PhotosView, ImageView, PeopleView, PersonPhotosView, PersonStatsView, AvatarView):
        hass.http.register_view(v(hass))


def _coordinator(hass, request, entry_id):
    user = request.get("hass_user")
    if user is None or not user.is_admin:
        raise web.HTTPUnauthorized()
    c = hass.data.get(DOMAIN, {}).get(entry_id)
    if c is None:
        raise web.HTTPNotFound()
    return c


def _photo_json(entry_id, item):
    tz = dt_util.get_default_time_zone()
    when = dt_util.utc_from_timestamp(item["ts"]).astimezone(tz) if item["ts"] else None
    base = f"/api/kata_album/{entry_id}/photos/{item['id']}"
    return {"id": item["id"], "date": when.date().isoformat() if when else None,
            "captured_at": when.isoformat() if when else None,
            "thumbnail_url": base + "/thumbnail", "preview_url": base + "/preview",
            "original_url": base + "/original"}


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
        out = [_photo_json(entry_id, i) for i in items]
        return self.json(
            {"start": first.isoformat(), "end": last.isoformat(),
             "status": "ready" if out else "empty", "items": out},
            headers={"Cache-Control": "no-store"})

    async def delete(self, request, entry_id):
        c = _coordinator(self.hass, request, entry_id)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest() from None
        if not isinstance(body, dict) or body.get("confirm") is not True or not isinstance(body.get("id"), str):
            raise web.HTTPBadRequest()
        if not c.photo_path(body["id"], "original"):
            raise web.HTTPNotFound()
        try:
            await c.delete_photo(body["id"])
        except KataError:
            return self.json({"status": "delete_unconfirmed"}, status_code=502,
                             headers={"Cache-Control": "no-store"})
        return self.json({"status": "deleted"}, headers={"Cache-Control": "no-store"})


class ImageView(HomeAssistantView):
    url = "/api/kata_album/{entry_id}/photos/{photo_id}/{kind}"
    name = "api:kata_album:image"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    def resolve_path(self, coordinator, photo_id, key):
        return coordinator.photo_path(photo_id, key)

    async def get(self, request: web.Request, entry_id: str, photo_id: str, kind: str):
        c = _coordinator(self.hass, request, entry_id)
        key = {"thumbnail": "thumb", "preview": "preview", "original": "original"}.get(kind)
        if key is None:
            raise web.HTTPNotFound()
        path = self.resolve_path(c, photo_id, key)
        if not path or c.local is None:
            raise web.HTTPNotFound()
        limit = {"thumb": MAX_THUMB_BYTES, "preview": MAX_PREVIEW_BYTES, "original": MAX_ORIGINAL_BYTES}[key]
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


class PeopleView(HomeAssistantView):
    url = "/api/kata_album/{entry_id}/people"
    name = "api:kata_album:people"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request, entry_id):
        c = _coordinator(self.hass, request, entry_id)
        try:
            people = await c.list_people()
        except KataError:
            raise web.HTTPBadGateway() from None
        return self.json({"items": [{"id": p["id"], "name": p["name"], "group": p["group"],
            "avatar_url": f"/api/kata_album/{entry_id}/people/{p['id']}/avatar" if p["avatar"] else None}
            for p in people]}, headers={"Cache-Control": "no-store"})


class PersonPhotosView(PeopleView):
    url = "/api/kata_album/{entry_id}/people/{person_id}/photos"
    name = "api:kata_album:person_photos"

    async def get(self, request, entry_id, person_id):
        c = _coordinator(self.hass, request, entry_id)
        if not c.has_person(person_id):
            raise web.HTTPNotFound()
        try:
            cursor = int(request.query.get("cursor", int(time.time())))
            if cursor < 0 or cursor > int(time.time()) + 60:
                raise ValueError()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest() from None
        try:
            result = await c.person_photos(person_id, cursor)
        except KataError:
            raise web.HTTPBadGateway() from None
        result["items"] = [_photo_json(entry_id, i) for i in result["items"]]
        return self.json(result, headers={"Cache-Control": "no-store"})


class PersonStatsView(PeopleView):
    url = "/api/kata_album/{entry_id}/people/{person_id}/stats"
    name = "api:kata_album:person_stats"

    async def get(self, request, entry_id, person_id):
        c = _coordinator(self.hass, request, entry_id)
        if not c.has_person(person_id):
            raise web.HTTPNotFound()
        try:
            result = await c.person_stats(person_id)
        except KataError:
            raise web.HTTPBadGateway() from None
        return self.json(result, headers={"Cache-Control": "no-store"})


class AvatarView(ImageView):
    url = "/api/kata_album/{entry_id}/people/{person_id}/avatar"
    name = "api:kata_album:avatar"

    def resolve_path(self, coordinator, photo_id, key):
        return coordinator.person_avatar(photo_id)

    async def get(self, request, entry_id, person_id):
        return await super().get(request, entry_id, person_id, "thumbnail")
