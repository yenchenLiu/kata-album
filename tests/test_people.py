"""Protocol tests with fake device responses; no real media is deleted."""
import asyncio
import hashlib
import json

from test_core import Resp, errors, local


class CaptureSession:
    def __init__(self, body):
        self.body = body
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return Resp(200, self.body)


def test_people_request_uses_exact_signed_bytes():
    session = CaptureSession({"payload": {"params": {"0": 0, "1": {"familiar": [], "stranger": []}}}})
    client = local.KataLocalClient(session, "DEV", "192.168.1.2", 80, "token")
    result = asyncio.run(client.invoke(9225, {"0": ["stranger", "familiar"]}))
    assert result == {"familiar": [], "stranger": []}
    url, options = session.requests[0]
    raw = options["data"]
    assert url.endswith("/thing_model/func_request")
    assert options["headers"]["Auth"] == hashlib.md5(raw + b"token").hexdigest()
    assert json.loads(raw)["payload"]["functionID"] == 9225


def test_delete_uses_device_id_not_path():
    session = CaptureSession({"payload": {"params": {"0": 0}}})
    client = local.KataLocalClient(session, "DEV", "192.168.1.2", 80, "token")
    asyncio.run(client.invoke(9218, {"0": {"is_pic": True, "list": ["1791403948"]}}))
    body = json.loads(session.requests[0][1]["data"])
    assert body["payload"]["params"] == {"0": {"is_pic": True, "list": ["1791403948"]}}


def test_rejected_device_command_is_not_success():
    session = CaptureSession({"payload": {"params": {"0": 5, "1": {}}}})
    client = local.KataLocalClient(session, "DEV", "192.168.1.2", 80, "token")
    try:
        asyncio.run(client.invoke(9218, {"0": {"is_pic": True, "list": ["id"]}}))
        assert False, "rejected delete must raise"
    except errors.LocalError:
        pass


def test_review_cursor_and_page_size():
    session = CaptureSession({"payload": {"params": {"0": 0, "1": {"pic_list": []}}}})
    client = local.KataLocalClient(session, "DEV", "192.168.1.2", 80, "token")
    asyncio.run(client.invoke(9226, {"0": {"face_id": "face", "timestamp": 1791403948, "page_size": 20}}))
    params = json.loads(session.requests[0][1]["data"])["payload"]["params"]["0"]
    assert params["timestamp"] == 1791403948 and params["page_size"] == 20


def test_avatar_download_auth_and_path():
    class ImageResponse:
        status = 200
    class ImageSession:
        async def get(self, url, **kwargs):
            self.url, self.options = url, kwargs
            return ImageResponse()
    session = ImageSession()
    client = local.KataLocalClient(session, "DEV", "192.168.1.2", 80, "token")
    asyncio.run(client.open_image("/download/faces/ID_1784533876857/raw_mini.jpg"))
    assert session.options["headers"]["Auth"] == local.md5_hex("token")
    for path in ("/download/faces/../secret.jpg", "/download/faces/a%2fb.jpg", "/download/faces/a.jpg?x=1", "/download/faces/a.mp4"):
        try:
            asyncio.run(client.open_image(path))
            assert False, "unsafe path accepted"
        except errors.LocalError:
            pass


def test_list_photos_units_and_signed_bytes():
    """Dates are sent in seconds, the request timestamp in milliseconds; auth covers the sent bytes."""
    session = CaptureSession({"payload": {"params": {"0": 0, "1": {"list": [{"id": "1"}]}}}})
    client = local.KataLocalClient(session, "DEV", "192.168.1.2", 80, "tok")
    assert asyncio.run(client.list_photos(1700000000, 1700086400)) == [{"id": "1"}]
    raw = session.requests[0][1]["data"]
    payload = json.loads(raw)["payload"]
    assert payload["functionID"] == 9217
    assert payload["params"]["0"]["startTime"] == 1700000000
    assert payload["params"]["0"]["endTime"] == 1700086400
    assert payload["timestamp"] > 10**12
    assert b": " not in raw and b", " not in raw  # compact JSON, serialized once
    assert session.requests[0][1]["headers"]["Auth"] == hashlib.md5(raw + b"tok").hexdigest()
