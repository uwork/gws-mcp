# ─── Secret Manager シークレット ────────────────────────────────────────────
# 各シークレットの初期バージョンは変数経由で .env から投入する。
# ローテーション時は以下のいずれかで行う:
#   terraform apply -replace="google_secret_manager_secret_version.<name>[0]"
#   gcloud secrets versions add <secret-id> --data-file=-
#
# 注意: secret_data は Terraform state に平文で記録される。
# GCS バックエンドの state バケットへの IAM アクセス権は最小権限で管理すること。
#
# 既存シークレットを Terraform 管理下に移行する場合:
#   terraform import google_secret_manager_secret.google_client_id \
#     projects/<PROJECT_ID>/secrets/gws-mcp-google-client-id
#   terraform import google_secret_manager_secret.state_secret_key \
#     projects/<PROJECT_ID>/secrets/gws-mcp-state-secret-key
#   （旧名 mcp-state-secret-key から gws-mcp-state-secret-key にリネームした場合は
#     gcloud secrets versions add gws-mcp-state-secret-key で値を再投入する）

resource "google_secret_manager_secret" "google_client_id" {
  secret_id = "gws-mcp-google-client-id"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_version" "google_client_id" {
  count       = var.google_client_id != "" ? 1 : 0
  secret      = google_secret_manager_secret.google_client_id.id
  secret_data = var.google_client_id

  # ignore_changes: 値の変更はバージョン追加で管理する
  # prevent_destroy: 変数が未設定になっても既存バージョンを誤削除しない
  lifecycle {
    ignore_changes  = [secret_data]
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret" "google_client_secret" {
  secret_id = "gws-mcp-google-client-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_version" "google_client_secret" {
  count       = var.google_client_secret != "" ? 1 : 0
  secret      = google_secret_manager_secret.google_client_secret.id
  secret_data = var.google_client_secret

  lifecycle {
    ignore_changes  = [secret_data]
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret" "state_secret_key" {
  secret_id = "gws-mcp-state-secret-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_version" "state_secret_key" {
  count       = var.state_secret_key != "" ? 1 : 0
  secret      = google_secret_manager_secret.state_secret_key.id
  secret_data = var.state_secret_key

  lifecycle {
    ignore_changes  = [secret_data]
    prevent_destroy = true
  }
}
