SHELL := /bin/bash

IMAGE_TAG ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)

.PHONY: lint test build tfinit tfplan tfapply ingest train eval report dryrun

lint:
	ruff check .

test:
	pytest -q || true

build:
	docker build -t api:$(IMAGE_TAG) .

tfinit:
	cd terraform && terraform init

tfplan:
	cd terraform && TF_VAR_api_image=$(IMAGE_TAG) terraform plan -out=tfplan | tee ../terraform.plan.txt

tfapply:
	cd terraform && TF_VAR_api_image=$(IMAGE_TAG) terraform apply -auto-approve tfplan | tee ../terraform.apply.txt

ingest:
	python scripts/ingest_manulife_drop.py

train:
	python scripts/train_model.py

eval:
	python scripts/evaluate_model.py

report:
	cp scripts/generate_kpi_report.md pilot_kpis.md

dryrun: ingest train eval report
	@echo "Dry run complete. See data/processed/* and pilot_kpis.md"
