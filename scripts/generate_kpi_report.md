# Pilot KPI Report (Draft)

Audience: Manulife Sustainability & Finance
Scope: One-region pilot

## Executive Summary
- Estimated water savings: **X acre-feet**
- p95 API latency: **< 800ms**, 5XX **< 2%**
- DR validated (RTO 4h / RPO 24h): **Yes**

## Data Coverage
- ET rows: N
- Soil moisture rows: N
- Weather rows: N
- Farms/Blocks: N

## Model Quality
- MAE: <from data/processed/evaluation.json>
- R²: <from data/processed/evaluation.json>
- Top features: see `data/processed/feature_importance.csv`

## Compliance & Ops
- RBAC owner/analyst enforced
- Secrets rotation event recorded
- Alarms in place; last drill date: <date>

## Next
- Add region 2
- OEM controller integrations
- Formalize SLAs & data-sharing
