"""OAuth 2.1 / Google OAuth の HTTP エンドポイント。"""

import base64
import hashlib
import logging
import secrets
import time

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from config import ALLOWED_REDIRECT_URIS, SERVICE_HOST
from features.oauth.google import build_google_auth_url, exchange_code_for_tokens
from features.oauth.state import create_state, verify_state
from features.oauth.storage import save_tokens

logger = logging.getLogger(__name__)


def _base_url(request: Request) -> str:
    """Cloud Run 環境では内部通信が HTTP になるため、X-Forwarded-Proto または
    SERVICE_HOST 環境変数を使って正しい https:// ベース URL を返す。"""
    if SERVICE_HOST:
        return f"https://{SERVICE_HOST}"
    # フォールバック: X-Forwarded-Proto を参照してスキームを補正する
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    scheme = proto or request.url.scheme
    return f"{scheme}://{request.url.netloc}"


async def protected_resource(request: Request) -> JSONResponse:
    """
    RFC 9728 OAuth Protected Resource Metadata。
    Claude.ai が最初に問い合わせ、認可サーバーの場所を発見する。
    """
    base_url = _base_url(request)
    return JSONResponse({
        "resource": base_url,
        "authorization_servers": [base_url],
    })


async def well_known(request: Request) -> JSONResponse:
    """
    RFC 8414 Authorization Server Metadata。
    Claude.ai が接続前に参照する。
    """
    base_url = _base_url(request)
    return JSONResponse({
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "registration_endpoint": f"{base_url}/register",
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

    try:
        token_response = await exchange_code_for_tokens(code)
    except httpx.HTTPStatusError as e:
        logger.error("Token exchange failed: %s", e)
        return HTMLResponse("<h1>トークン交換に失敗しました</h1>", status_code=500)

    user_id = hashlib.sha256(state_data["code_challenge"].encode()).hexdigest()[:32]
    tokens = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token", ""),
        "expiry": time.time() + token_response.get("expires_in", 3600),
        "user_id": user_id,
    }
    save_tokens(user_id, tokens)

    mcp_redirect = state_data["mcp_redirect_uri"]
    mcp_state = state_data.get("mcp_state", "")
    code_challenge = state_data["code_challenge"]

    mcp_code = create_state({"user_id": user_id, "code_challenge": code_challenge})
    redirect_url = f"{mcp_redirect}?code={mcp_code}"
    if mcp_state:
        redirect_url += f"&state={mcp_state}"
    return RedirectResponse(url=redirect_url, status_code=302)


async def register(request: Request) -> JSONResponse:
    """
    RFC 7591 OAuth 2.0 Dynamic Client Registration。
    MCP クライアント（Claude.ai）がクライアント情報を登録する。
    client_id を発行して返す（client_secret 不要）。
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    client_id = secrets.token_urlsafe(16)
    response_data: dict = {
        "client_id": client_id,
        "token_endpoint_auth_method": "none",
        "grant_types": body.get("grant_types", ["authorization_code", "refresh_token"]),
        "response_types": body.get("response_types", ["code"]),
    }
    if "redirect_uris" in body:
        response_data["redirect_uris"] = body["redirect_uris"]
    for field in ("client_name", "client_uri", "scope"):
        if field in body:
            response_data[field] = body[field]

    return JSONResponse(response_data, status_code=201)


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

        digest = hashlib.sha256(code_verifier.encode()).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if computed != code_data["code_challenge"]:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "PKCE verification failed"},
                status_code=400,
            )

        user_id = code_data["user_id"]
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
