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

