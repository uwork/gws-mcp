"""アプリケーション全体の設定・定数。"""

import os

PROJECT_ID = os.environ.get("PROJECT_ID", "")
REGION = os.environ.get("REGION", "asia-northeast1")
SERVICE = os.environ.get("SERVICE", "gws-mcp")
SERVICE_HOST = os.environ.get("SERVICE_HOST", "")

# Secret Manager のシークレット名（固定値）
SECRET_NAME_CLIENT_ID = "gws-mcp-google-client-id"
SECRET_NAME_CLIENT_SECRET = "gws-mcp-google-client-secret"

# Firestore
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "mcp_tokens")

# OAuth
# SERVICE_HOST が設定されている場合は https://<host>/callback を自動導出する。
# OAUTH_REDIRECT_URI 環境変数で明示的に上書き可能。
_default_redirect_uri = (
    f"https://{SERVICE_HOST}/callback" if SERVICE_HOST else "http://localhost:8080/callback"
)
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", _default_redirect_uri)
_state_secret_key = os.environ.get("STATE_SECRET_KEY", "")
if not _state_secret_key:
    raise RuntimeError(
        "STATE_SECRET_KEY environment variable is required. "
        'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
    )
STATE_SECRET_KEY = _state_secret_key

_ALLOWED_REDIRECT_URIS_ENV = os.environ.get(
    "ALLOWED_REDIRECT_URIS",
    "https://claude.ai/api/mcp/auth_callback\nhttp://localhost:8080/callback",
)
_allowed_set: set[str] = {u.strip() for u in _ALLOWED_REDIRECT_URIS_ENV.splitlines() if u.strip()}
# SERVICE_HOST から自動導出した callback URI も許可リストに含める
if SERVICE_HOST:
    _allowed_set.add(f"https://{SERVICE_HOST}/callback")
ALLOWED_REDIRECT_URIS: frozenset[str] = frozenset(_allowed_set)

# Google OAuth
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = (
    "openid "
    "email "
    "https://www.googleapis.com/auth/spreadsheets "
    "https://www.googleapis.com/auth/presentations "
    "https://www.googleapis.com/auth/documents "
    "https://www.googleapis.com/auth/drive"
)

# 許可する Google ログインドメイン。カンマまたは改行区切り。未設定の場合は制限なし。
_ALLOWED_GOOGLE_DOMAINS_ENV = os.environ.get("ALLOWED_GOOGLE_DOMAINS", "")
ALLOWED_GOOGLE_DOMAINS: frozenset[str] = frozenset(
    d.strip().lower()
    for d in _ALLOWED_GOOGLE_DOMAINS_ENV.replace(",", "\n").splitlines()
    if d.strip()
)
