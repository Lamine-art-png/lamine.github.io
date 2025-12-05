# agroai/report.py

from pathlib import Path
import csv
from shutil import copyfile

from .run_simulation import main as run_simulation_main
from .charts import main as charts_main

BASE_DIR = Path(__file__).resolve().parent
RESULTS_CSV = BASE_DIR / "agroai_results.csv"
CHARTS_DIR = BASE_DIR / "charts"
REPORTS_DIR = BASE_DIR / "reports"


def _load_summary():
    """Compute per-field seasonal totals and savings from the results CSV."""
    if not RESULTS_CSV.exists():
        return []

    per_field = {}

    with RESULTS_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = row["field_id"]
            b = float(row["baseline_in"])
            a = float(row["agroai_in"])

            entry = per_field.setdefault(
                fid,
                {
                    "field_id": fid,
                    "field_name": row["field_name"],
                    "baseline_in": 0.0,
                    "agroai_in": 0.0,
                },
            )
            entry["baseline_in"] += b
            entry["agroai_in"] += a

    for entry in per_field.values():
        baseline = entry["baseline_in"]
        agro = entry["agroai_in"]
        if baseline > 0:
            savings_in = baseline - agro
            savings_pct = savings_in / baseline * 100.0
        else:
            savings_in = 0.0
            savings_pct = 0.0

        entry["savings_in"] = savings_in
        entry["savings_pct"] = savings_pct

    return list(per_field.values())


def generate_sample_report() -> Path:
    """
    Run simulations, generate charts, and write an HTML sample report.

    Returns:
        Path to the generated HTML report.
    """
    # 1) Ensure data + charts exist
    run_simulation_main()
    charts_main()

    # 2) Load summary metrics
    summary = _load_summary()
    if not summary:
        raise RuntimeError("No data to report on")

    # For now we just use the first field (e.g. napa_cab_2024)
    field = summary[0]
    field_id = field["field_id"]

    baseline_in = field["baseline_in"]
    agroai_in = field["agroai_in"]
    savings_pct = field["savings_pct"]

    # 3) Image URLs as seen by the browser (served from /demo-assets)
    # The actual PNG files are written by charts_main() into CHARTS_DIR.
    timeseries_img_url = f"/demo-assets/{field_id}_timeseries.png"
    season_bar_img_url = f"/demo-assets/{field_id}_season_bar.png"

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORTS_DIR / "sample_report.html"

    # 4) Build HTML with inline CSS (Glacial Indifference + system fallbacks)
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>AGRO-AI Sample Water Report – {field['field_name']}</title>
  <style>
    @font-face {{
      font-family: "Glacial Indifference";
      src: url("/demo-assets/fonts/GlacialIndifference-Regular.woff2") format("woff2");
      font-weight: 400;
      font-style: normal;
      font-display: swap;
    }}
    @font-face {{
      font-family: "Glacial Indifference";
      src: url("/demo-assets/fonts/GlacialIndifference-Bold.woff2") format("woff2");
      font-weight: 700;
      font-style: normal;
      font-display: swap;
    }}

    body {{
      font-family: "Glacial Indifference", -apple-system, system-ui, sans-serif;
      margin: 2rem;
      color: #111;
      max-width: 960px;
      background: #f5f5f7;
    }}

    .page {{
      background: #fff;
      border-radius: 18px;
      padding: 32px 40px 40px;
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.12);
    }}

    h1 {{
      font-size: 1.6rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 0.4rem;
    }}

    h2 {{
      font-size: 1.1rem;
      margin-top: 2rem;
      margin-bottom: 0.6rem;
    }}

    h3 {{
      font-size: 0.9rem;
      margin-bottom: 0.4rem;
    }}

    .subtitle {{
      color: #666;
      font-size: 0.85rem;
      margin-bottom: 1.6rem;
    }}

    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}

    .kpi-card {{
      border-radius: 12px;
      border: 1px solid #e5e7eb;
      padding: 12px 14px;
      background: #fafafa;
    }}

    .kpi-label {{
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #6b7280;
      margin-bottom: 0.4rem;
    }}

    .kpi-value {{
      font-size: 1.1rem;
      font-weight: 700;
    }}

    .kpi-savings {{
      color: #15803d;
    }}

    .section-body {{
      font-size: 0.9rem;
      line-height: 1.5;
      color: #374151;
      margin-bottom: 1rem;
    }}

    .chart-wrapper {{
      margin: 1rem 0 2rem;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid #e5e7eb;
      background: #fcfcff;
    }}

    .chart-wrapper img {{
      max-width: 100%;
      height: auto;
      display: block;
      margin: 0 auto;
    }}

    .disclaimer {{
      font-size: 0.7rem;
      color: #9ca3af;
      margin-top: 1.8rem;
      border-top: 1px solid #e5e7eb;
      padding-top: 0.8rem;
    }}
  </style>
</head>
<body>
  <div class="page">
    <h1>AGRO-AI Sample Water Report</h1>
    <div class="subtitle">
      Field: {field['field_name']} ({field_id}) · Generated automatically by AGRO-AI engine
    </div>

    <h2>Executive Summary</h2>
    <div class="section-body">
      This sample report is generated by replaying a recent irrigation window on a representative Napa Cabernet block.
      We compare a typical baseline schedule against the AGRO-AI recommendation engine, using the same field,
      infrastructure, and constraints.
    </div>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Baseline seasonal water</div>
        <div class="kpi-value">{baseline_in:.2f} in</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">AGRO-AI seasonal water</div>
        <div class="kpi-value">{agroai_in:.2f} in</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Modeled savings</div>
        <div class="kpi-value kpi-savings">{savings_pct:.1f}%</div>
      </div>
    </div>

    <h2>Seasonal Water Use</h2>
    <div class="section-body">
      The chart below compares total applied water over the modeled window. AGRO-AI reduces applied water while
      respecting the configured daily capacity constraint. In a real deployment, this same structure scales to ranch,
      region, and portfolio views.
    </div>
    <div class="chart-wrapper">
      <img src="{season_bar_img_url}" alt="Seasonal water use – {field_id}" />
    </div>

    <h2>Daily Irrigation Profile</h2>
    <div class="section-body">
      Instead of a fixed pattern of irrigations, AGRO-AI follows weather-driven demand (ET) and system constraints.
      The daily curve below illustrates how the engine shifts and trims applications across the week.
    </div>
    <div class="chart-wrapper">
      <img src="{timeseries_img_url}" alt="Daily irrigation profile – {field_id}" />
    </div>

    <h2>How this scales for institutional landowners</h2>
    <div class="section-body">
      In production, the same reporting pipeline ingests block lists, allocations and pump logs for thousands of acres,
      then generates portfolio-grade water reports each quarter. This sample illustrates the structure and level of
      insight AGRO-AI provides before any manual Excel work or consulting study.
    </div>

    <div class="disclaimer">
      This sample is illustrative only and is based on modeled data for a single representative block.
      Portfolio performance will depend on crop mix, hardware constraints, and grower adherence.
    </div>
  </div>
</body>
</html>
"""

    html_path.write_text(html, encoding="utf-8")
    return html_path


if __name__ == "__main__":
    generate_sample_report()

