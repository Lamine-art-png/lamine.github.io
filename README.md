# AGRO-AI • Manulife Pilot Kit (One-Region)

This is a drop-in starter to make a **limited pilot** reproducible:
- **Terraform (AWS)**: ECS Fargate API + RDS Postgres + S3 (raw/models) + CloudWatch + Secrets Manager + ECR.
- **CI/CD (GitHub Actions)**: Lint/Test → Docker Build/Push → Terraform Plan/Apply via OIDC.
- **RBAC & Secrets**: Tenant-scoped roles (`owner`, `analyst`) with API keys; per-tenant secrets in Secrets Manager.
- **Runbooks**: Incident & DR with RTO/RPO targets and evidence checklist.
- **SOC 2 Matrix**: Minimal controls mapped to TSC with compensating controls.
- **Data & Model**: Batch ingestion, retraining, evaluation (MAE/R²), feature importance, bias stub, KPI report template.

> Assumptions: AWS account in `us-west-1` (N. California), OIDC to GitHub, Dockerized API (e.g., FastAPI).


## AGRO-AI Water Command Center

- **AGRO-AI Portal:** https://app.agroai-pilot.com
- **AGRO-AI API:** https://api.agroai-pilot.com
- **Water Command Center:** Enterprise customer portal for connected controller environments, live context assembly, irrigation recommendations, execution tracking, verification, integrations, reports, audit log, and administration placeholders.

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
<!-- trigger deploy -->


## Velia AI backend + mobile wiring

- Backend app: `apps/velia-ai-api` (Express).
- Mobile app: `apps/velia-mobile` now calls backend-first APIs with local fallback for weather, assistant responses, and voice interpretation.

### Backend quick run

```bash
cd apps/velia-ai-api
npm install
npm run dev
```

### Backend tests

```bash
cd apps/velia-ai-api
npm test
```
