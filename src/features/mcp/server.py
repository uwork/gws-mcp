"""FastMCP サーバーインスタンスとツール定義。"""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from config import SERVICE_HOST

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
