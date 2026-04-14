"""FastMCP サーバーインスタンス（単一の mcp オブジェクト）。

server.py / sheets.py など複数モジュールが同じ mcp インスタンスを参照するため、
ここでのみ生成し他モジュールはここから import する。
"""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from config import SERVICE_HOST

mcp = FastMCP(
    "gws-mcp",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[SERVICE_HOST, "localhost", "localhost:8080"],
    ),
)
