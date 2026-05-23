"""BearerAuthMiddleware のテスト。

app.py をインポートすると features.mcp.server 経由で FastMCP が初期化されるため、
ここではミドルウェアを単体で再実装して検証する。
"""

import json
import time

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from features.mcp.auth import get_current_user_id, set_user_id
from features.oauth.state import create_state, verify_state


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
            if auth.startswith("Bearer "):
                mcp_token = auth[7:]
                token_data = verify_state(mcp_token, max_age=3600)
                if token_data and "user_id" in token_data:
                    set_user_id(token_data["user_id"])
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


def test_invalid_bearer_does_not_set_user_id():
    client = _make_middleware_client()
    body = client.get("/me", headers={"Authorization": "Bearer garbage-token"}).json()
    assert body["user_id"] is None


def test_no_auth_header_user_id_is_none():
    client = _make_middleware_client()
    body = client.get("/me").json()
    assert body["user_id"] is None


def test_non_bearer_auth_ignored():
    client = _make_middleware_client()
    body = client.get("/me", headers={"Authorization": "Basic dXNlcjpwYXNz"}).json()
    assert body["user_id"] is None


def test_expired_bearer_does_not_set_user_id():
    """max_age=3600 を超えたトークンは user_id を設定しない。"""
    past = time.time() - 3601
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "time.time", return_value=past
    ):
        token = create_state({"user_id": "expired-user", "issued_at": past})
    client = _make_middleware_client()
    body = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["user_id"] is None


def test_token_without_user_id_field_does_not_set_user_id():
    token = create_state({"other_field": "value"})
    client = _make_middleware_client()
    body = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["user_id"] is None


def test_valid_token_preserves_correct_user_id():
    token = _make_valid_token("bob-123")
    client = _make_middleware_client()
    body = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["user_id"] == "bob-123"
