#!/usr/bin/env python3
"""Build the versioned DMRV reference dataset from public, licensed sources.

Sources (all permit commercial use with attribution):
  * GeoNames country dumps + admin1 codes (CC BY 4.0) -> administrative gazetteer
  * NASA POWER daily point API, AG community (NASA open data), 2004-2023 ->
    monthly means of daily values (the POWER *climatology* T2M_MAX/T2M_MIN are
    monthly extremes, which are not valid Penman-Monteith inputs)
  * ISRIC SoilGrids 2.0 REST API (CC BY 4.0) -> 0-30 cm topsoil properties

Run where outbound HTTPS is allowed (the GitHub Actions workflow
``dmrv-reference-data.yml``). Output is deterministic JSON that the API loads
read-only; nothing is fetched at request time.

    python3 agroai_api/scripts/build_dmrv_reference_data.py --out /tmp/dmrv_reference_v1.json
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import importlib.util
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("geography", ROOT / "app" / "intelligence_platform" / "geography.py")
geography = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(geography)

USER_AGENT = "AGRO-AI-reference-data-builder/1.0 (+https://agroai-pilot.com)"
COUNTRIES = ("IN", "BD")
GEONAMES_DUMP = "https://download.geonames.org/export/dump/{country}.zip"
GEONAMES_ADMIN1 = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_START, POWER_END = "20040101", "20231231"
POWER_PARAMETERS = ("T2M", "T2M_MAX", "T2M_MIN", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN", "PRECTOTCORR")
SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
SOIL_PROPERTIES = ("phh2o", "soc", "clay", "sand", "silt", "nitrogen", "cec")
SOIL_DEPTHS = (("0-5cm", 5), ("5-15cm", 10), ("15-30cm", 15))
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_LATIN = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,59}$")

# Districts with precomputed climate and soil context: major agro-climatic
# zones and crop systems, plus deliberately ambiguous district names.
TARGETS: tuple[tuple[str, str, str], ...] = (
    ("IN", "Uttar Pradesh", "Gautam Buddha Nagar"), ("IN", "Uttar Pradesh", "Meerut"),
    ("IN", "Uttar Pradesh", "Lucknow"), ("IN", "Uttar Pradesh", "Varanasi"), ("IN", "Uttar Pradesh", "Gorakhpur"),
    ("IN", "Punjab", "Ludhiana"), ("IN", "Punjab", "Bathinda"), ("IN", "Punjab", "Amritsar"),
    ("IN", "Haryana", "Karnal"), ("IN", "Haryana", "Hisar"),
    ("IN", "Rajasthan", "Jaipur"), ("IN", "Rajasthan", "Bikaner"), ("IN", "Rajasthan", "Ganganagar"),
    ("IN", "Madhya Pradesh", "Indore"), ("IN", "Madhya Pradesh", "Ujjain"), ("IN", "Madhya Pradesh", "Hoshangabad"),
    ("IN", "Maharashtra", "Pune"), ("IN", "Maharashtra", "Nashik"), ("IN", "Maharashtra", "Nagpur"),
    ("IN", "Maharashtra", "Yavatmal"), ("IN", "Maharashtra", "Aurangabad"),
    ("IN", "Bihar", "Aurangabad"), ("IN", "Bihar", "Patna"), ("IN", "Bihar", "Purnia"),
    ("IN", "Gujarat", "Rajkot"), ("IN", "Gujarat", "Banaskantha"),
    ("IN", "Karnataka", "Mandya"), ("IN", "Karnataka", "Dharwad"), ("IN", "Karnataka", "Belgaum"),
    ("IN", "Tamil Nadu", "Thanjavur"), ("IN", "Tamil Nadu", "Coimbatore"),
    ("IN", "Andhra Pradesh", "Guntur"), ("IN", "Telangana", "Nalgonda"),
    ("IN", "West Bengal", "Nadia"), ("IN", "Odisha", "Cuttack"), ("IN", "Assam", "Nagaon"),
    ("IN", "Kerala", "Palakkad"),
    ("BD", "Rajshahi", "Bogra"), ("BD", "Rangpur", "Dinajpur"), ("BD", "Mymensingh", "Mymensingh"),
)


def _get(url: str, *, attempts: int = 3, timeout: int = 60, backoff: int = 10) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"fetch failed after {attempts} attempts: {url}") from last


def build_gazetteer() -> dict:
    admin1: dict[str, dict] = {}
    for line in _get(GEONAMES_ADMIN1).decode("utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 4 and parts[0].split(".")[0] in COUNTRIES:
            country, code = parts[0].split(".", 1)
            admin1.setdefault(country, {})[code] = {"name": parts[1], "ascii": parts[2], "id": int(parts[3]), "alt": []}
    gazetteer: dict[str, dict] = {}
    for country in COUNTRIES:
        archive = zipfile.ZipFile(io.BytesIO(_get(GEONAMES_DUMP.format(country=country))))
        rows = archive.read(f"{country}.txt").decode("utf-8").splitlines()
        districts = []
        states = admin1.get(country, {})
        for line in rows:
            parts = line.split("\t")
            if len(parts) < 19 or parts[6] != "A":
                continue
            alternates = sorted({name for name in parts[3].split(",") if _LATIN.match(name)})[:12]
            if parts[7] == "ADM1" and parts[10] in states:
                states[parts[10]]["alt"] = alternates
            elif parts[7] == "ADM2":
                districts.append({
                    "id": int(parts[0]), "name": parts[1], "ascii": parts[2], "alt": alternates,
                    "admin1": parts[10], "lat": round(float(parts[4]), 5), "lon": round(float(parts[5]), 5),
                })
        districts.sort(key=lambda item: (item["admin1"], item["name"], item["id"]))
        gazetteer[country] = {"states": dict(sorted(states.items())), "districts": districts}
    return gazetteer


def fetch_climate(lat: float, lon: float) -> dict:
    query = urllib.parse.urlencode({
        "parameters": ",".join(POWER_PARAMETERS), "community": "AG", "longitude": f"{lon:.4f}", "latitude": f"{lat:.4f}",
        "start": POWER_START, "end": POWER_END, "format": "JSON",
    })
    body = json.loads(_get(f"{POWER_URL}?{query}", timeout=120))
    parameters = body["properties"]["parameter"]
    units = {name: (body.get("parameters") or {}).get(name, {}).get("units") for name in POWER_PARAMETERS}
    solar_factor = 3.6 if str(units.get("ALLSKY_SFC_SW_DWN") or "").lower().startswith("kw") else 1.0
    sums: dict[tuple[str, int], list[float]] = {}
    for name in POWER_PARAMETERS:
        for day, raw in (parameters.get(name) or {}).items():
            if raw is None or raw <= -998:
                continue
            sums.setdefault((name, int(day[4:6])), []).append(float(raw))

    def mean(name: str, month: int, minimum_days: int = 300) -> float | None:
        values = sums.get((name, month)) or []
        return round(sum(values) / len(values), 3) if len(values) >= minimum_days else None

    monthly = {}
    for month in range(1, 13):
        solar = mean("ALLSKY_SFC_SW_DWN", month)
        monthly[str(month)] = {
            "tmean_c": mean("T2M", month), "tmax_c": mean("T2M_MAX", month), "tmin_c": mean("T2M_MIN", month),
            "rh_mean_pct": mean("RH2M", month), "wind_2m_ms": mean("WS2M", month),
            "solar_mj_m2_day": None if solar is None else round(solar * solar_factor, 3),
            "precip_mm_day": mean("PRECTOTCORR", month),
            "days": len(sums.get(("T2M_MAX", month)) or []),
        }
    coordinates = (body.get("geometry") or {}).get("coordinates") or [lon, lat, None]
    return {
        "source": "NASA POWER daily (AG community), monthly means of daily values",
        "period": f"{POWER_START[:4]}-{POWER_END[:4]}",
        "grid_point": {"latitude": coordinates[1], "longitude": coordinates[0]},
        "elevation_m": coordinates[2] if len(coordinates) > 2 else None,
        "units_reported": units,
        "monthly": monthly,
    }


def fetch_soil(lat: float, lon: float) -> dict:
    params = [("lon", f"{lon:.4f}"), ("lat", f"{lat:.4f}"), ("value", "mean")]
    params += [("property", name) for name in SOIL_PROPERTIES] + [("depth", label) for label, _w in SOIL_DEPTHS]
    body = json.loads(_get(f"{SOILGRIDS_URL}?{urllib.parse.urlencode(params)}", attempts=2, timeout=30, backoff=15))
    result: dict[str, dict] = {}
    for layer in body.get("properties", {}).get("layers", []):
        factor = float((layer.get("unit_measure") or {}).get("d_factor") or 1)
        target = (layer.get("unit_measure") or {}).get("target_units")
        by_depth = {d["label"]: (d.get("values") or {}).get("mean") for d in layer.get("depths", [])}
        weighted, weight = 0.0, 0
        for label, thickness in SOIL_DEPTHS:
            raw = by_depth.get(label)
            if raw is not None:
                weighted += float(raw) / factor * thickness
                weight += thickness
        result[layer["name"]] = {
            "value_0_30cm": round(weighted / weight, 3) if weight == 30 else None,
            "units": target,
        }
    return {"source": "ISRIC SoilGrids 2.0 (250 m, mean)", "depth": "0-30 cm thickness-weighted", "properties": result}


def build(out: Path) -> dict:
    gazetteer = build_gazetteer()
    resolver = geography.Gazetteer(gazetteer)
    climate, soil, unresolved = {}, {}, []
    soil_failures = 0
    print(f"gazetteer: {sum(len(c['districts']) for c in gazetteer.values())} districts", flush=True)
    for country, state, district in TARGETS:
        match = resolver.resolve(country, state, district)
        if match["status"] != "resolved":
            unresolved.append({"target": [country, state, district], "result": match})
            print(f"unresolved {country}/{state}/{district}: {match['status']}", flush=True)
            continue
        key = str(match["geoname_id"])
        try:
            climate[key] = fetch_climate(match["latitude"], match["longitude"])
        except (RuntimeError, KeyError, ValueError) as exc:
            print(f"climate failed {district}: {exc}", flush=True)
        if soil_failures >= 3:
            soil[key] = {"source": "ISRIC SoilGrids 2.0 (250 m, mean)", "error": "skipped after repeated SoilGrids failures"}
        else:
            try:
                soil[key] = fetch_soil(match["latitude"], match["longitude"])
                soil_failures = 0
            except (RuntimeError, KeyError, ValueError) as exc:
                soil_failures += 1
                soil[key] = {"source": "ISRIC SoilGrids 2.0 (250 m, mean)", "error": str(exc)[:200]}
            time.sleep(13)  # SoilGrids fair-use limit: 5 requests per minute.
        print(f"done {country}/{state}/{district} climate={key in climate} soil={'error' not in soil.get(key, {})}", flush=True)
    data = {
        "dataset": "agroai-dmrv-reference",
        "version": "1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sources": {
            "gazetteer": {"name": "GeoNames", "license": "CC BY 4.0", "url": "https://www.geonames.org/"},
            "climate": {"name": "NASA POWER daily data, 2004-2023 monthly means", "license": "NASA open data; attribution requested", "url": "https://power.larc.nasa.gov/"},
            "soil": {"name": "ISRIC SoilGrids 2.0", "license": "CC BY 4.0", "url": "https://soilgrids.org/"},
        },
        "gazetteer": gazetteer,
        "climate": climate,
        "soil": soil,
        "unresolved_targets": unresolved,
    }
    out.write_text(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--emit-log-chunks", action="store_true", help="also print gzip+base64 chunks for log transport")
    args = parser.parse_args()
    data = build(args.out)
    raw = args.out.read_bytes()
    print(f"dmrv-reference sha256={hashlib.sha256(raw).hexdigest()} bytes={len(raw)} "
          f"districts={sum(len(c['districts']) for c in data['gazetteer'].values())} "
          f"climate={len(data['climate'])} soil={len(data['soil'])} unresolved={len(data['unresolved_targets'])}")
    print(json.dumps(data["unresolved_targets"], indent=1))
    if args.emit_log_chunks:
        encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")
        for index in range(0, len(encoded), 3000):
            print(f"DMRVREF {index // 3000:05d} {encoded[index:index + 3000]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
