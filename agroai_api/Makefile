.PHONY: help install lint type test coverage run seed docker-up docker-down clean

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies
	pip install -r requirements.txt

lint: ## Run linter (ruff)
	ruff check app/ tests/

format: ## Format code
	black app/ tests/
	ruff check --fix app/ tests/

type: ## Run type checker (mypy)
	mypy app/ --ignore-missing-imports

test: ## Run tests
	pytest tests/ -v

coverage: ## Run tests with coverage
	pytest tests/ --cov=app --cov-report=html --cov-report=term

run: ## Run development server
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

seed: ## Seed database with demo data
	python scripts/seed.py

docker-up: ## Start Docker containers
	docker-compose up --build

docker-down: ## Stop Docker containers
	docker-compose down

docker-logs: ## Show Docker logs
	docker-compose logs -f

clean: ## Clean up generated files
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache
	rm -f agroai.db

quality: lint type test ## Run all quality checks

.DEFAULT_GOAL := help
