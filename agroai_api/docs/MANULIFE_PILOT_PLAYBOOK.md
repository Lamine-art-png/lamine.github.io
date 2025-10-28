# Manulife Investment Management - AGRO-AI Pilot Playbook

## Executive Summary

This playbook guides the deployment and operation of AGRO-AI for Manulife's 500+ acre irrigation pilot in the Midwest corn belt.

**Pilot Objectives:**
1. Reduce water usage by 15-20% vs. baseline (traditional scheduling)
2. Maintain or improve yield (target: +2-5% vs. baseline)
3. Achieve 99.5% system uptime during growing season
4. Demonstrate SOC 2 compliance for enterprise scale-up
5. Generate actionable ROI data for board presentation

**Timeline:**
- Week 1-2: Infrastructure setup
- Week 3-4: Historical data ingestion + model training
- Week 5-6: Pilot deployment (3-5 fields)
- Week 7-20: Growing season monitoring + optimization
- Week 21-24: Results analysis + expansion planning

## Phase 1: Infrastructure Setup (Weeks 1-2)

### Day 1-3: Azure Environment

**Tasks:**
```bash
# 1. Provision Azure resources (see API_DEPLOYMENT_GUIDE.md)
# 2. Configure networking
# 3. Set up Application Insights
# 4. Deploy AGRO-AI API
# 5. Run database migrations
```

**Acceptance Criteria:**
- [ ] API responds to /v1/health
- [ ] Database migrations complete
- [ ] Application Insights receiving telemetry
- [ ] All secrets in Key Vault (no hardcoded credentials)

### Day 4-7: Tenant Onboarding

**Create Manulife Tenant:**
```bash
# Generate production API key
python scripts/cli.py apikey create \
  --tenant-id manulife-pilot \
  --name "Manulife Production - Growing Season 2025" \
  --role owner \
  --expires-days 365

# Store key in 1Password/LastPass
```

**Register Fields:**
```bash
# For each pilot field
curl -X POST https://app-agroai-pilot.azurewebsites.net/v1/blocks \
  -H "Authorization: Bearer $APIKEY" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "manulife-field-001",
    "name": "North 40 - Corn",
    "area_ha": 16.2,
    "crop_type": "corn",
    "latitude": 41.8781,
    "longitude": -87.6298,
    "water_budget_allocated_m3": 12000
  }'
```

**Acceptance Criteria:**
- [ ] Tenant created with secure API key
- [ ] 3-5 fields registered
- [ ] Water budgets configured per field
- [ ] Field coordinates validated

### Day 8-14: Edge Device Setup

**Deploy Raspberry Pi Collectors (per field):**

1. **Hardware Setup**
   - Raspberry Pi 4 (4GB RAM)
   - 64GB SD card
   - 4G LTE modem (backup connectivity)
   - Weatherproof enclosure
   - Battery backup (8hr capacity)

2. **Software Installation**
   ```bash
   # On each Pi
   sudo apt update && sudo apt install -y python3-pip git
   git clone https://github.com/agroai/edge-collector.git
   cd edge-collector
   pip3 install -r requirements.txt

   # Configure
   cat > .env <<EOF
   AGROAI_API_URL=https://app-agroai-pilot.azurewebsites.net
   AGROAI_API_KEY=$APIKEY
   FIELD_ID=manulife-field-001
   INGESTION_INTERVAL_MINUTES=60
   LOCAL_BUFFER_PATH=/var/agroai/buffer
   EOF

   # Set up systemd service
   sudo cp agroai-collector.service /etc/systemd/system/
   sudo systemctl enable agroai-collector
   sudo systemctl start agroai-collector
   ```

3. **Sensor Integration**
   - Soil moisture sensors: Connect to GPIO, configure depths (6", 12", 18")
   - Weather station: Serial connection for ET₀, rainfall, temp
   - Flow meter: Modbus/RTU connection to irrigation system

**Acceptance Criteria:**
- [ ] Edge devices online and reporting to API
- [ ] Sensor data arriving in hourly batches
- [ ] Local buffering tested (simulate network outage)
- [ ] Battery backup tested

## Phase 2: Historical Data & Model Training (Weeks 3-4)

### Week 3: Data Ingestion

**Ingest Historical Data (3 years):**
```bash
# Weather data from NOAA/Weather Underground
python scripts/ingest_historical_weather.py \
  --tenant-id manulife-pilot \
  --start-date 2022-04-01 \
  --end-date 2024-11-01 \
  --lat 41.8781 \
  --lon -87.6298

# Irrigation records (if available)
python scripts/ingest_historical_irrigation.py \
  --tenant-id manulife-pilot \
  --csv-path data/manulife_irrigation_2022-2024.csv

# Yield data
python scripts/ingest_yield_data.py \
  --csv-path data/manulife_yields_2022-2024.csv
```

**Data Quality Checks:**
```bash
# Verify ingestion
curl -H "Authorization: Bearer $APIKEY" \
  "https://app-agroai-pilot.azurewebsites.net/v1/admin/ingestion-runs?tenant_id=manulife-pilot&status=success&limit=100"

# Check telemetry coverage
python scripts/check_data_quality.py \
  --tenant-id manulife-pilot \
  --report-path artifacts/reports/data_quality_$(date +%Y%m%d).html
```

**Acceptance Criteria:**
- [ ] ≥ 80% data coverage for 3-year period
- [ ] < 5% rejected rows in ingestion
- [ ] No gaps > 7 days in weather data
- [ ] Yield data linked to field IDs

### Week 4: Model Training

**Train Crop-Specific Models:**
```bash
# Train corn model for Midwest
python scripts/train_model.py \
  --model-name irrigation_recommender \
  --crop-type corn \
  --region midwest \
  --train-start 2022-04-01 \
  --train-end 2024-08-31 \
  --test-start 2024-09-01 \
  --test-end 2024-11-01 \
  --algorithm random_forest \
  --output artifacts/models/corn_midwest_v1

# Review metrics
python scripts/evaluate_model.py \
  --model-path artifacts/models/corn_midwest_v1 \
  --generate-report artifacts/reports/model_eval_corn_v1.pdf
```

**Target Metrics:**
| Metric | Target | Achieved |
|--------|--------|----------|
| MAE (irrigation depth) | < 5mm | __ mm |
| R² Score | > 0.75 | __ |
| RMSE | < 8mm | __ mm |
| Feature Importance | Top 5 make sense | ✓/✗ |

**Promote Model:**
```bash
# If metrics acceptable, promote to pilot
python scripts/cli.py model promote \
  --model-id <model-run-id> \
  --status pilot \
  --promoted-by "jane.doe@manulife.com"
```

**Acceptance Criteria:**
- [ ] Model meets target metrics
- [ ] Feature importances validated by agronomist
- [ ] Model promoted to pilot status
- [ ] Evaluation report reviewed by Manulife stakeholders

## Phase 3: Pilot Deployment (Weeks 5-6)

### Week 5: Field Selection & Baselines

**Select 3-5 Pilot Fields:**
- Criteria: Representative soil types, good sensor coverage, separate irrigation zones
- Designate 1-2 control fields (traditional scheduling)

**Establish Baselines:**
```bash
# Calculate historical water use per field
python scripts/calculate_baseline.py \
  --tenant-id manulife-pilot \
  --fields manulife-field-001,manulife-field-002 \
  --years 2022,2023,2024 \
  --output baselines.json
```

**Configure Pilot:**
```bash
# Enable AI recommendations for pilot fields
curl -X PATCH https://app-agroai-pilot.azurewebsites.net/v1/blocks/manulife-field-001 \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"ai_enabled": true, "auto_apply": false}'

# Note: auto_apply=false means recommendations are advisory only (human in loop)
```

**Acceptance Criteria:**
- [ ] Baseline water use calculated for all fields
- [ ] Control vs. treatment fields designated
- [ ] AI recommendations enabled (advisory mode)
- [ ] Stakeholder sign-off on go-live

### Week 6: Go-Live & Monitoring

**Go-Live Checklist:**
- [ ] Sensors calibrated within last 30 days
- [ ] Edge devices reporting normally
- [ ] Model serving production traffic
- [ ] Alerts configured in Application Insights
- [ ] Daily email digest set up for agronomist
- [ ] Emergency contact list shared

**Daily Workflow (Grower):**
1. **Morning (7 AM)**: Check daily email digest
   - Recommended irrigation schedules
   - Weather forecast
   - Soil moisture trends

2. **Review & Approve (8 AM)**:
   ```bash
   # View recommendation
   curl -H "Authorization: Bearer $APIKEY" \
     "https://app-agroai-pilot.azurewebsites.net/v1/blocks/manulife-field-001/recommendations"

   # Apply if acceptable
   curl -X POST "https://app-agroai-pilot.azurewebsites.net/v1/controllers/field-001-controller:apply" \
     -H "Authorization: Bearer $APIKEY" \
     -d '{
       "start_time": "2025-05-10T10:00:00Z",
       "duration_min": 180,
       "zone_ids": ["zone-1", "zone-2"]
     }'
   ```

3. **Evening (6 PM)**: Review execution
   - Verify irrigation completed
   - Check soil moisture response
   - Note any issues in field log

## Phase 4: Growing Season Operations (Weeks 7-20)

### Weekly Operations

**Monday: Performance Review**
```bash
# Generate weekly KPI report
python scripts/generate_kpi_report.py \
  --tenant-id manulife-pilot \
  --week $(date +%Y-W%V) \
  --email stakeholders@manulife.com
```

**KPIs to Track:**
| KPI | Target | Alert If |
|-----|--------|----------|
| Water savings vs. baseline | 15-20% | < 10% or > 25% |
| Soil moisture in target range | > 90% of time | < 85% |
| Recommendation acceptance rate | > 80% | < 70% |
| System uptime | > 99.5% | < 99% |
| Yield on track (mid-season) | +2-5% vs. baseline | < 0% |

**Wednesday: Model Performance**
```bash
# Check for model drift
python scripts/check_model_drift.py \
  --tenant-id manulife-pilot \
  --alert-email ops@agroai.com
```

**Friday: Data Quality**
```bash
# Verify sensor health
python scripts/sensor_health_check.py \
  --tenant-id manulife-pilot \
  --generate-maintenance-tickets
```

### Monthly Operations

**Model Retraining:**
- Retrain with latest data (incremental learning)
- A/B test new vs. current model
- Promote if metrics improve

**Stakeholder Report:**
- Water saved (m³ and %)
- Energy saved (kWh and $)
- Yield forecast update
- System health scorecard

## Phase 5: Results Analysis (Weeks 21-24)

### Post-Season Analysis

**Data Export:**
```bash
# Export full season data
python scripts/export_season_data.py \
  --tenant-id manulife-pilot \
  --season 2025 \
  --output season_2025_complete.csv

# Generate final ROI report
python scripts/generate_roi_report.py \
  --tenant-id manulife-pilot \
  --season 2025 \
  --baseline baselines.json \
  --output artifacts/reports/ROI_Final_2025.pdf
```

**Key Deliverables:**
1. **Executive Summary** (1-2 pages)
   - Water saved: XX,XXX m³ (XX%)
   - Cost saved: $XX,XXX
   - Yield impact: +X.X%
   - ROI: XX% (payback period: X.X years)

2. **Technical Report** (10-15 pages)
   - Methodology
   - Field-by-field results
   - Model performance analysis
   - Recommendations for scale-up

3. **Board Presentation** (PowerPoint)
   - Business case
   - Results visualization
   - Expansion plan
   - Budget request

**Acceptance Criteria:**
- [ ] All pilot objectives met or exceeded
- [ ] ROI > 100% demonstrated
- [ ] No SOC 2 compliance issues
- [ ] Board presentation approved
- [ ] Expansion plan for 50 fields in 2026

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Sensor failure | Medium | High | Daily health checks, spare sensors on-site |
| Network outage | Low | Medium | Edge buffering (8hr), 4G backup |
| Model drift | Medium | Medium | Weekly drift detection, monthly retraining |
| Grower non-compliance | Low | High | Training, daily reminders, agronomist support |
| Extreme weather | Medium | Low | Model handles edge cases, manual override available |

## Success Criteria

**Pilot is successful if:**
- ✅ Water savings: 15-20% (target) or 10-15% (acceptable)
- ✅ Yield: Maintained (minimum) or +2-5% (target)
- ✅ Uptime: > 99.5%
- ✅ ROI: > 100% over 3 years
- ✅ Stakeholder satisfaction: 8/10 or higher

**Pilot leads to expansion if:**
- All success criteria met
- No show-stopper issues (data privacy, system reliability)
- Board approval for $XXX,XXX budget (50 field deployment)

## Contacts & Escalation

| Role | Name | Email | Phone |
|------|------|-------|-------|
| Manulife PM | [Name] | [email] | [phone] |
| AGRO-AI Tech Lead | [Name] | [email] | [phone] |
| Agronomist | [Name] | [email] | [phone] |
| Azure Support | - | azure-support | Premier hotline |
| Escalation | [VP Name] | [email] | [phone] |

**Escalation Triggers:**
- System downtime > 4 hours
- Data breach or security incident
- Grower safety concern
- < 10% water savings at mid-season
