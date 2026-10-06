#!/usr/bin/env python3
"""Generate the shared ISO 3166-1 country and ISO 4217 currency registries.

Sources (generation-time only; runtime code reads the committed JSON):
- countries: tz database ``iso3166.tab`` (ISO 3166-1 alpha-2, via pytz) and
  ``zone.tab`` for each country's primary IANA time zone;
- currencies: Unicode CLDR territory tender data (via Babel) as of AS_OF.

Customer-facing names are not stored: the portal renders them with
``Intl.DisplayNames`` in the viewer's locale, so every advertised locale gets
localized country and currency names without English fallbacks.

Usage: python3 scripts/generate_iso_registries.py [--check]
Requires: pip install babel pytz (not runtime dependencies).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import babel
import pytz
from babel.numbers import get_currency_precision, get_territory_currencies

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shared" / "registries"
AS_OF = date(2026, 10, 3)

# Territories outside ISO 3166-1 that agricultural customers operate in.
# Kosovo uses the user-assigned code XK (European Commission, Unicode CLDR).
EXTRA_TERRITORIES = {"XK": ("Kosovo", "Europe/Belgrade")}

# Facts newer than the CLDR release bundled with Babel. Each entry names its source.
CURRENCY_OVERRIDES = {
    # Bulgaria adopted the euro on 2026-01-01 (Council Decision (EU) 2025/1407).
    "BG": ["EUR"],
}


def build() -> tuple[dict, dict]:
    countries = []
    tenders: set[str] = set()
    for code in sorted(set(pytz.country_names) | set(EXTRA_TERRITORIES)):
        currencies = CURRENCY_OVERRIDES.get(code) or get_territory_currencies(code, AS_OF, tender=True, non_tender=False)
        tenders.update(currencies)
        zones = pytz.country_timezones.get(code) or ([EXTRA_TERRITORIES[code][1]] if code in EXTRA_TERRITORIES else [])
        countries.append({
            "code": code,
            "default_currency": currencies[0] if currencies else None,
            "currencies": list(currencies),
            "timezone": zones[0] if zones else "UTC",
            "iso3166_assigned": code not in EXTRA_TERRITORIES,
        })
    currencies = [{"code": code, "minor_units": get_currency_precision(code)} for code in sorted(tenders)]
    meta = {"as_of": AS_OF.isoformat(), "sources": {"countries": f"tzdata iso3166.tab/zone.tab (pytz {pytz.__version__})", "currencies": f"Unicode CLDR territory currencies (Babel {babel.__version__})"}}
    return (
        {"schema": "agroai.iso3166-1.v1", **meta, "count": len(countries), "countries": countries},
        {"schema": "agroai.iso4217.v1", **meta, "count": len(currencies), "currencies": currencies},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    countries, currencies = build()
    outputs = {OUT / "countries.json": countries, OUT / "currencies.json": currencies}
    stale = []
    for path, payload in outputs.items():
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        print(f"stale registries: {', '.join(stale)}", file=sys.stderr)
        return 1
    print(json.dumps({"countries": countries["count"], "currencies": currencies["count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
