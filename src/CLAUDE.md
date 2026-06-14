# src — 実装ガイド

> **メンテナンスルール**: `src/` 以下のファイルを変更したとき、このファイルの記述と食い違いが生じる場合は必ずここを更新すること。対象はディレクトリ構造・エンドポイント・ツール一覧・環境変数・依存ライブラリ・認証フロー。

## ディレクトリ構造

```
src/
├── main.py                    # エントリポイント（uvicorn 起動）
├── app.py                     # Starlette アプリ組み立て・ルーティング
├── config.py                  # 環境変数・定数
├── features/
│   ├── mcp/
│   │   ├── instance.py        # FastMCP インスタンス（単一 mcp オブジェクト）
│   │   ├── server.py          # ping ツール定義・sheets / slides / docs モジュール登録
│   │   ├── auth.py            # ContextVar による user_id 管理
│   │   ├── sheets.py          # Google Sheets MCP ツール定義
│   │   ├── slides.py          # Google Slides MCP ツール定義
│   │   └── docs.py            # Google Docs MCP ツール定義
│   └── oauth/
│       ├── routes.py          # OAuth HTTP エンドポイント
│       ├── google.py          # Google OAuth ヘルパー
│       ├── state.py           # itsdangerous による state トークン生成・検証
│       ├── storage.py         # Firestore トークン永続化
│       └── secret.py          # Secret Manager アクセス（メモリキャッシュ付き）
└── static/
    └── favicon.ico
```

## 認証の 2 レイヤー構造

```
Claude.ai ──[MCP OAuth 2.1]──► /authorize ──► Google OAuth ──► /callback
                                                                     │
                              ◄──[MCP Bearer Token]───────────────────┘
```

**Layer 1: MCP 認証**（`features/oauth/routes.py`）
- `/.well-known/oauth-protected-resource` — RFC 9728 resource metadata（claude.ai が最初に参照）
- `/.well-known/oauth-authorization-server` — RFC 8414 AS metadata
- `/register` — RFC 7591 動的クライアント登録（client_secret 不要）
- `/authorize` — PKCE (S256) 付き認可リクエスト受付 → Google 認可画面にリダイレクト
- `/token` — 認可コード → MCP Bearer トークン交換（PKCE 検証）、リフレッシュトークンによる再発行にも対応
- MCP Bearer トークンは `itsdangerous.URLSafeTimedSerializer` で生成・検証（有効期限 1 時間）
- トークンペイロードには `type` フィールドを含む（`"access"` / `"refresh"`）。`BearerAuthMiddleware` は `type == "access"` のみ受け付け、`/token` の `refresh_token` グラントは `type == "refresh"` のみ受け付ける（用途混用を防ぐ）
- リフレッシュトークンは有効期限 30 日。使用のたびに新しいトークンを発行するローテーション方式
- 現在有効なリフレッシュトークンの SHA-256 フィンガープリント（`mcp_refresh_fingerprint`）を Firestore の `mcp_tokens/{user_id}` ドキュメントに保存。リフレッシュ時に照合し、不一致は `invalid_grant`。`delete_tokens(user_id)` を呼ぶと Google + MCP 両方のアクセスが即座に無効化される

**Layer 2: Google 認証**（`features/oauth/google.py`）
- Google OAuth 認可コードをアクセストークン・リフレッシュトークンと交換
- `access_token / refresh_token / expiry / user_id` を Firestore に保存
- アクセストークンの有効期限 60 秒前にリフレッシュトークンで自動更新
- 要求スコープ: `openid email spreadsheets presentations documents drive`
  - `spreadsheets` — Google Sheets 読み書き
  - `presentations` — Google Slides 読み書き
  - `documents` — Google Docs 読み書き
  - `drive` — エクスポート・コメント読み書き（Drive API）

## リクエストフロー（MCP ツール呼び出し時）

1. `BearerAuthMiddleware`（`app.py`）が `Authorization: Bearer <mcp_token>` を検証
2. トークン内の `user_id` を ContextVar にセット（`features/mcp/auth.py:set_user_id`）
3. MCP ツール（`sheets.py` など）が `get_current_user_id()` で user_id を取得
4. `get_valid_access_token(user_id)` で Firestore から Google アクセストークンを取得
5. Google Sheets API を呼び出して結果を返す

## BearerAuthMiddleware の認証失敗時の挙動

- Bearer トークンなし → `401` + `WWW-Authenticate: Bearer realm=..., resource_metadata=...`（error 属性なし）
- Bearer トークンあり・無効 → `401` + 同上（`error="invalid_token"` 付き）
- RFC 6750 §3.1 に準拠（error 属性はトークンが存在した場合のみ付与）

## user_id の生成ルール

`callback` エンドポイントで `code_challenge` の SHA-256 ハッシュ先頭 32 文字を user_id とする。  
同じ PKCE フローなら常に同じ user_id になる（Firestore ドキュメントキー）。

## MCP ツール一覧（`features/mcp/`）

| ツール名 | 定義ファイル | 概要 |
|---|---|---|
| `ping` | `server.py` | 疎通確認 |
| `sheets_get_values` | `sheets.py` | 単一範囲の値取得 |
| `sheets_batch_get_values` | `sheets.py` | 複数範囲を一括取得 |
| `sheets_get_spreadsheet` | `sheets.py` | スプレッドシートのメタデータ取得 |
| `sheets_create_spreadsheet` | `sheets.py` | 新規スプレッドシート作成 |
| `sheets_update_values` | `sheets.py` | 範囲への値書き込み（上書き） |
| `sheets_append_values` | `sheets.py` | テーブル末尾への追記 |
| `sheets_clear_values` | `sheets.py` | 範囲のセル値クリア |
| `sheets_batch_update` | `sheets.py` | 構造・書式の一括更新（spreadsheets.batchUpdate） |
| `sheets_batch_update_help` | `sheets.py` | `sheets_batch_update` の request 種別リファレンス |
| `slides_create_presentation` | `slides.py` | 新規プレゼンテーション作成 |
| `slides_get_presentation` | `slides.py` | プレゼンテーション概要・スライド一覧取得 |
| `slides_get_page` | `slides.py` | 特定スライドの全要素詳細取得 |
| `slides_batch_update` | `slides.py` | スライドの一括更新（presentations.batchUpdate） |
| `slides_batch_update_help` | `slides.py` | `slides_batch_update` の request 種別リファレンス |
| `slides_export` | `slides.py` | PDF / PPTX / テキスト形式でエクスポート（Drive API） |
| `slides_get_thumbnail` | `slides.py` | スライドのサムネイル URL 取得 |
| `slides_list_comments` | `slides.py` | コメント一覧取得（Drive API） |
| `slides_add_comment` | `slides.py` | コメント追加（Drive API） |
| `docs_get_document` | `docs.py` | ドキュメントのコンテンツとメタデータ取得（タブ対応） |
| `docs_create_document` | `docs.py` | 新規ドキュメント作成 |
| `docs_batch_update` | `docs.py` | ドキュメントの一括更新（documents.batchUpdate） |
| `docs_batch_update_help` | `docs.py` | `docs_batch_update` の request 種別リファレンス |
| `docs_export` | `docs.py` | PDF / DOCX / テキスト / HTML 形式でエクスポート（Drive API） |
| `docs_list_comments` | `docs.py` | コメント一覧取得（Drive API） |
| `docs_add_comment` | `docs.py` | コメント追加（Drive API） |

ツールのレスポンスは Google API の camelCase / ネスト構造を整形した snake_case のフラット dict。  
2D 配列に 2 行以上あれば `headers` / `records` キーも追加する（AI が扱いやすい形式）。

## 設定（環境変数）

| 変数 | 必須 | 説明 |
|---|---|---|
| `STATE_SECRET_KEY` | ✅ | state / MCP トークン署名鍵（32 バイト hex 推奨） |
| `PROJECT_ID` | ✅ | GCP プロジェクト ID |
| `SERVICE_HOST` | | 公開ホスト名（例: `myservice-abc123.a.run.app`）。HTTPS URL 生成に使用。未設定時は `X-Forwarded-Proto` ヘッダーで補完（ローカル開発では省略可） |
| `REGION` | | Cloud Run リージョン（デフォルト: `asia-northeast1`） |
| `FIRESTORE_COLLECTION` | | Firestore コレクション名（デフォルト: `mcp_tokens`） |
| `OAUTH_REDIRECT_URI` | | Google OAuth コールバック URI（SERVICE_HOST から自動導出） |
| `ALLOWED_REDIRECT_URIS` | | 許可する MCP リダイレクト URI（改行区切り） |
| `ALLOWED_GOOGLE_DOMAINS` | | ログイン許可ドメイン（カンマまたは改行区切り、未設定=制限なし） |

Secret Manager に格納するシークレット名は `config.py` の定数に固定:
- `gws-mcp-google-client-id`
- `gws-mcp-google-client-secret`

## 新しいツールを追加する手順

1. `features/mcp/sheets.py`（または新規モジュール）に `@mcp.tool()` デコレータで関数を定義
2. 新規モジュールの場合は `features/mcp/server.py` の末尾に `import features.mcp.<module>` を追加
3. `mcp` インスタンスは必ず `features/mcp/instance.py` から import する

## 依存ライブラリ

- `starlette` + `uvicorn` — ASGI フレームワーク
- `mcp[streamable-http]` — FastMCP サーバー（Streamable HTTP トランスポート）
- `httpx` — 非同期 HTTP クライアント（Google API 呼び出し）
- `itsdangerous` — state / Bearer トークン署名
- `google-cloud-firestore` — トークン永続化
- `google-cloud-secret-manager` — クライアントシークレット管理
