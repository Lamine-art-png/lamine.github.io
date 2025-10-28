# AGRO-AI API Deployment Guide

## Overview

This guide covers deploying the AGRO-AI API for enterprise pilots (500+ acres) with Manulife Investment Management.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Edge (Farm)                                             │
│  ┌────────────────┐                                     │
│  │ Raspberry Pi   │ → Local file-drop watcher           │
│  │ + Sensors      │   Collects data hourly              │
│  └────────────────┘                                     │
└──────────────┬──────────────────────────────────────────┘
               │ HTTPS
┌──────────────▼──────────────────────────────────────────┐
│  Azure Cloud                                             │
│  ┌────────────────┐    ┌──────────────┐                │
│  │ App Service    │───▶│ Azure SQL    │                │
│  │ (API + Worker) │    │ Database     │                │
│  └────────────────┘    └──────────────┘                │
│         │                                                │
│         ▼                                                │
│  ┌────────────────┐    ┌──────────────┐                │
│  │ Azure Blob     │    │ Application  │                │
│  │ (Model Store)  │    │ Insights     │                │
│  └────────────────┘    └──────────────┘                │
└─────────────────────────────────────────────────────────┘
```

## Prerequisites

### Azure Resources

1. **App Service**
   - Plan: B2 or higher (2 cores, 3.5 GB RAM minimum)
   - Python 3.11 runtime
   - Always On: Enabled

2. **Azure SQL Database**
   - DTU: S3 or higher (100 DTUs)
   - Storage: 250 GB minimum
   - Geo-replication: Recommended for production

3. **Azure Blob Storage**
   - Account type: StorageV2
   - Performance: Standard
   - Redundancy: ZRS (Zone-redundant storage)
   - Containers:
     - `agroai-ingestion` - Raw sensor data
     - `agroai-models` - ML model artifacts
     - `agroai-reports` - Generated reports

4. **Application Insights**
   - For monitoring and alerting

### Environment Variables

```bash
# Database
DATABASE_URL=mssql+pyodbc://username:password@server.database.windows.net:1433/agroai?driver=ODBC+Driver+18+for+SQL+Server

# Security
API_KEY_SALT=<32-char-random-string>
SECRET_KEY=<32-char-random-string>
WEBHOOK_SECRET=<32-char-random-string>

# Azure Storage
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_STORAGE_CONTAINER_INGESTION=agroai-ingestion
AZURE_STORAGE_CONTAINER_MODELS=agroai-models

# Model Registry
MODEL_REGISTRY_BACKEND=azure
MODEL_REGISTRY_PATH=models/

# Observability
LOG_LEVEL=INFO
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...

# Rate Limiting
RATE_LIMIT_PER_MINUTE=100
```

## Deployment Steps

### 1. Prepare Azure Resources

```bash
# Login to Azure
az login

# Create resource group
az group create --name rg-agroai-pilot --location eastus2

# Create App Service plan
az appservice plan create \
  --name asp-agroai-pilot \
  --resource-group rg-agroai-pilot \
  --sku B2 \
  --is-linux

# Create web app
az webapp create \
  --name app-agroai-pilot \
  --resource-group rg-agroai-pilot \
  --plan asp-agroai-pilot \
  --runtime "PYTHON|3.11"

# Create Azure SQL Database
az sql server create \
  --name sql-agroai-pilot \
  --resource-group rg-agroai-pilot \
  --location eastus2 \
  --admin-user agroai_admin \
  --admin-password <strong-password>

az sql db create \
  --server sql-agroai-pilot \
  --resource-group rg-agroai-pilot \
  --name agroai_prod \
  --service-objective S3

# Create Storage Account
az storage account create \
  --name stagroaipilot \
  --resource-group rg-agroai-pilot \
  --location eastus2 \
  --sku Standard_ZRS

# Create containers
az storage container create --name agroai-ingestion --account-name stagroaipilot
az storage container create --name agroai-models --account-name stagroaipilot
az storage container create --name agroai-reports --account-name stagroaipilot
```

### 2. Configure App Service

```bash
# Set environment variables
az webapp config appsettings set \
  --name app-agroai-pilot \
  --resource-group rg-agroai-pilot \
  --settings \
    DATABASE_URL="..." \
    API_KEY_SALT="..." \
    SECRET_KEY="..." \
    AZURE_STORAGE_CONNECTION_STRING="..."

# Configure startup command
az webapp config set \
  --name app-agroai-pilot \
  --resource-group rg-agroai-pilot \
  --startup-file "scripts/startup.sh"
```

### 3. Deploy Code

```bash
# From local repository
cd agroai_api

# Build deployment package
zip -r deploy.zip . -x "*.git*" -x "*venv*" -x "*__pycache__*"

# Deploy
az webapp deployment source config-zip \
  --name app-agroai-pilot \
  --resource-group rg-agroai-pilot \
  --src deploy.zip
```

### 4. Run Migrations

```bash
# SSH into app service
az webapp ssh --name app-agroai-pilot --resource-group rg-agroai-pilot

# Run migrations
cd /home/site/wwwroot
python3 -m alembic upgrade head

# Seed initial data
python3 scripts/seed.py
```

### 5. Create Tenant & API Keys

```bash
# Create Manulife tenant
python3 scripts/cli.py apikey create \
  --tenant-id manulife-pilot \
  --name "Manulife Production Key" \
  --role owner \
  --expires-days 365

# Save the API key securely
```

## Operational Runbooks

### Daily Operations

**Morning Checks (9 AM)**
```bash
# Check ingestion runs from last 24h
curl -H "Authorization: Bearer $API_KEY" \
  https://app-agroai-pilot.azurewebsites.net/v1/admin/ingestion-runs?hours=24

# Check model performance
curl -H "Authorization: Bearer $API_KEY" \
  https://app-agroai-pilot.azurewebsites.net/v1/admin/models/production/metrics
```

**Evening Sync (6 PM)**
```bash
# Trigger batch ingestion for all fields
python3 scripts/trigger_ingestion.py --all-fields
```

### Weekly Operations

**Model Retraining (Sundays, 2 AM)**
```bash
# Automated via Azure Functions cron
# Or manually:
python3 scripts/train_model.py \
  --crop-type corn \
  --region midwest \
  --start-date 2024-01-01 \
  --end-date 2024-12-31
```

**Performance Review (Fridays)**
```bash
# Generate weekly report
python3 scripts/generate_report.py \
  --tenant-id manulife-pilot \
  --period week \
  --output artifacts/reports/weekly_$(date +%Y%m%d).pdf
```

### Incident Response

**High Error Rate on Ingestion**
```bash
# 1. Check recent failures
curl -H "Authorization: Bearer $API_KEY" \
  https://app-agroai-pilot.azurewebsites.net/v1/admin/ingestion-runs?status=failed&limit=10

# 2. Review logs in Application Insights
az monitor app-insights query \
  --app agroai-pilot-insights \
  --analytics-query "traces | where severityLevel >= 3 | top 20 by timestamp desc"

# 3. Re-run failed ingestions
python3 scripts/retry_ingestion.py --batch-id <batch-id>
```

**Model Drift Detected**
```bash
# 1. Check recent prediction accuracy
# 2. Trigger emergency retraining
python3 scripts/train_model.py --emergency --use-recent-data-only

# 3. Promote to pilot, test, then production
python3 scripts/cli.py model promote --model-id <id> --status pilot
# ... test ...
python3 scripts/cli.py model promote --model-id <id> --status production
```

## Monitoring & Alerts

### Key Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| API Response Time (p95) | < 500ms | > 1000ms |
| Ingestion Success Rate | > 99% | < 95% |
| Model Accuracy (MAE) | < 5mm | > 8mm |
| Database CPU | < 70% | > 85% |
| Storage Used | < 80% | > 90% |

### Application Insights Queries

**Failed Requests**
```kusto
requests
| where success == false
| where timestamp > ago(1h)
| summarize count() by resultCode, name
| order by count_ desc
```

**Slow Queries**
```kusto
dependencies
| where type == "SQL"
| where duration > 1000
| project timestamp, name, duration, data
| order by timestamp desc
```

## Security Checklist

- [ ] All API keys use strong random generation
- [ ] Database firewall configured (Azure services only)
- [ ] HTTPS enforced (no HTTP allowed)
- [ ] CORS configured for specific origins only
- [ ] Rate limiting enabled on all endpoints
- [ ] Secrets stored in Azure Key Vault (not App Settings)
- [ ] Application Insights configured for PII redaction
- [ ] Backup retention policy: 30 days
- [ ] DR plan documented and tested

## Scaling Guidelines

### When to Scale Up

**App Service**
- CPU consistently > 70%: Move to P1V2 (2 cores → 4 cores)
- Memory > 80%: Move to P2V2 (3.5 GB → 7 GB)

**Database**
- DTU usage > 80%: Move S3 → S4 or S6
- Storage > 80%: Increase max size

**Horizontal Scaling**
- \> 1000 req/min sustained: Add second instance
- \> 5000 req/min: Move to Premium tier + auto-scaling

## Backup & Recovery

**Database Backups**
- Automated daily backups (Azure SQL built-in)
- Point-in-time restore available for 35 days
- Test restore quarterly

**Blob Storage**
- Soft delete enabled (30 days retention)
- Versioning enabled for model artifacts
- Monthly backup to separate storage account

**Disaster Recovery**
- RTO: 4 hours
- RPO: 1 hour
- Geo-replicated database to West US 2

## Support Contacts

- **Technical Lead**: [email]
- **Azure Support**: Portal + phone support (Premium tier)
- **Manulife Stakeholders**: [email list]
- **On-Call Schedule**: PagerDuty rotation
