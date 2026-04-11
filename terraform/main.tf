terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  backend "gcs" {
    # bucket は terraform init 時に -backend-config で渡す
    # 例: terraform init -backend-config="bucket=$(terraform -chdir=. output -raw tfstate_bucket)"
    # または: terraform init -backend-config=backend.conf
    prefix = "gws-mcp"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ─── API 有効化 ───────────────────────────────────────────────────────────────

resource "google_project_service" "run" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam" {
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}
