-include .env

PROJECT_ID ?= your-project-id
REGION     ?= us-central1
SERVICE    ?= gws-mcp

.PHONY: deploy
deploy:
	# Dockerfile をもとに Cloud Build でビルドし Cloud Run へデプロイ
	gcloud run deploy $(SERVICE) \
		--project=$(PROJECT_ID) \
		--region=$(REGION) \
		--source=.
