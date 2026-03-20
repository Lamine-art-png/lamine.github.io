"""Model information and methodology endpoints.

Public-facing endpoints that describe AGRO-AI's recommendation engine,
data requirements, ML pipeline, and scientific methodology.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/model", tags=["model-info"])

MODEL_VERSION = "rf-ens-1.0.0"


@router.get("/info")
def model_info():
    """
    Public model card: algorithm, data requirements, evaluation metrics,
    and pipeline overview. No authentication required.
    """
    return {
        "model": {
            "name": "AGRO-AI Irrigation Recommender",
            "version": MODEL_VERSION,
            "type": "Hybrid — physics-based water balance + Random Forest ensemble",
            "description": (
                "Combines a FAO-56 Penman-Monteith water balance model with "
                "a Random Forest ensemble trained on historical field data to "
                "produce per-block irrigation recommendations."
            ),
        },
        "algorithm": {
            "stage_1_water_balance": {
                "method": "ET0 − effective rainfall + soil VWC deficit → irrigation need",
                "weighting": "60% soil moisture deficit, 40% ET-based deficit",
                "reference": "FAO Irrigation and Drainage Paper 56",
            },
            "stage_2_ml_ensemble": {
                "algorithm": "Random Forest (scikit-learn)",
                "estimators": 200,
                "target_variable": "ET0 (reference evapotranspiration, mm/day)",
                "training_data": "Historical field telemetry (soil, weather, flow)",
                "evaluation_metrics": {
                    "MAE": "Mean Absolute Error (target: < 5mm)",
                    "RMSE": "Root Mean Squared Error",
                    "R2": "Coefficient of determination (target: > 0.75)",
                },
            },
        },
        "data_requirements": {
            "description": (
                "Every data source that is relevant to irrigation scheduling. "
                "The system ingests, validates, and fuses all available signals."
            ),
            "telemetry_types": [
                {
                    "type": "soil_vwc",
                    "description": "Volumetric Water Content (m³/m³)",
                    "range": "0.0 – 1.0",
                    "recommended_interval": "15 minutes",
                    "sensor_depths": "6\", 12\", 18\" (multi-depth preferred)",
                },
                {
                    "type": "et0",
                    "description": "Reference Evapotranspiration (mm/day)",
                    "source": "On-site weather station or NOAA/Weather Underground",
                    "recommended_interval": "Hourly or daily",
                },
                {
                    "type": "weather",
                    "description": "Rainfall, temperature, humidity, wind, solar radiation",
                    "source": "On-site station, NOAA, or third-party API",
                    "recommended_interval": "Hourly",
                },
                {
                    "type": "flow",
                    "description": "Irrigation flow rate (m³/hour)",
                    "source": "Flow meter per irrigation zone",
                    "recommended_interval": "Hourly totals",
                },
                {
                    "type": "valve_state",
                    "description": "Valve open/close status",
                    "source": "Irrigation controller (e.g., Talgil, Galcon)",
                    "recommended_interval": "Event-driven",
                },
            ],
            "supplementary_data": [
                "Crop type and growth stage",
                "Soil classification and field capacity",
                "Block area (hectares) and GPS coordinates",
                "Historical yield records",
                "Water allocation / budget constraints",
            ],
        },
        "crop_support": {
            "calibrated_crops": {
                "corn": {"root_zone_depth_mm": 800},
                "wheat": {"root_zone_depth_mm": 600},
                "vegetables": {"root_zone_depth_mm": 400},
                "trees": {"root_zone_depth_mm": 1000},
                "vineyard": {"root_zone_depth_mm": 600},
                "almonds": {"root_zone_depth_mm": 1000},
            },
            "note": "Any crop can be onboarded — root zone depth and Kc curve are configurable.",
        },
        "ml_pipeline": {
            "lifecycle": ["training", "pilot", "production", "archived"],
            "registry_backends": ["filesystem", "AWS S3", "Azure Blob Storage"],
            "versioning": "Semantic versioning with SHA-256 artifact checksums",
            "promotion": "Manual promotion with metric gate (MAE < 5mm, R² > 0.75)",
            "retraining": "Monthly (pilot), automated pipeline planned (Phase 2)",
        },
        "output": {
            "recommendation": {
                "when": "Optimal irrigation start time (UTC)",
                "duration_min": "Irrigation duration in minutes",
                "volume_m3": "Total water volume in cubic meters",
                "confidence": "Model confidence score (0–1)",
                "explanations": "Human-readable reasoning (deficit, ET0, VWC, efficiency)",
                "version": "Model version used for traceability",
            },
            "caching": {
                "idempotency": "24-hour TTL on Idempotency-Key header",
                "feature_cache": "6-hour TTL based on input feature hash",
            },
        },
        "integrations": {
            "controller_support": ["Talgil", "Galcon (planned)"],
            "data_ingestion": ["REST API (batch)", "File drop", "AWS S3", "Azure Blob"],
            "deployment": ["Azure App Service (cloud)", "Raspberry Pi (edge)"],
        },
        "links": {
            "methodology": "/v1/model/methodology",
            "api_docs": "/docs",
            "health": "/v1/health",
        },
    }


@router.get("/methodology", response_class=HTMLResponse)
def model_methodology():
    """
    Public methodology page — a detailed, readable explanation of how
    AGRO-AI calculates irrigation recommendations. Designed to be shared
    with partners, investors, and conference audiences.
    """
    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AGRO-AI — Methodology</title>
  <style>
    :root {{ --brand: #1a7a3a; --bg: #f8faf9; --card: #fff; --text: #222; --muted: #666; }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
           background: var(--bg); color: var(--text); line-height: 1.7; }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 48px 24px; }}
    h1 {{ color: var(--brand); font-size: 2rem; margin-bottom: 8px; }}
    .subtitle {{ color: var(--muted); font-size: 1.1rem; margin-bottom: 40px; }}
    h2 {{ color: var(--brand); font-size: 1.35rem; margin-top: 40px; margin-bottom: 16px;
          border-bottom: 2px solid var(--brand); padding-bottom: 6px; }}
    h3 {{ font-size: 1.1rem; margin-top: 24px; margin-bottom: 8px; }}
    p, li {{ margin-bottom: 10px; }}
    ul {{ padding-left: 24px; }}
    .card {{ background: var(--card); border-radius: 10px; padding: 24px;
             margin: 16px 0; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    .formula {{ background: #f0f4f1; border-left: 4px solid var(--brand);
                padding: 16px 20px; margin: 16px 0; font-family: 'Courier New', monospace;
                font-size: 0.95rem; border-radius: 0 6px 6px 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
    th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #e0e0e0; }}
    th {{ background: var(--brand); color: #fff; font-weight: 600; }}
    tr:nth-child(even) {{ background: #f4f7f5; }}
    .badge {{ display: inline-block; background: var(--brand); color: #fff;
              padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; margin-right: 6px; }}
    .version {{ color: var(--muted); font-size: 0.85rem; margin-top: 48px;
                padding-top: 16px; border-top: 1px solid #ddd; }}
  </style>
</head>
<body>
<div class="container">

  <h1>AGRO-AI Methodology</h1>
  <p class="subtitle">How we turn field data into precision irrigation recommendations</p>

  <!-- ─── OVERVIEW ─── -->
  <h2>1. Overview</h2>
  <p>AGRO-AI uses a <strong>hybrid approach</strong> that combines a physics-based water balance model
     with a machine learning ensemble. The water balance provides a scientifically grounded baseline,
     while the ML layer learns site-specific patterns from historical data to refine predictions over time.</p>

  <!-- ─── DATA ─── -->
  <h2>2. Data Requirements</h2>
  <p>We ingest <strong>every data source that is relevant</strong> to irrigation scheduling:</p>

  <table>
    <tr><th>Data Type</th><th>What We Measure</th><th>Typical Source</th></tr>
    <tr><td><span class="badge">soil_vwc</span></td>
        <td>Volumetric Water Content at multiple depths (6", 12", 18")</td>
        <td>In-ground soil sensors (15-min intervals)</td></tr>
    <tr><td><span class="badge">et0</span></td>
        <td>Reference Evapotranspiration (mm/day)</td>
        <td>On-site weather station, NOAA</td></tr>
    <tr><td><span class="badge">weather</span></td>
        <td>Rainfall, temperature, humidity, wind, solar radiation</td>
        <td>Weather station or API</td></tr>
    <tr><td><span class="badge">flow</span></td>
        <td>Irrigation flow rate (m&sup3;/hour)</td>
        <td>Flow meter per zone</td></tr>
    <tr><td><span class="badge">valve_state</span></td>
        <td>Valve open/close events</td>
        <td>Irrigation controller (Talgil, Galcon)</td></tr>
  </table>

  <p>Supplementary inputs include <strong>crop type &amp; growth stage</strong>,
     <strong>soil classification</strong>, <strong>field area &amp; GPS</strong>,
     <strong>historical yield records</strong>, and <strong>water budget constraints</strong>.</p>

  <!-- ─── ALGORITHM ─── -->
  <h2>3. Recommendation Algorithm</h2>

  <h3>Stage 1 — Water Balance Model</h3>
  <p>Based on <strong>FAO-56 Penman-Monteith</strong> methodology, we calculate the irrigation
     deficit by combining two signals:</p>

  <div class="formula">
    VWC deficit = (target_VWC − current_VWC) &times; root_zone_depth<br/>
    ET deficit  = (ET0 &times; 3 days) − (rainfall &times; 0.75 efficiency)<br/><br/>
    <strong>Total deficit = 0.6 &times; VWC deficit + 0.4 &times; ET deficit</strong>
  </div>

  <p>Root zone depth is calibrated per crop:</p>
  <table>
    <tr><th>Crop</th><th>Root Zone Depth</th></tr>
    <tr><td>Corn</td><td>800 mm</td></tr>
    <tr><td>Wheat</td><td>600 mm</td></tr>
    <tr><td>Vegetables</td><td>400 mm</td></tr>
    <tr><td>Trees / Almonds</td><td>1,000 mm</td></tr>
    <tr><td>Vineyard</td><td>600 mm</td></tr>
  </table>

  <h3>Stage 2 — Machine Learning Ensemble</h3>
  <p>A <strong>Random Forest ensemble</strong> (200 estimators) is trained on historical
     field telemetry to predict ET0 and refine deficit estimates. The model is versioned,
     evaluated, and promoted through a controlled lifecycle.</p>

  <div class="card">
    <h3>Model Evaluation Criteria</h3>
    <ul>
      <li><strong>MAE</strong> (Mean Absolute Error) — target: &lt; 5 mm</li>
      <li><strong>RMSE</strong> (Root Mean Squared Error) — tracked per training run</li>
      <li><strong>R&sup2;</strong> (Coefficient of Determination) — target: &gt; 0.75</li>
      <li><strong>Feature importance</strong> — top features ranked and stored per version</li>
    </ul>
  </div>

  <!-- ─── OUTPUT ─── -->
  <h2>4. Recommendation Output</h2>
  <p>For each irrigation block, the engine produces:</p>

  <div class="card">
    <table>
      <tr><th>Field</th><th>Description</th></tr>
      <tr><td><strong>when</strong></td><td>Optimal irrigation start time (defaults to 6 AM)</td></tr>
      <tr><td><strong>duration_min</strong></td><td>How long to irrigate (minutes)</td></tr>
      <tr><td><strong>volume_m&sup3;</strong></td><td>Total water volume needed</td></tr>
      <tr><td><strong>confidence</strong></td><td>Model confidence score (0–1)</td></tr>
      <tr><td><strong>explanations</strong></td><td>Human-readable reasoning: deficit, ET0, VWC, efficiency</td></tr>
      <tr><td><strong>version</strong></td><td>Model version used (for audit trail)</td></tr>
    </table>
  </div>

  <p>Recommendations honor user-defined <strong>constraints</strong> (min/max duration, preferred
     time window, minimum interval between irrigations) and <strong>targets</strong> (soil VWC goal,
     application efficiency).</p>

  <!-- ─── ML PIPELINE ─── -->
  <h2>5. ML Pipeline &amp; Governance</h2>

  <div class="card">
    <h3>Model Lifecycle</h3>
    <p><span class="badge">training</span> <span class="badge">pilot</span>
       <span class="badge">production</span> <span class="badge">archived</span></p>
    <ul>
      <li><strong>Registry</strong> — versioned artifacts with SHA-256 checksums (filesystem, S3, or Azure Blob)</li>
      <li><strong>Promotion gate</strong> — new models must beat MAE &lt; 5mm and R&sup2; &gt; 0.75 before going live</li>
      <li><strong>Segmentation</strong> — models can be trained per crop type, region, or season</li>
      <li><strong>Audit trail</strong> — every training run records dataset hash, hyperparameters, metrics, and duration</li>
    </ul>
  </div>

  <!-- ─── INTEGRATIONS ─── -->
  <h2>6. Integrations &amp; Deployment</h2>
  <ul>
    <li><strong>Irrigation controllers:</strong> Talgil (live), Galcon (planned)</li>
    <li><strong>Data ingestion:</strong> REST API, file drop, AWS S3, Azure Blob</li>
    <li><strong>Cloud:</strong> Azure App Service with managed PostgreSQL</li>
    <li><strong>Edge:</strong> Raspberry Pi deployment for on-site processing</li>
    <li><strong>Sync cadence:</strong> Operational data every 15–20 minutes; historical backfill as batch</li>
  </ul>

  <!-- ─── ROI ─── -->
  <h2>7. Measured Outcomes</h2>
  <p>The platform tracks and reports:</p>
  <ul>
    <li><strong>Water saved</strong> (m&sup3;) — vs. baseline scheduling</li>
    <li><strong>Energy saved</strong> (kWh) — from optimized pump runtime</li>
    <li><strong>Cost savings</strong> (USD) — water + energy combined</li>
    <li><strong>Yield impact</strong> (%) — when historical yield data is available</li>
    <li><strong>Water budget utilization</strong> — real-time tracking against seasonal allocation</li>
  </ul>

  <p class="version">
    Model version: <strong>{MODEL_VERSION}</strong> &nbsp;|&nbsp;
    API: <code>GET /v1/model/info</code> for machine-readable model card &nbsp;|&nbsp;
    &copy; AGRO-AI
  </p>

</div>
</body>
</html>"""
    return HTMLResponse(content=html)
