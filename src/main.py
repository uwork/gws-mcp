"""
gws-mcp エントリポイント。

2 レイヤー構造:
  Layer 1: MCP 認証 — MCPサーバー自身が OAuth 2.1 AS として動作
           /.well-known/oauth-authorization-server, /authorize, /token, /callback
  Layer 2: Google 認証 — Google OAuth でアクセストークンを取得
           access_token / refresh_token を Firestore に永続化
"""

import logging
import os

import uvicorn

from app import app  # noqa: F401

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
