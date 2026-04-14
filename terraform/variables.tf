variable "project_id" {
  description = "GCP プロジェクト ID"
  type        = string
  default     = "example-project"
}

variable "region" {
  description = "デプロイリージョン"
  type        = string
  default     = "asia-northeast1"
}

variable "service_name" {
  description = "Cloud Run サービス名"
  type        = string
  default     = "gws-mcp"
}

variable "service_host" {
  description = "Cloud Run サービスのホスト名（例: gws-mcp-51272669646.us-central1.run.app）"
  type        = string
}

variable "oauth_redirect_uri" {
  description = "Google OAuth コールバック URI（Cloud Run の /callback エンドポイント）"
  type        = string
}

