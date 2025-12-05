# agroai/charts.py

import csv
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless backend; no MacOS GUI windows

import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent
RESULTS_CSV = BASE_DIR / "agroai_results.csv"
CHARTS_DIR = BASE_DIR / "charts"


def load_results():
    rows = []
    if not RESULTS_CSV.exists():
        print(f"No results file at {RESULTS_CSV}")
        return rows

    with RESULTS_CSV.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            r["date"] = datetime.strptime(r["date"], "%Y-%m-%d").date()
            r["baseline_in"] = float(r["baseline_in"])
            r["agroai_in"] = float(r["agroai_in"])
            rows.append(r)
    return rows


def plot_daily_timeseries(rows, field_id: str):
    field_rows = [r for r in rows if r["field_id"] == field_id]
    if not field_rows:
        print(f"No rows for field {field_id}")
        return

    field_rows.sort(key=lambda r: r["date"])
    dates = [r["date"] for r in field_rows]
    baseline = [r["baseline_in"] for r in field_rows]
    agro = [r["agroai_in"] for r in field_rows]

    plt.figure()
    plt.plot(dates, baseline, label="Baseline (in/day)")
    plt.plot(dates, agro, label="AGRO-AI (in/day)")
    plt.xlabel("Date")
    plt.ylabel("Irrigation (inches)")
    plt.title(f"Daily Irrigation – {field_id}")
    plt.legend()
    plt.tight_layout()

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHARTS_DIR / f"{field_id}_timeseries.png"
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Wrote {out_path}")


def plot_season_bar(rows, field_id: str):
    field_rows = [r for r in rows if r["field_id"] == field_id]
    if not field_rows:
        print(f"No rows for field {field_id}")
        return

    baseline_total = sum(r["baseline_in"] for r in field_rows)
    agro_total = sum(r["agroai_in"] for r in field_rows)

    labels = ["Baseline", "AGRO-AI"]
    values = [baseline_total, agro_total]

    plt.figure()
    plt.bar(labels, values)
    plt.ylabel("Total seasonal water (inches)")
    plt.title(f"Seasonal Water Use – {field_id}")
    plt.tight_layout()

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHARTS_DIR / f"{field_id}_season_bar.png"
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Wrote {out_path}")


def main():
    rows = load_results()
    if not rows:
        return

    field_ids = sorted({r["field_id"] for r in rows})
    print("Fields:", field_ids)

    for fid in field_ids:
        plot_daily_timeseries(rows, fid)
        plot_season_bar(rows, fid)


if __name__ == "__main__":
    main()

