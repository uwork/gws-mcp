# gws-mcp — Google Sheets MCP Server

## プロジェクト目的

Claude.ai のカスタムコネクタとして接続できるリモート MCP サーバー。  
Google Sheets の読み書きを Claude.ai チャットから自然言語で操作することを目的とする。

## 現在のフェーズ: Phase 1（疎通確認）

`ping` ツールのみを持つ最小実装を Cloud Run にデプロイし、  
Claude.ai カスタムコネクタとして登録・呼び出しが正常に動作することを最初に確認する。

**Phase 1 を最優先とする理由**:  
Claude.ai の MCP OAuth 2.1 対応状況が 2025 年時点で不明確なため、  
まず認証なしで疎通確認を行い、接続基盤の動作を検証する。

---

## ディレクトリ構成

```
gws-mcp/
├── .devcontainer/
│   ├── devcontainer.json      # DevContainer 設定
│   └── Dockerfile             # DevContainer イメージ
├── src/
│   └── main.py                # MCP サーバー実装
├── .env.example               # 環境変数サンプル
├── CLAUDE.md                  # このファイル
├── Dockerfile                 # Cloud Run 用イメージ
├── pyproject.toml             # Python プロジェクト設定
└── README.md
```

---

## ローカル起動コマンド

```bash
# 依存関係インストール
uv sync

# SSE モードで起動（ポート 8080）
uv run python src/main.py

# または環境変数でポート指定
PORT=8080 uv run python src/main.py
```

---

## Cloud Run デプロイコマンド

```bash
# イメージビルド & プッシュ
gcloud builds submit \
  --tag asia-northeast1-docker.pkg.dev/catwark-gws-mcp/gws-mcp/server:latest \
  --project catwark-gws-mcp

# Cloud Run にデプロイ
gcloud run deploy gws-mcp \
  --image asia-northeast1-docker.pkg.dev/catwark-gws-mcp/gws-mcp/server:latest \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --project catwark-gws-mcp
```

---

## 認証アーキテクチャ（2 レイヤー構造）

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: MCP 認証（Claude.ai ↔ MCPサーバー）              │
│                                                             │
│  Claude.ai ──[OAuth 2.1 + PKCE]──▶ MCPサーバー            │
│                ↑                        │                  │
│                └── /.well-known/        │                  │
│                    oauth-authorization- │                  │
│                    server               │                  │
│                                         ▼                  │
│             MCPサーバー自身が Authorization Server として動作│
└─────────────────────────────────────────────────────────────┘
                                │
                                │ Google OAuth コールバック後
                                ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Google 認証（MCPサーバー ↔ Google Sheets API）   │
│                                                             │
│  MCPサーバー ──[Authorization Code Flow]──▶ Google OAuth   │
│       │                                         │          │
│       │◀────── access_token / refresh_token ────┘          │
│       │                                                     │
│       ├── Secret Manager ── client_id / client_secret      │
│       └── Firestore ──────── refresh_token 永続化          │
└─────────────────────────────────────────────────────────────┘
```

---

## Secret Manager / Firestore 役割分担

| ストレージ | 保存内容 | 理由 |
|---|---|---|
| Secret Manager | `mcp-google-client-id` | アプリ固定の機密情報。変更頻度低 |
| Secret Manager | `mcp-google-client-secret` | 同上 |
| Firestore | `access_token`, `refresh_token`, `expiry` | ユーザーごとに異なり、定期更新が必要なため |

Firestore コレクション: `mcp_tokens`  
ドキュメントキー: ユーザー識別子（Phase 2 以降で確定）

---

## 開発フェーズ

| フェーズ | 内容 | 状態 |
|---|---|---|
| Phase 1 | ping ツールのみ・認証なし・Cloud Run 疎通確認 | **進行中** |
| Phase 2 | OAuth 2.1 Authorization Server 実装・PKCE 対応 | 未着手 |
| Phase 3 | Google 認証 + Sheets CRUD 実装 | 未着手 |

---

## 技術的不確実性

- **Claude.ai の MCP OAuth 2.1 対応状況**: 2025 年 3 月 26 日仕様の OAuth 2.1 が Claude.ai カスタムコネクタで実際にどこまでサポートされているか未検証
- **SSE エンドポイント URL**: Cloud Run デプロイ後、Claude.ai が期待する `/sse` パスや `/mcp` パスの確認が必要
- **認証なしコネクタの制限**: Phase 1 では `--allow-unauthenticated` で公開するが、本番では IAM または OAuth で保護すること
