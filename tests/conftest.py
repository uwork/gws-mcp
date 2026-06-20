"""pytest 共通フィクスチャ。

google.cloud.* はテスト実行時に GCP 認証なしでインポートされるため、
モジュールレベルで sys.modules に差し替える。
conftest.py は pytest が最初に読み込むため、他の features.* インポートより前に実行される。
"""

import base64
import json
import os
import sys
from unittest.mock import MagicMock

# ---- GCP SDK スタブ（features.* インポートより前に差し替える） ----
for _mod in [
    "google",
    "google.cloud",
    "google.cloud.firestore",
    "google.cloud.secretmanager",
    "google.auth",
    "google.auth.transport",
    "google.auth.transport.requests",
    "google.oauth2",
    "google.oauth2.id_token",
]:
    sys.modules.setdefault(_mod, MagicMock())

# ---- テスト用環境変数（config.py のモジュールロード前に設定） ----
os.environ.setdefault("STATE_SECRET_KEY", "test-secret-key-for-pytest")
os.environ.setdefault("PROJECT_ID", "test-project")
os.environ.setdefault(
    "ALLOWED_REDIRECT_URIS",
    "http://localhost:8080/callback",
)

# ---- pytest / Starlette インポート ----
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from features.oauth import routes as oauth_routes

TEST_REDIRECT_URI = "http://localhost:8080/callback"


@pytest.fixture()
def oauth_app():
    """MCP サーバーを含まない最小 OAuth ルートの Starlette アプリ。"""
    return Starlette(
        routes=[
            Route("/.well-known/oauth-protected-resource", oauth_routes.protected_resource),
            Route("/.well-known/oauth-authorization-server", oauth_routes.well_known),
            Route("/authorize", oauth_routes.authorize),
            Route("/callback", oauth_routes.callback),
            Route("/register", oauth_routes.register, methods=["POST"]),
            Route("/token", oauth_routes.token, methods=["GET", "POST"]),
        ]
    )


@pytest.fixture()
def client(oauth_app):
    """リダイレクトを追わない TestClient（リダイレクト先 URL の検証に使う）。"""
    return TestClient(oauth_app, follow_redirects=False)


@pytest.fixture(autouse=True)
def restore_route_globals():
    """各テスト後に routes モジュールのグローバル変数を復元する。"""
    saved = {
        "ALLOWED_REDIRECT_URIS": oauth_routes.ALLOWED_REDIRECT_URIS,
        "ALLOWED_GOOGLE_DOMAINS": oauth_routes.ALLOWED_GOOGLE_DOMAINS,
        "SERVICE_HOST": oauth_routes.SERVICE_HOST,
    }
    yield
    for k, v in saved.items():
        setattr(oauth_routes, k, v)


@pytest.fixture()
def pkce_pair():
    """(code_verifier, code_challenge) のペアを返す。challenge = BASE64URL(SHA256(verifier))。"""
    import hashlib

    verifier = "test-verifier-string-used-for-pkce-testing-abc"
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return {"verifier": verifier, "challenge": challenge}


@pytest.fixture()
def valid_google_state(pkce_pair):
    """/authorize が Google にリダイレクトする際に生成する state トークン。"""
    from features.oauth.state import create_state

    return create_state(
        {
            "mcp_redirect_uri": TEST_REDIRECT_URI,
            "mcp_client_id": "test-client-id",
            "mcp_state": "original-mcp-state",
            "code_challenge": pkce_pair["challenge"],
        }
    )


@pytest.fixture()
def make_jwt():
    """フェイク Google ID トークン（JWT）を生成するファクトリを返す。"""

    def _make(email: str, email_verified: bool = True) -> str:
        payload = {"email": email, "email_verified": email_verified}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        return f"header.{payload_b64}.fakesig"

    return _make
