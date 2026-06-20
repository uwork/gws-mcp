# ─── ローカル変数 ─────────────────────────────────────────────────────────────

locals {
  # SERVICE_HOST が設定されていれば https://<host>/callback を自動導出する
  oauth_redirect_uri = var.service_host != "" ? "https://${var.service_host}/callback" : ""
}

# ─── サービスアカウント ────────────────────────────────────────────────────────

resource "google_service_account" "gws_mcp" {
  account_id   = "${var.service_name}-sa"
  display_name = "gws-mcp Cloud Run サービスアカウント"
}

# Secret Manager のシークレット読み取り権限（gws-mcp-* シークレットのみに限定）
resource "google_project_iam_member" "gws_mcp_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.gws_mcp.email}"

  condition {
    title       = "gws-mcp secrets only"
    description = "gws-mcp-* プレフィックスのシークレットのみ読み取り可能"
    expression  = "resource.name.startsWith(\"projects/${var.project_id}/secrets/gws-mcp-\")"
  }
}

# Firestore の読み書き権限
resource "google_project_iam_member" "gws_mcp_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.gws_mcp.email}"
}

# ─── Firestore ────────────────────────────────────────────────────────────────
# 注意: すでに存在する場合は terraform import が必要
#   terraform import google_firestore_database.default projects/<PROJECT_ID>/databases/(default)

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.firestore]
}

# ─── Cloud Run サービス ────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "gws_mcp" {
  name     = var.service_name
  location = var.region
  # Phase 1: IAM チェックを無効化して全公開（Claude.ai カスタムコネクタからの接続用）
  # Phase 2 以降で OAuth 保護に切り替える際はここを削除する
  invoker_iam_disabled = true

  template {
    service_account = google_service_account.gws_mcp.email

    containers {
      # image は gcloud deploy で管理するため Terraform 管理外
      image = "gcr.io/cloudrun/placeholder"

      ports {
        container_port = 8080
      }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
      env {
        name  = "SERVICE"
        value = var.service_name
      }
      env {
        name = "STATE_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.state_secret_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "SERVICE_HOST"
        value = var.service_host
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        # リクエストがない間は 0 インスタンスにスケールダウン
        cpu_idle = true
      }
    }
  }

  scaling {
    min_instance_count = 0
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  depends_on = [google_project_service.run]
}
