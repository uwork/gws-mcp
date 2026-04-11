output "cloud_run_url" {
  description = "Cloud Run サービスの URL"
  value       = google_cloud_run_v2_service.gws_mcp.uri
}

output "image_base" {
  description = "Artifact Registry イメージのベース URL（タグなし）"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}/server"
}

output "service_account_email" {
  description = "Cloud Run サービスアカウントのメールアドレス"
  value       = google_service_account.gws_mcp.email
}
