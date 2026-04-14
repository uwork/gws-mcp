"""Starlette アプリの組み立て。"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount, Route

from features.mcp.server import mcp
from features.oauth.routes import (
    authorize,
    callback,
    protected_resource,
    token,
    well_known,
)

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
