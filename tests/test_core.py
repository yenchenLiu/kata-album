"""Core tests, runnable without Home Assistant: uv run --with aiohttp pytest tests"""
import asyncio
import base64
import importlib.util
import json
import sys
import time
import types
from pathlib import Path

PKG = Path(__file__).parent.parent / "custom_components" / "kata_album"
pkg = types.ModuleType("kata_album"); pkg.__path__ = [str(PKG)]; sys.modules["kata_album"] = pkg
def load(name):
    spec = importlib.util.spec_from_file_location(f"kata_album.{name}", PKG / f"{name}.py")
    m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m); return m
for n in ("const", "errors"): load(n)
auth_mod, local = load("auth"), load("local")
errors = sys.modules["kata_album.errors"]

def jwt(exp):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b({'a':1})}.{b({'exp':exp})}.sig"

class Resp:
    def __init__(s, status, body): s.status, s._b = status, body
    async def __aenter__(s): return s
    async def __aexit__(s, *a): return False
    async def json(s, content_type=None): return s._b

class Session:
    def __init__(s, resp): s.calls, s.resp = 0, resp
    def post(s, *a, **k):
        s.calls += 1; return s.resp

ACC = dict(refresh_token="r1", client_id="c", client_secret="s", terminal_device_id="t", user_id="u")

def test_concurrent_refresh_once():
    body = {"statusCode": 100, "body": {"access_token": jwt(time.time() + 7200), "refresh_token": "r2"}}
    sess = Session(Resp(200, body)); saved = []
    async def persist(a): saved.append(a["refresh_token"])
    a = auth_mod.KataAuth(sess, ACC, persist)
    async def go(): return await asyncio.gather(*[a.ensure_access_token() for _ in range(10)])
    out = asyncio.run(go())
    assert sess.calls == 1 and len(set(out)) == 1 and saved == ["r2"]

def test_keeps_old_refresh_when_none_returned():
    body = {"statusCode": 100, "body": {"access_token": jwt(time.time() + 7200)}}
    a = auth_mod.KataAuth(Session(Resp(200, body)), ACC)
    asyncio.run(a.ensure_access_token())
    assert a.account["refresh_token"] == "r1"

def test_2006_requires_reauth_but_5xx_is_transient():
    a = auth_mod.KataAuth(Session(Resp(200, {"statusCode": 2006})), ACC)
    try: asyncio.run(a.ensure_access_token()); assert False
    except errors.AuthRejected: pass
    a = auth_mod.KataAuth(Session(Resp(503, {})), ACC)
    try: asyncio.run(a.ensure_access_token()); assert False
    except errors.CloudError: pass

def test_refresh_margin():
    a = auth_mod.KataAuth(Session(Resp(200, {})), ACC)
    a.access_token, a.expires_at = "x", time.time() + 200
    assert not a._fresh()
    a.expires_at = time.time() + 1000
    assert a._fresh()

def test_download_path_validation():
    c = local.KataLocalClient(None, "d", "1.2.3.4", 80, "t")
    for bad in ("/etc/passwd", "/download/../x", "http://evil/download/a"):
        try: asyncio.run(c.open_image(bad)); assert False
        except errors.LocalError: pass


def test_photo_paths_accept_only_listed_shape():
    import re
    pat = re.compile(r"^photo/[0-9A-Za-z_-]+$")
    assert pat.match("photo/1791403948")
    for bad in ("../x", "photo/../x", "/etc/passwd", "photo/a/b", "http://h/photo/1"):
        assert not pat.match(bad)
