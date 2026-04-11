"""
gws-mcp Phase 1: 最小 MCP サーバー（疎通確認用）

ping ツールのみを持ち、認証なしで Cloud Run 上で動作する。
Claude.ai カスタムコネクタからの接続確認が目的。
"""

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gws-mcp")


@mcp.tool()
def ping() -> str:
    """サーバーの疎通確認を行う。正常稼働中なら 'pong' を返す。"""
    return "pong"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    mcp.run(transport="sse", host="0.0.0.0", port=port)
