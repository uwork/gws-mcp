-include .env
export

# .env の変数を Terraform 変数にマッピング
# SERVICE_HOST にカスタムドメインを設定するだけで Terraform・アプリ双方に反映される
TF_VAR_project_id          := $(PROJECT_ID)
TF_VAR_region              := $(REGION)
TF_VAR_service_name        := $(SERVICE)
TF_VAR_service_host        := $(SERVICE_HOST)
TF_VAR_google_client_id     := $(GOOGLE_CLIENT_ID)
TF_VAR_google_client_secret := $(GOOGLE_CLIENT_SECRET)
TF_VAR_state_secret_key     := $(STATE_SECRET_KEY)
export TF_VAR_project_id TF_VAR_region TF_VAR_service_name TF_VAR_service_host
export TF_VAR_google_client_id TF_VAR_google_client_secret TF_VAR_state_secret_key

TF_DIR := terraform

.PHONY: deploy tf-init tf-plan tf-apply tf-output tf-destroy

deploy:
	# Dockerfile をもとに Cloud Build でビルドし Cloud Run へデプロイ
	gcloud run deploy $(SERVICE) \
		--project=$(PROJECT_ID) \
		--region=$(REGION) \
		--source=.

tf-init:
	@test -n "$(TFSTATE_BUCKET)" || (echo "ERROR: TFSTATE_BUCKET is not set in .env"; exit 1)
	cd $(TF_DIR) && terraform init -backend-config="bucket=$(TFSTATE_BUCKET)"

tf-plan:
	cd $(TF_DIR) && terraform plan

tf-apply:
	cd $(TF_DIR) && terraform apply

tf-output:
	cd $(TF_DIR) && terraform output

tf-destroy:
	cd $(TF_DIR) && terraform destroy
