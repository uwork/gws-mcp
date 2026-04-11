# ─── サービスアカウント ────────────────────────────────────────────────────────

resource "google_service_account" "gws_mcp" {
  account_id   = "${var.service_name}-sa"
  display_name = "gws-mcp Cloud Run サービスアカウント"
}

# ─── Cloud Run サービス ────────────────────────────────────────────────────────

locals {
  image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}/server:${var.image_tag}"
}

resource "google_cloud_run_v2_service" "gws_mcp" {
  name     = var.service_name
  location = var.region

  template {
    service_account = google_service_account.gws_mcp.email

    containers {
      image = local.image

      ports {
        container_port = 8080
      }

      env {
        name  = "PORT"
        value = "8080"
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

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
  }

  depends_on = [
    google_project_service.run,
    google_artifact_registry_repository.gws_mcp,
  ]
}

# ─── 呼び出し権限 ─────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  name     = google_cloud_run_v2_service.gws_mcp.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.gws_mcp.email}"
}

# Claude.ai からの公開アクセスを許可（Phase 1）
# Phase 2 以降で OAuth 保護に切り替える場合はここを削除する
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.cloud_run_invoker == "allUsers" ? 1 : 0
  name     = google_cloud_run_v2_service.gws_mcp.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
