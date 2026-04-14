"""アプリケーション全体の設定・定数。"""

import os

PROJECT_ID = os.environ.get("PROJECT_ID", "")
REGION = os.environ.get("REGION", "asia-northeast1")
SERVICE = os.environ.get("SERVICE", "gws-mcp")
SERVICE_HOST = os.environ.get("SERVICE_HOST", "localhost:8080")

# Secret Manager のシークレット名
SECRET_NAME_CLIENT_ID = os.environ.get("SECRET_NAME_CLIENT_ID", "mcp-google-client-id")
SECRET_NAME_CLIENT_SECRET = os.environ.get("SECRET_NAME_CLIENT_SECRET", "mcp-google-client-secret")

# Firestore
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "mcp_tokens")

# OAuth
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8080/callback")
STATE_SECRET_KEY = os.environ.get("STATE_SECRET_KEY", "dev-secret-change-in-production")

_ALLOWED_REDIRECT_URIS_ENV = os.environ.get(
    "ALLOWED_REDIRECT_URIS",
    "https://claude.ai/api/mcp/auth_callback\nhttp://localhost:8080/callback",
)
ALLOWED_REDIRECT_URIS: frozenset[str] = frozenset(
    u.strip() for u in _ALLOWED_REDIRECT_URIS_ENV.splitlines() if u.strip()
)

# Google OAuth
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets "
    "https://www.googleapis.com/auth/drive.readonly"
)
