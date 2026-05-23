"""Starlette アプリの組み立て。"""

import contextlib
import logging

from starlette.applications import Starlette
from starlette.responses import FileResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from config import SERVICE_HOST
from features.mcp.auth import set_user_id
from features.mcp.server import mcp  # ツール登録トリガーも兼ねる
from features.oauth.routes import (
    authorize,
    callback,
    protected_resource,
    register,
    token,
    well_known,
)
from features.oauth.state import verify_state

logger = logging.getLogger(__name__)

_mcp_app = mcp.streamable_http_app()


class BearerAuthMiddleware:
    """MCP Bearer トークンを検証し、user_id を ContextVar にセットする ASGI ミドルウェア。

    MCP クライアントが送る Authorization: Bearer <mcp_token> を解析し、
    トークン内の user_id を取り出してリクエストスコープの ContextVar に格納する。
    Bearer トークンが無い・無効な場合は 401 を返し、claude.ai に OAuth フローを
    開始させる（RFC 9728 resource_metadata discovery）。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth: str = headers.get(b"authorization", b"").decode()
            authenticated = False
            if auth.startswith("Bearer "):
                mcp_token = auth[7:]
                token_data = verify_state(mcp_token, max_age=3600)
                if token_data and "user_id" in token_data:
                    set_user_id(token_data["user_id"])
                    authenticated = True
                else:
                    logger.debug("BearerAuthMiddleware: invalid or expired MCP token")

            if not authenticated:
                host = SERVICE_HOST or headers.get(b"host", b"").decode()
                resource_metadata_url = f"https://{host}/.well-known/oauth-protected-resource"
                www_auth = f'Bearer realm="{host}", resource_metadata="{resource_metadata_url}"'
                response = Response(
                    content=b'{"error":"unauthorized"}',
                    status_code=401,
                    headers={
                        "WWW-Authenticate": www_auth,
                        "Content-Type": "application/json",
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


routes = [
    Route("/.well-known/oauth-protected-resource", protected_resource),
    Route("/.well-known/oauth-authorization-server", well_known),
    Route("/authorize", authorize),
    Route("/callback", callback),
    Route("/register", register, methods=["POST"]),
    Route("/token", token, methods=["GET", "POST"]),
    Route("/favicon.ico", lambda _: FileResponse("static/favicon.ico")),
    Mount("/", app=BearerAuthMiddleware(_mcp_app)),
]

app = Starlette(routes=routes, lifespan=lifespan)
