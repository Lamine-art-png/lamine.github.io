# AGRO-AI • Manulife Pilot Kit (One-Region)

This is a drop-in starter to make a **limited pilot** reproducible:
- **Terraform (AWS)**: ECS Fargate API + RDS Postgres + S3 (raw/models) + CloudWatch + Secrets Manager + ECR.
- **CI/CD (GitHub Actions)**: Lint/Test → Docker Build/Push → Terraform Plan/Apply via OIDC.
- **RBAC & Secrets**: Tenant-scoped roles (`owner`, `analyst`) with API keys; per-tenant secrets in Secrets Manager.
- **Runbooks**: Incident & DR with RTO/RPO targets and evidence checklist.
- **SOC 2 Matrix**: Minimal controls mapped to TSC with compensating controls.
- **Data & Model**: Batch ingestion, retraining, evaluation (MAE/R²), feature importance, bias stub, KPI report template.

> Assumptions: AWS account in `us-west-1` (N. California), OIDC to GitHub, Dockerized API (e.g., FastAPI).

## Quickstart
```bash
make tfinit
make tfplan
make tfapply
```

## Evidence Pack
- `terraform.plan.txt`, `terraform.apply.txt` (from CI)
- CloudWatch alarm screenshots, RDS snapshots, Secrets rotation events
- `data/processed/evaluation.json`, `feature_importance.csv`, `bias_report.json`
- `ops/runbooks/*.md` (export PDF)
