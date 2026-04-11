# ─── Artifact Registry ────────────────────────────────────────────────────────

resource "google_artifact_registry_repository" "gws_mcp" {
  repository_id = var.service_name
  location      = var.region
  format        = "DOCKER"
  description   = "gws-mcp コンテナイメージ"

  depends_on = [google_project_service.artifact_registry]
}
