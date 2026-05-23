"""BearerAuthMiddleware のテスト。

app.py をインポートすると features.mcp.server 経由で FastMCP が初期化されるため、
ここではミドルウェアを単体で再実装して検証する。
"""

import logging
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from features.mcp.auth import get_current_user_id, set_user_id
from features.oauth.state import create_state, verify_state

_SERVICE_HOST = "testserver"
_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ミドルウェア（app.py からコピー、依存関係なし）
# ---------------------------------------------------------------------------


class _BearerAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth: str = headers.get(b"authorization", b"").decode()
            authenticated = False
            has_token = False
            if auth.startswith("Bearer "):
                has_token = True
                mcp_token = auth[7:]
                token_data = verify_state(mcp_token, max_age=3600)
                if token_data and "user_id" in token_data:
                    set_user_id(token_data["user_id"])
                    authenticated = True
                else:
                    _logger.debug("BearerAuthMiddleware: invalid or expired MCP token")

            if not authenticated:
                host = _SERVICE_HOST or headers.get(b"host", b"").decode()
                resource_metadata_url = f"https://{host}/.well-known/oauth-protected-resource"
                error_part = ', error="invalid_token"' if has_token else ""
                www_auth = (
                    f'Bearer realm="gws-mcp", resource_metadata="{resource_metadata_url}"'
                    f"{error_part}"
                )
                body = b'{"error":"invalid_token"}' if has_token else b'{"error":"unauthorized"}'
                response = Response(
                    content=body,
                    status_code=401,
                    headers={
                        "WWW-Authenticate": www_auth,
                        "Content-Type": "application/json",
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# テスト用エンドポイント
# ---------------------------------------------------------------------------


async def _user_id_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"user_id": get_current_user_id()})


def _make_middleware_client() -> TestClient:
    inner = Starlette(routes=[Route("/me", _user_id_endpoint)])
    app = _BearerAuthMiddleware(inner)
    return TestClient(app, raise_server_exceptions=True)


def _make_valid_token(user_id: str = "test-user-123") -> str:
    return create_state({"user_id": user_id, "issued_at": time.time()})


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------


def test_valid_bearer_sets_user_id():
    token = _make_valid_token("alice")
    client = _make_middleware_client()
    body = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["user_id"] == "alice"


def test_invalid_bearer_returns_401():
    client = _make_middleware_client()
    resp = client.get("/me", headers={"Authorization": "Bearer garbage-token"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"


def test_no_auth_header_returns_401():
    client = _make_middleware_client()
    resp = client.get("/me")
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_non_bearer_auth_returns_401():
    client = _make_middleware_client()
    resp = client.get("/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_expired_bearer_returns_401():
    """max_age=3600 を超えたトークンは 401 を返す。"""
    past = time.time() - 3601
    with __import__("unittest.mock", fromlist=["patch"]).patch("time.time", return_value=past):
        token = create_state({"user_id": "expired-user", "issued_at": past})
    client = _make_middleware_client()
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"


def test_token_without_user_id_field_returns_401():
    token = create_state({"other_field": "value"})
    client = _make_middleware_client()
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"


# RFC 6750 §3.1: WWW-Authenticate ヘッダーの内容検証


def test_no_token_www_authenticate_has_no_error():
    """トークンなしの場合、WWW-Authenticate に error 属性を含めない（RFC 6750 §3.1）。"""
    client = _make_middleware_client()
    resp = client.get("/me")
    www_auth = resp.headers["WWW-Authenticate"]
    assert "resource_metadata=" in www_auth
    assert "error=" not in www_auth


def test_invalid_token_www_authenticate_has_error():
    """無効トークンの場合、WWW-Authenticate に error="invalid_token" を含む（RFC 6750 §3.1）。"""
    client = _make_middleware_client()
    resp = client.get("/me", headers={"Authorization": "Bearer bad-token"})
    www_auth = resp.headers["WWW-Authenticate"]
    assert 'error="invalid_token"' in www_auth
    assert "resource_metadata=" in www_auth


def test_www_authenticate_contains_resource_metadata_url():
    """resource_metadata に /.well-known/oauth-protected-resource の URL が含まれる。"""
    client = _make_middleware_client()
    resp = client.get("/me")
    www_auth = resp.headers["WWW-Authenticate"]
    assert "/.well-known/oauth-protected-resource" in www_auth


def test_valid_token_preserves_correct_user_id():
    token = _make_valid_token("bob-123")
    client = _make_middleware_client()
    body = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["user_id"] == "bob-123"
