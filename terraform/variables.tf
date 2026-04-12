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
