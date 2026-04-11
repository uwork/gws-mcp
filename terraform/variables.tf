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

variable "image_tag" {
  description = "デプロイするコンテナイメージのタグ"
  type        = string
  default     = "latest"
}

variable "cloud_run_invoker" {
  description = "Cloud Run を呼び出せる IAM メンバー。公開する場合は allUsers"
  type        = string
  default     = "allUsers"
}
