import json
import csv
from pathlib import Path
from datetime import datetime, date, timedelta

from .baselines import BASELINES
from .engine import recommend_irrigation

# Base directory of the agroai package
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_CSV = BASE_DIR / "agroai_results.csv"


def daterange(start: date, end: date):
    curr = start
    while curr <= end:
        yield curr
        curr += timedelta(days=1)


def load_field_config(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def load_weather_index(csv_path: Path) -> dict:
    index = {}
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_date = row.get("date", "").strip()
            if not raw_date:
                continue
            try:
                d = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                # Skip any row that doesn't look like a proper date
                print(f"Skipping row with bad date value: {raw_date!r}")
                continue
            index[d] = row
    return index

def build_payload(cfg: dict, day: date, weather_row: dict) -> dict:
    return {
        "field_id": cfg["field_id"],
        "location": {"lat": cfg["lat"], "lon": cfg["lon"]},
        "crop": {
            "type": cfg["crop"],
            "season_start": cfg["season_start"],
            "season_end": cfg["season_end"],
        },
        "soil": {
            "type": cfg["soil_type"],
            "root_depth_m": cfg["root_depth_m"],
        },
        "system": cfg["system"],
        "constraints": cfg["constraints"],
        "date": day.isoformat(),
        "weather": {
            "et0_mm": float(weather_row.get("et0_mm", 0.0)),
            "precip_mm": float(weather_row.get("precip_mm", 0.0)),
            "t_mean_c": float(weather_row.get("t_mean_c", 0.0)),
        },
    }


def run_one_field(config_path: Path) -> list[dict]:
    cfg = load_field_config(config_path)

    # weather_csv should be a path *relative to the agroai package*
    weather_csv_path = BASE_DIR / cfg["weather_csv"]
    weather_index = load_weather_index(weather_csv_path)

    baseline_fn = BASELINES[cfg["baseline_schedule_type"]]

    start = datetime.strptime(cfg["season_start"], "%Y-%m-%d").date()
    end = datetime.strptime(cfg["season_end"], "%Y-%m-%d").date()

    rows = []
    for day in daterange(start, end):
        if day not in weather_index:
            continue

        weather_row = weather_index[day]
        baseline_in = baseline_fn(day)

        payload = build_payload(cfg, day, weather_row)
        recommended_inches = recommend_irrigation(payload)

        rows.append({
            "field_id": cfg["field_id"],
            "field_name": cfg["name"],
            "date": day.isoformat(),
            "et0_mm": weather_row.get("et0_mm"),
            "baseline_in": baseline_in,
            "agroai_in": recommended_inches,
        })

    return rows


def main():
    configs_dir = BASE_DIR / "configs"
    all_rows = []

    for cfg_path in configs_dir.glob("*.json"):
        print(f"Running simulation for {cfg_path.name}")
        rows = run_one_field(cfg_path)
        all_rows.extend(rows)

    if not all_rows:
        print("No rows generated.")
        return

    with OUTPUT_CSV.open("w", newline="") as f:
        fieldnames = [
            "field_id",
            "field_name",
            "date",
            "et0_mm",
            "baseline_in",
            "agroai_in",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)

    print(f"Wrote {len(all_rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

