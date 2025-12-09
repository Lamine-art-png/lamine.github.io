# agroai/analysis.py

import csv
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RESULTS_CSV = BASE_DIR / "agroai_results.csv"


def main():
    if not RESULTS_CSV.exists():
        print(f"No results file found at {RESULTS_CSV}")
        return

    per_field = defaultdict(lambda: {"baseline_in": 0.0, "agroai_in": 0.0})

    with RESULTS_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = row["field_id"]
            b = float(row["baseline_in"])
            a = float(row["agroai_in"])
            per_field[fid]["baseline_in"] += b
            per_field[fid]["agroai_in"] += a

    if not per_field:
        print("No data rows in results.")
        return

    print("\n=== Season Summary per Field ===")
    for fid, agg in per_field.items():
        baseline = agg["baseline_in"]
        agro = agg["agroai_in"]
        if baseline <= 0:
            continue
        savings_in = baseline - agro
        savings_pct = savings_in / baseline * 100.0

        print(f"\nField: {fid}")
        print(f"  Baseline total: {baseline:.2f} in")
        print(f"  AGRO-AI total:  {agro:.2f} in")
        print(f"  Savings:        {savings_in:.2f} in ({savings_pct:.1f}%)")

    print("\nDone.")


if __name__ == "__main__":
    main()

