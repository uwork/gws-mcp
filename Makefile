-include .env
export

# .env の変数を Terraform 変数にマッピング
# SERVICE_HOST にカスタムドメインを設定するだけで Terraform・アプリ双方に反映される
TF_VAR_project_id   := $(PROJECT_ID)
TF_VAR_region       := $(REGION)
TF_VAR_service_name := $(SERVICE)
TF_VAR_service_host := $(SERVICE_HOST)
export TF_VAR_project_id TF_VAR_region TF_VAR_service_name TF_VAR_service_host

TF_DIR := terraform

.PHONY: deploy tf-init tf-plan tf-apply tf-output tf-destroy

deploy:
	# Dockerfile をもとに Cloud Build でビルドし Cloud Run へデプロイ
	gcloud run deploy $(SERVICE) \
		--project=$(PROJECT_ID) \
		--region=$(REGION) \
		--source=.

tf-init:
	cd $(TF_DIR) && terraform init -backend-config="bucket=$(TFSTATE_BUCKET)"

tf-plan:
	cd $(TF_DIR) && terraform plan

tf-apply:
	cd $(TF_DIR) && terraform apply

tf-output:
	cd $(TF_DIR) && terraform output

tf-destroy:
	cd $(TF_DIR) && terraform destroy
