"""
gws-mcp Phase 2: OAuth 2.1 Authorization Server 実装

2 レイヤー構造:
  Layer 1: MCP 認証 — MCPサーバー自身が OAuth 2.1 AS として動作
           /.well-known/oauth-authorization-server, /authorize, /token, /callback
  Layer 2: Google 認証 — Google OAuth でアクセストークンを取得
           access_token / refresh_token を Firestore に永続化
"""

import base64
import contextlib
import hashlib
import logging
import os
import time

import httpx
from google.cloud import firestore, secretmanager
from itsdangerous import URLSafeTimedSerializer
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── 設定 ────────────────────────────────────────────────────────────────────

PROJECT_ID = os.environ.get("PROJECT_ID", "")
REGION = os.environ.get("REGION", "asia-northeast1")
SERVICE = os.environ.get("SERVICE", "gws-mcp")
SECRET_NAME_CLIENT_ID = os.environ.get("SECRET_NAME_CLIENT_ID", "mcp-google-client-id")
SECRET_NAME_CLIENT_SECRET = os.environ.get("SECRET_NAME_CLIENT_SECRET", "mcp-google-client-secret")
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "mcp_tokens")
# Cloud Run デプロイ後に設定するリダイレクト URI
# 例: https://gws-mcp-xxxx-an.a.run.app/callback
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8080/callback")
# state トークン署名キー（本番では Secret Manager から取得）
STATE_SECRET_KEY = os.environ.get("STATE_SECRET_KEY", "dev-secret-change-in-production")
# MCP クライアントとして許可する redirect_uri（改行区切りで複数指定可）
_ALLOWED_REDIRECT_URIS_ENV = os.environ.get(
    "ALLOWED_REDIRECT_URIS",
    "https://claude.ai/api/mcp/auth_callback\nhttp://localhost:8080/callback",
)
ALLOWED_REDIRECT_URIS: frozenset[str] = frozenset(
    u.strip() for u in _ALLOWED_REDIRECT_URIS_ENV.splitlines() if u.strip()
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive.readonly"

# ─── Secret Manager ──────────────────────────────────────────────────────────

_secret_cache: dict[str, str] = {}


def get_secret(secret_name: str) -> str:
    """Secret Manager からシークレットを取得する。結果はメモリにキャッシュ。"""
    if secret_name in _secret_cache:
        return _secret_cache[secret_name]
    client = secretmanager.SecretManagerServiceClient()
    resource = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": resource})
    value = response.payload.data.decode("utf-8").strip()
    _secret_cache[secret_name] = value
    return value


# ─── Firestore ───────────────────────────────────────────────────────────────

_db: firestore.Client | None = None


def get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID)
    return _db


def save_tokens(user_id: str, tokens: dict) -> None:
    """Firestore にトークンを保存する。"""
    doc = get_db().collection(FIRESTORE_COLLECTION).document(user_id)
    doc.set(tokens)


def load_tokens(user_id: str) -> dict | None:
    """Firestore からトークンを読み込む。"""
    doc = get_db().collection(FIRESTORE_COLLECTION).document(user_id).get()
    return doc.to_dict() if doc.exists else None


def delete_tokens(user_id: str) -> None:
    """Firestore からトークンを削除する。"""
    get_db().collection(FIRESTORE_COLLECTION).document(user_id).delete()


# ─── state トークン ───────────────────────────────────────────────────────────

_serializer = URLSafeTimedSerializer(STATE_SECRET_KEY)


def create_state(data: dict) -> str:
    return _serializer.dumps(data)


def verify_state(token: str, max_age: int = 600) -> dict | None:
    try:
        return _serializer.loads(token, max_age=max_age)
    except Exception:
        return None


# ─── OAuth ヘルパー ───────────────────────────────────────────────────────────

def build_google_auth_url(state: str) -> str:
    client_id = get_secret(SECRET_NAME_CLIENT_ID)
    params = {
        "client_id": client_id,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"


async def exchange_code_for_tokens(code: str) -> dict:
    """Google OAuth 認可コードをトークンと交換する。"""
    client_id = get_secret(SECRET_NAME_CLIENT_ID)
    client_secret = get_secret(SECRET_NAME_CLIENT_SECRET)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """リフレッシュトークンで新しいアクセストークンを取得する。"""
    client_id = get_secret(SECRET_NAME_CLIENT_ID)
    client_secret = get_secret(SECRET_NAME_CLIENT_SECRET)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        return response.json()


async def get_valid_access_token(user_id: str) -> str | None:
    """
    Firestore から有効なアクセストークンを返す。
    期限切れの場合はリフレッシュトークンで更新する。
    """
    tokens = load_tokens(user_id)
    if tokens is None:
        return None

    # 有効期限チェック（60秒のバッファ）
    if tokens.get("expiry", 0) > time.time() + 60:
        return tokens["access_token"]

    # リフレッシュ
    if "refresh_token" not in tokens:
        return None
    refreshed = await refresh_access_token(tokens["refresh_token"])
    updated = {
        **tokens,
        "access_token": refreshed["access_token"],
        "expiry": time.time() + refreshed.get("expires_in", 3600),
    }
    if "refresh_token" in refreshed:
        updated["refresh_token"] = refreshed["refresh_token"]
    save_tokens(user_id, updated)
    return updated["access_token"]


# ─── MCP サーバー ─────────────────────────────────────────────────────────────

# Cloud Run のホスト名（例: gws-mcp-51272669646.us-central1.run.app）
SERVICE_HOST = os.environ.get("SERVICE_HOST", "localhost:8080")

mcp = FastMCP(
    "gws-mcp",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[SERVICE_HOST, "localhost", "localhost:8080"],
    ),
)


@mcp.tool()
def ping() -> str:
    """サーバーの疎通確認を行う。正常稼働中なら 'pong' を返す。"""
    return "pong"


# ─── OAuth 2.1 エンドポイント ─────────────────────────────────────────────────

async def protected_resource(request: Request) -> JSONResponse:
    """
    RFC 9728 OAuth Protected Resource Metadata。
    Claude.ai が最初に問い合わせ、認可サーバーの場所を発見する。
    """
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse({
        "resource": base_url,
        "authorization_servers": [base_url],
    })


async def well_known(request: Request) -> JSONResponse:
    """
    RFC 8414 Authorization Server Metadata。
    Claude.ai が接続前に参照する。
    """
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse({
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


async def authorize(request: Request) -> Response:
    """
    Layer 1: MCP クライアント（Claude.ai）から認可リクエストを受け取り、
    Google OAuth の認可画面にリダイレクトする。
    PKCE の code_challenge / code_challenge_method は state に埋め込んで保持する。
    """
    params = dict(request.query_params)
    required = ["response_type", "client_id", "redirect_uri", "code_challenge"]
    for p in required:
        if p not in params:
            return JSONResponse(
                {"error": "invalid_request", "error_description": f"Missing {p}"},
                status_code=400,
            )

    if params.get("code_challenge_method", "S256") != "S256":
        return JSONResponse(
            {"error": "invalid_request", "error_description": "Only S256 supported"},
            status_code=400,
        )

    if params["redirect_uri"] not in ALLOWED_REDIRECT_URIS:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "Unauthorized redirect_uri"},
            status_code=400,
        )

    # MCP クライアントの情報を state に保存（コールバック後に復元）
    state_data = {
        "mcp_redirect_uri": params["redirect_uri"],
        "mcp_client_id": params["client_id"],
        "mcp_state": params.get("state", ""),
        "code_challenge": params["code_challenge"],
    }
    google_state = create_state(state_data)
    auth_url = build_google_auth_url(google_state)
    return RedirectResponse(url=auth_url, status_code=302)


async def callback(request: Request) -> Response:
    """
    Layer 2: Google OAuth コールバック。
    認可コードを受け取りトークン交換 → Firestore 保存 → MCP クライアントへリダイレクト。
    """
    code = request.query_params.get("code")
    state_token = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return HTMLResponse(f"<h1>認証エラー</h1><p>{error}</p>", status_code=400)
    if not code or not state_token:
        return HTMLResponse("<h1>不正なリクエスト</h1>", status_code=400)

    state_data = verify_state(state_token)
    if state_data is None:
        return HTMLResponse("<h1>state トークンが無効または期限切れです</h1>", status_code=400)

    # Google からトークンを取得
    try:
        token_response = await exchange_code_for_tokens(code)
    except httpx.HTTPStatusError as e:
        logger.error("Token exchange failed: %s", e)
        return HTMLResponse("<h1>トークン交換に失敗しました</h1>", status_code=500)

    # ユーザー識別子: state 内の code_challenge のハッシュを使用
    user_id = hashlib.sha256(state_data["code_challenge"].encode()).hexdigest()[:32]
    tokens = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token", ""),
        "expiry": time.time() + token_response.get("expires_in", 3600),
        "user_id": user_id,
    }
    save_tokens(user_id, tokens)

    # MCP クライアントに渡す認可コード（user_id を code として使用）
    mcp_redirect = state_data["mcp_redirect_uri"]
    mcp_state = state_data.get("mcp_state", "")
    code_challenge = state_data["code_challenge"]

    # MCPの認可コードとして user_id + code_challenge を署名して返す
    mcp_code = create_state({"user_id": user_id, "code_challenge": code_challenge})
    redirect_url = f"{mcp_redirect}?code={mcp_code}"
    if mcp_state:
        redirect_url += f"&state={mcp_state}"
    return RedirectResponse(url=redirect_url, status_code=302)


async def token(request: Request) -> JSONResponse:
    """
    Layer 1: MCP クライアントが認可コードをアクセストークンと交換する。
    PKCE の code_verifier を検証する。
    GET はエンドポイント疎通確認用に 200 を返す。
    """
    if request.method == "GET":
        return JSONResponse({"token_endpoint": "ready"})

    if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        form = await request.form()
        params = dict(form)
    else:
        try:
            params = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_request"}, status_code=400)

    grant_type = params.get("grant_type")
    if grant_type == "authorization_code":
        code = params.get("code", "")
        code_verifier = params.get("code_verifier", "")
        if not code or not code_verifier:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "Missing code or code_verifier"},
                status_code=400,
            )

        code_data = verify_state(code)
        if code_data is None:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "Invalid or expired code"},
                status_code=400,
            )

        # PKCE 検証: SHA256(code_verifier) == code_challenge
        digest = hashlib.sha256(code_verifier.encode()).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if computed != code_data["code_challenge"]:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "PKCE verification failed"},
                status_code=400,
            )

        user_id = code_data["user_id"]
        # MCP アクセストークンとして user_id を署名して発行（有効期限1時間）
        mcp_token = create_state({"user_id": user_id, "issued_at": time.time()})
        return JSONResponse({
            "access_token": mcp_token,
            "token_type": "Bearer",
            "expires_in": 3600,
        })

    elif grant_type == "refresh_token":
        refresh = params.get("refresh_token", "")
        if not refresh:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        token_data = verify_state(refresh, max_age=60 * 60 * 24 * 30)  # 30日
        if token_data is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        user_id = token_data["user_id"]
        mcp_token = create_state({"user_id": user_id, "issued_at": time.time()})
        return JSONResponse({
            "access_token": mcp_token,
            "token_type": "Bearer",
            "expires_in": 3600,
        })

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


# ─── Starlette アプリ組み立て ──────────────────────────────────────────────────

# streamable_http_app() を呼んで session_manager を初期化する
_mcp_app = mcp.streamable_http_app()


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


routes = [
    Route("/.well-known/oauth-protected-resource", protected_resource),
    Route("/.well-known/oauth-authorization-server", well_known),
    Route("/authorize", authorize),
    Route("/callback", callback),
    Route("/token", token, methods=["GET", "POST"]),
    Mount("/", app=_mcp_app),
]

app = Starlette(routes=routes, lifespan=lifespan)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
