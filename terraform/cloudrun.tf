# ─── サービスアカウント ────────────────────────────────────────────────────────

resource "google_service_account" "gws_mcp" {
  account_id   = "${var.service_name}-sa"
  display_name = "gws-mcp Cloud Run サービスアカウント"
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
