"""Administrative-location resolution for agricultural context.

Resolves caller-supplied country / state(region) / district labels against a
versioned gazetteer derived from GeoNames (CC BY 4.0). The result states how a
label was matched and how precise the resulting point is. A resolved district
is an administrative representative point, never a field location.

Standard library only: the reference-data builder imports this module outside
the application runtime.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

_SUFFIXES = ("district", "zila", "zilla", "jila", "jilla", "division", "dist")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")

# ISO 3166-2:IN subdivision codes and common legacy spellings. Values are
# normalized state names as published by GeoNames admin1 codes.
STATE_ALIASES: dict[str, dict[str, str]] = {
    "IN": {
        "an": "andaman and nicobar islands", "ap": "andhra pradesh", "ar": "arunachal pradesh",
        "as": "assam", "br": "bihar", "ch": "chandigarh", "cg": "chhattisgarh", "ct": "chhattisgarh",
        "dl": "delhi", "nct of delhi": "delhi", "national capital territory of delhi": "delhi",
        "ga": "goa", "gj": "gujarat", "hr": "haryana", "hp": "himachal pradesh",
        "jk": "jammu and kashmir", "jh": "jharkhand", "ka": "karnataka", "kl": "kerala",
        "la": "ladakh", "mp": "madhya pradesh", "mh": "maharashtra", "mn": "manipur",
        "ml": "meghalaya", "mz": "mizoram", "nl": "nagaland", "od": "odisha", "or": "odisha",
        "orissa": "odisha", "py": "puducherry", "pondicherry": "puducherry", "pb": "punjab",
        "rj": "rajasthan", "sk": "sikkim", "tn": "tamil nadu", "tg": "telangana", "ts": "telangana",
        "tr": "tripura", "up": "uttar pradesh", "uk": "uttarakhand", "ut": "uttarakhand",
        "uttaranchal": "uttarakhand", "wb": "west bengal",
    },
}

# Officially renamed districts (old <-> new). Matching through this table is
# reported as ``rename_alias`` so callers can update stored labels.
DISTRICT_RENAMES: dict[str, dict[str, str]] = {
    "IN": {
        "allahabad": "prayagraj", "faizabad": "ayodhya", "gurgaon": "gurugram",
        "hoshangabad": "narmadapuram", "belgaum": "belagavi", "mysore": "mysuru",
        "bangalore": "bengaluru", "bangalore urban": "bengaluru urban", "gulbarga": "kalaburagi",
        "bellary": "ballari", "shimoga": "shivamogga", "tumkur": "tumakuru",
        "mewat": "nuh", "osmanabad": "dharashiv", "aurangabad": "chhatrapati sambhajinagar",
    },
}

PRECISION = "administrative_representative_point"
PRECISION_NOTE = (
    "District resolved to a GeoNames second-level administrative representative point. "
    "It is not a field location; climate and soil values at this point are coarse regional context."
)


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.casefold().replace("&", " and ")
    text = _SPACES.sub(" ", _NON_WORD.sub(" ", text)).strip()
    words = text.split(" ")
    while len(words) > 1 and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def _names(entry: dict[str, Any]) -> set[str]:
    names = {normalize(entry.get("name")), normalize(entry.get("ascii"))}
    names.update(normalize(item) for item in entry.get("alt") or [])
    names.discard("")
    return names


class Gazetteer:
    """Read-only lookup over the ``gazetteer`` section of the reference data."""

    def __init__(self, data: dict[str, Any]):
        self._countries = data

    def countries(self) -> list[str]:
        return sorted(self._countries)

    def _state_codes(self, country: str, label: str) -> set[str]:
        states = self._countries[country]["states"]
        wanted = normalize(label)
        wanted = STATE_ALIASES.get(country, {}).get(wanted, wanted)
        return {code for code, entry in states.items() if wanted in _names(entry)}

    def _district_matches(self, country: str, label: str, codes: set[str] | None) -> tuple[list[dict[str, Any]], str]:
        districts = self._countries[country]["districts"]
        wanted = normalize(label)
        exact = [d for d in districts if (codes is None or d["admin1"] in codes) and wanted in _names(d)]
        if exact:
            return exact, "exact"
        renames = DISTRICT_RENAMES.get(country, {})
        alias = renames.get(wanted) or next((old for old, new in renames.items() if new == wanted), None)
        if alias:
            aliased = [d for d in districts if (codes is None or d["admin1"] in codes) and alias in _names(d)]
            if aliased:
                return aliased, "rename_alias"
        return [], "none"

    def _public(self, country: str, district: dict[str, Any]) -> dict[str, Any]:
        state = self._countries[country]["states"].get(district["admin1"], {})
        return {
            "geoname_id": district["id"],
            "district": district["name"],
            "state": state.get("name"),
            "country": country,
            "latitude": district["lat"],
            "longitude": district["lon"],
        }

    def resolve(self, country: str, state: str | None, district: str) -> dict[str, Any]:
        country = str(country or "").upper()
        if country not in self._countries:
            return {"status": "country_not_supported", "supported_countries": self.countries()}
        codes = self._state_codes(country, state or "")
        if not codes:
            names = [entry["name"] for entry in self._countries[country]["states"].values()]
            return {
                "status": "state_not_found",
                "suggestions": difflib.get_close_matches(str(state or ""), names, n=5, cutoff=0.6),
            }
        matches, method = self._district_matches(country, district, codes)
        if len(matches) == 1:
            return {
                "status": "resolved",
                "match_method": method,
                "precision": PRECISION,
                "precision_note": PRECISION_NOTE,
                **self._public(country, matches[0]),
            }
        if len(matches) > 1:
            return {"status": "ambiguous", "candidates": [self._public(country, item) for item in matches]}
        elsewhere, _method = self._district_matches(country, district, None)
        if elsewhere:
            return {"status": "state_mismatch", "candidates": [self._public(country, item) for item in elsewhere]}
        in_state = [d["name"] for d in self._countries[country]["districts"] if d["admin1"] in codes]
        return {
            "status": "district_not_found",
            "suggestions": difflib.get_close_matches(str(district or ""), in_state, n=5, cutoff=0.6),
        }
