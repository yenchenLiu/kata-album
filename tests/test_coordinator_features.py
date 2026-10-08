"""Coordinator/view contract tests with lightweight HA doubles (not a HA runtime)."""
import asyncio
import importlib
import sys
import types
from datetime import datetime, timezone

import pytest
from test_core import errors


@pytest.fixture
def modules(monkeypatch):
    class Coordinator:
        @classmethod
        def __class_getitem__(cls, item):
            return cls
        async def async_request_refresh(self):
            self.refreshed = True
    class View:
        def json(self, data, **kwargs):
            return data
    names = {
        "homeassistant": {}, "homeassistant.components": {"persistent_notification": object()},
        "homeassistant.config_entries": {"ConfigEntry": object},
        "homeassistant.core": {"HomeAssistant": object},
        "homeassistant.exceptions": {"ConfigEntryAuthFailed": type("ConfigEntryAuthFailed", (Exception,), {})},
        "homeassistant.helpers": {},
        "homeassistant.helpers.aiohttp_client": {"async_get_clientsession": lambda h: None},
        "homeassistant.helpers.update_coordinator": {"DataUpdateCoordinator": Coordinator},
        "homeassistant.components.http": {"HomeAssistantView": View},
        "homeassistant.util": {},
        "homeassistant.util.dt": {
            "get_default_time_zone": lambda: timezone.utc,
            "utc_from_timestamp": lambda t: datetime.fromtimestamp(t, timezone.utc),
            "now": lambda: datetime.now(timezone.utc)},
    }
    for name, attrs in names.items():
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delitem(sys.modules, "kata_album.coordinator", raising=False)
    monkeypatch.delitem(sys.modules, "kata_album.api", raising=False)
    coordinator = importlib.import_module("kata_album.coordinator")
    api = importlib.import_module("kata_album.api")
    yield coordinator, api
    sys.modules.pop("kata_album.coordinator", None)
    sys.modules.pop("kata_album.api", None)


def make_coordinator(mod):
    c = object.__new__(mod.KataCoordinator)
    c._lock = asyncio.Lock()
    c._salt = "test"
    c._photos, c._people, c._list_cache = {}, {}, {"old": (0, [])}
    return c


def test_registry_maps_opaque_id_to_device_id(modules):
    mod, _ = modules
    c = make_coordinator(mod)
    photo = c._register_photo({"id": "1791403948", "path": "photo/1791403948", "start_time": 1791403948000})
    assert photo["id"] != "1791403948" and photo["ts"] == 1791403948
    assert c._photos[photo["id"]]["device_id"] == "1791403948"


def test_people_and_pagination_without_start_stat(modules):
    mod, _ = modules
    c = make_coordinator(mod)
    class Local:
        async def invoke(self, fid, params):
            if fid == 9225:
                return {"familiar": [{"face_id": "face", "name": "Person", "thumb_path": "faces/ID_1/raw"}], "stranger": []}
            if fid == 9227:
                return {"total": 21}
            return {"pic_list": [{"id": str(100 - i), "path": f"photo/{100-i}", "start_time": 100000} for i in range(20)]}
    c.local = Local()
    async def run():
        people = await c.list_people()
        pid = people[0]["id"]
        assert people[0]["avatar"] == "/download/faces/ID_1/raw_mini.jpg"
        assert await c.person_stats(pid) == {"total": 21, "start": None}
        page = await c.person_photos(pid, 101)
        assert not page["done"] and page["next_cursor"] == 81
        # A server repeating the same boundary must not loop forever.
        assert (await c.person_photos(pid, 81))["done"]
    asyncio.run(run())


@pytest.mark.parametrize("fail", [False, True])
def test_delete_invalidates_cache_even_when_uncertain(modules, fail):
    mod, _ = modules
    c = make_coordinator(mod)
    photo = c._register_photo({"id": "100", "path": "photo/100", "start_time": 100000})
    class Local:
        async def invoke(self, fid, params):
            assert fid == 9218 and params == {"0": {"is_pic": True, "list": ["100"]}}
            if fail:
                raise errors.LocalError("timeout")
            return {}
        async def list_photos(self, start, end):
            assert (start, end) == (99, 102)  # only the photo's own second is re-listed
            return []
    c.local = Local()
    if fail:
        with pytest.raises(errors.LocalError):
            asyncio.run(c.delete_photo(photo["id"]))
        assert photo["id"] in c._photos
    else:
        asyncio.run(c.delete_photo(photo["id"]))
        assert photo["id"] not in c._photos and c.refreshed
    assert c._list_cache == {}


def test_delete_is_not_reported_when_photo_is_still_listed(modules):
    mod, _ = modules
    c = make_coordinator(mod)
    photo = c._register_photo({"id": "100", "path": "photo/100", "start_time": 100000})
    class Local:
        async def invoke(self, fid, params):
            return {}  # device acknowledges...
        async def list_photos(self, start, end):
            return [{"id": "100"}]  # ...but the photo is still there
    c.local = Local()
    with pytest.raises(errors.LocalError):
        asyncio.run(c.delete_photo(photo["id"]))
    assert photo["id"] in c._photos and c._list_cache == {}


def test_malformed_people_and_pages_become_local_errors(modules):
    mod, _ = modules
    c = make_coordinator(mod)
    class Local:
        def __init__(self, data):
            self.data = data
        async def invoke(self, fid, params):
            return self.data
    # A malformed entry is skipped; a wrong container type is a LocalError, not a 500.
    c.local = Local({"familiar": [{"name": "no id"}, {"face_id": "f1"}], "stranger": []})
    assert [p["device_id"] for p in asyncio.run(c.list_people())] == ["f1"]
    c.local = Local({"familiar": "oops"})
    with pytest.raises(errors.LocalError):
        asyncio.run(c.list_people())
    c._people = {"p": {"device_id": "f1", "group": "familiar", "avatar": None}}
    c.local = Local({"pic_list": [{"id": "not-a-number", "path": "photo/1"}]})
    with pytest.raises(errors.LocalError):
        asyncio.run(c.person_photos("p", 101))
    assert c.has_person("p") and not c.has_person("missing")


def test_views_reject_non_admin(modules):
    _, api = modules
    from aiohttp import web
    hass = types.SimpleNamespace(data={"kata_album": {"entry": object()}})
    for request in ({}, {"hass_user": types.SimpleNamespace(is_admin=False)}):
        with pytest.raises(web.HTTPUnauthorized):
            api._coordinator(hass, request, "entry")


def test_delete_requires_explicit_confirmation(modules):
    _, api = modules
    from aiohttp import web
    class Request(dict):
        async def json(self):
            return {"id": "opaque"}
    request = Request(hass_user=types.SimpleNamespace(is_admin=True))
    hass = types.SimpleNamespace(data={"kata_album": {"entry": object()}})
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(api.PhotosView(hass).delete(request, "entry"))
