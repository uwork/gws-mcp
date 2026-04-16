output "cloud_run_url" {
  description = "Cloud Run サービスの URL"
  value       = google_cloud_run_v2_service.gws_mcp.uri
}

output "service_url" {
  description = "サービスの公開 URL（カスタムドメイン設定時はそちらを優先）"
  value       = var.service_host != "" ? "https://${var.service_host}" : google_cloud_run_v2_service.gws_mcp.uri
}

output "oauth_redirect_uri" {
  description = "Google OAuth に登録すべきリダイレクト URI"
  value       = local.oauth_redirect_uri != "" ? local.oauth_redirect_uri : "${google_cloud_run_v2_service.gws_mcp.uri}/callback"
}

output "service_account_email" {
  description = "Cloud Run サービスアカウントのメールアドレス"
  value       = google_service_account.gws_mcp.email
}
