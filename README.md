# gws-mcp

Google Sheets MCP Server — Claude.ai のカスタムコネクタとして Google Sheets を操作するリモート MCP サーバー。

## 概要

| 項目 | 内容 |
|---|---|
| Transport | SSE（Server-Sent Events） |
| 認証 | OAuth 2.1 + PKCE（Phase 2 以降） |
| デプロイ先 | Google Cloud Run（プロジェクト: catwark-gws-mcp） |
| トークン永続化 | Cloud Firestore |
| シークレット管理 | Secret Manager |

## クイックスタート

### ローカル開発

```bash
# DevContainer を使う場合は VS Code で "Reopen in Container"

# または手動セットアップ
uv sync
PORT=8080 uv run python src/main.py
```

### Cloud Run デプロイ

```bash
gcloud builds submit \
  --tag asia-northeast1-docker.pkg.dev/catwark-gws-mcp/gws-mcp/server:latest \
  --project catwark-gws-mcp

gcloud run deploy gws-mcp \
  --image asia-northeast1-docker.pkg.dev/catwark-gws-mcp/gws-mcp/server:latest \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --project catwark-gws-mcp
```

### Claude.ai カスタムコネクタ登録

1. Claude.ai → Settings → Integrations → Add custom connector
2. URL に Cloud Run のエンドポイントを入力（例: `https://gws-mcp-xxxx-an.a.run.app`）
3. `ping` ツールを呼び出して疎通確認

## フェーズ

- **Phase 1（現在）**: `ping` ツールのみ・認証なし
- **Phase 2**: OAuth 2.1 Authorization Server 実装
- **Phase 3**: Google Sheets CRUD 実装

詳細は [CLAUDE.md](./CLAUDE.md) を参照。
