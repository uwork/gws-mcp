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
  description = "カスタムドメインまたは Cloud Run デフォルトホスト名（例: mcp.example.com）。設定すると OAUTH_REDIRECT_URI を自動導出する。"
  type        = string
  default     = ""
}

variable "google_client_id" {
  description = "Google OAuth クライアント ID（Secret Manager の初期バージョン投入用）"
  type        = string
  sensitive   = true
  default     = ""
}

variable "google_client_secret" {
  description = "Google OAuth クライアントシークレット（Secret Manager の初期バージョン投入用）"
  type        = string
  sensitive   = true
  default     = ""
}

variable "state_secret_key" {
  description = "OAuth state トークン署名キー（Secret Manager の初期バージョン投入用）"
  type        = string
  sensitive   = true
  default     = ""
}

