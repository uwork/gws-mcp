# gws-mcp

Google Sheets MCP Server — Claude.ai のカスタムコネクタとして Google Sheets を操作するリモート MCP サーバー。

## 概要

| 項目 | 内容 |
|---|---|
| Transport | SSE（Server-Sent Events） |
| 認証 | OAuth 2.1 + PKCE（Phase 2 以降） |
| デプロイ先 | Google Cloud Run |
| トークン永続化 | Cloud Firestore |
| シークレット管理 | Secret Manager |

## クイックスタート

### ローカル開発

```bash
# DevContainer を使う場合は VS Code で "Reopen in Container"

# または手動セットアップ
uv sync --extra dev   # dev 依存（pytest, starlette 等）を含めてインストール
PORT=8080 uv run python src/main.py

# テスト実行
uv run pytest
```

### Cloud Run デプロイ

```bash
gcloud builds submit \
  --tag asia-northeast1-docker.pkg.dev/example-gws-mcp/gws-mcp/server:latest \
  --project example-gws-mcp

gcloud run deploy gws-mcp \
  --image asia-northeast1-docker.pkg.dev/example-gws-mcp/gws-mcp/server:latest \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --project example-gws-mcp
```

### Claude.ai カスタムコネクタ登録

1. Claude.ai → Settings → Integrations → Add custom connector
2. URL に Cloud Run のエンドポイントを入力（例: `https://gws-mcp-xxxx-an.a.run.app`）
3. `ping` ツールを呼び出して疎通確認

## フェーズ

- **Phase 1**: `ping` ツールのみ・認証なし
- **Phase 2（現在）**: OAuth 2.1 Authorization Server 実装
- **Phase 3**: Google Sheets CRUD 実装

## Phase 2 セットアップ

### 1. Google Cloud Console で OAuth クライアントを作成

1. [API とサービス] → [認証情報] → [OAuth 2.0 クライアント ID] を作成
2. アプリケーションの種類: **ウェブ アプリケーション**
3. 承認済みのリダイレクト URI に `https://<Cloud Run URL>/callback` を追加

### 2. 環境変数を設定

`.env.example` をコピーして `.env` を作成し、各値を設定する。

```bash
cp .env.example .env
# PROJECT_ID, SERVICE_HOST, STATE_SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET を設定
```

> **注意**: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `STATE_SECRET_KEY` は
> `make tf-apply` 時に Terraform state（GCS）へ**平文で**記録される。
> state バケットの IAM アクセス権は最小権限で管理すること。

### 3. Terraform で GCP リソースと Secret Manager シークレットを作成

```bash
make tf-init
make tf-apply   # Secret Manager へのシークレット初期投入も行われる
```

既存の手動作成シークレットがある場合は事前に `terraform import` が必要:

```bash
terraform -chdir=terraform import \
  google_secret_manager_secret.google_client_id \
  projects/YOUR_PROJECT_ID/secrets/gws-mcp-google-client-id

terraform -chdir=terraform import \
  google_secret_manager_secret.google_client_secret \
  projects/YOUR_PROJECT_ID/secrets/gws-mcp-google-client-secret

terraform -chdir=terraform import \
  google_secret_manager_secret.state_secret_key \
  projects/YOUR_PROJECT_ID/secrets/gws-mcp-state-secret-key
```

> **リネームについて**: v0.x 以前で手動作成した `mcp-state-secret-key` は
> `gws-mcp-state-secret-key` にリネームされた。旧シークレットの値を新名で再登録すること。

### 4. デプロイ

```bash
make deploy
```

詳細は [CLAUDE.md](./CLAUDE.md) を参照。
