"""เอกสาร API (Swagger, ReDoc, openapi.json) ต้องไม่ถูกเสิร์ฟเมื่อปิด API_DOCS_ENABLED

ค่าเริ่มต้นปิด เพื่อให้ production ตอบ 404 ทั้งบนโดเมน API (/docs)
และผ่าน proxy ของหน้าเว็บ (/api/docs → /docs)
"""
import asyncio

from fastapi import FastAPI

from app.config import _bool, fastapi_docs_kwargs, settings

DOC_PATHS = (
    "/docs",
    "/docs/",
    "/redoc",
    "/redoc/",
    "/openapi.json",
    "/docs/oauth2-redirect",
)


def _status(app, path: str) -> tuple[int, bytes]:
    """เรียก ASGI โดยตรง ไม่เข้า lifespan จึงไม่สตาร์ทคิวงานหรือเธรดสำรอง"""
    status: dict[str, int] = {}
    body = bytearray()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    asyncio.run(app(scope, receive, send))
    return status["code"], bytes(body)


def test_flag_defaults_off_and_parses_common_values(monkeypatch):
    monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
    assert _bool("API_DOCS_ENABLED", False) is False
    for value in ("1", "true", "yes", "on", "TRUE"):
        monkeypatch.setenv("API_DOCS_ENABLED", value)
        assert _bool("API_DOCS_ENABLED", False) is True
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("API_DOCS_ENABLED", value)
        assert _bool("API_DOCS_ENABLED", False) is False


def test_disabled_docs_404_while_other_routes_stay():
    app = FastAPI(**fastapi_docs_kwargs(False))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    for path in DOC_PATHS:
        code, body = _status(app, path)
        assert code == 404, path
        assert b'"paths"' not in body
        assert b"/admin" not in body
    code, body = _status(app, "/health")
    assert code == 200 and b"ok" in body


def test_enabled_docs_serve_schema():
    app = FastAPI(**fastapi_docs_kwargs(True))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    assert _status(app, "/docs")[0] == 200
    assert _status(app, "/redoc")[0] == 200
    code, body = _status(app, "/openapi.json")
    assert code == 200
    assert b'"openapi"' in body and b"/health" in body
    assert fastapi_docs_kwargs(False) == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_running_app_hides_docs_unless_flag_is_on():
    from app.main import app

    kwargs = fastapi_docs_kwargs(settings.api_docs_enabled)
    assert app.docs_url == kwargs["docs_url"]
    assert app.redoc_url == kwargs["redoc_url"]
    assert app.openapi_url == kwargs["openapi_url"]
    health, health_body = _status(app, "/health")
    assert health == 200 and b"ok" in health_body
    if settings.api_docs_enabled:
        assert _status(app, "/openapi.json")[0] == 200
        return
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        code, body = _status(app, path)
        assert code == 404, path
        assert b'"paths"' not in body
        assert b"/admin" not in body
