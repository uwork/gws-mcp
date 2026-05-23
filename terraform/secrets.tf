# ─── Secret Manager シークレット ────────────────────────────────────────────
# 各シークレットの初期バージョンは変数経由で .env から投入する。
# ローテーション時は terraform taint または gcloud secrets versions add で行う。

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

  # シークレット値の変更はバージョン追加で管理する（terraform apply での不意な再作成を防ぐ）
  lifecycle {
    ignore_changes = [secret_data]
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
    ignore_changes = [secret_data]
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
    ignore_changes = [secret_data]
  }
}
