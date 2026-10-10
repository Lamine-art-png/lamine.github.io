"""Deterministic guard against unsupported quantitative claims in visual output.

Ordinary RGB imagery cannot measure chemical concentration, residue, dosage,
soil or tissue chemistry, sugar content, exact moisture, or yield per area.
A vision-language model can still emit such numbers. This module finds them,
replaces the numeric claim with a neutral marker, and reports a flag so the
result is visibly downgraded instead of silently trusted.

The same detector is used by the evaluation harness, so the release metric
"zero unsupported chemical/medical-like numeric claims" is measured with the
exact rule that the runtime enforces.

Unit-based detection is language-independent. Keyword-based percentage
detection covers English, Portuguese and Spanish terms; other locales still get
unit-based protection.
"""
from __future__ import annotations

import re
from typing import Any

REDACTION_MARKER = "[unsupported measurement removed]"
FLAG_UNSUPPORTED_MEASUREMENT = "unsupported_quantitative_claim_removed"

_NUMBER = r"\d+(?:[.,]\d+)?"
_RANGE = rf"(?:{_NUMBER}\s*(?:-|–|to|a|até)\s*)?{_NUMBER}"

# number + unit that only instruments, laboratories, or records can establish.
_UNIT_CLAIM = re.compile(
    rf"(?<![\w.]){_RANGE}\s*(?:"
    r"ppm|ppb|"
    r"mg\s*/\s*(?:kg|l|dl|ml|m3|m³)|"
    r"(?:µg|μg|ug|ng)\s*/\s*\w+|"
    r"g\s*/\s*(?:l|ha|kg|m2|m²|plant|planta)|"
    r"kg\s*/\s*(?:ha|acre|ac|plant|planta)|"
    r"t\s*/\s*(?:ha|acre|ac)|tons?\s*/\s*(?:ha|acre|ac)|"
    r"l\s*/\s*(?:ha|acre|ac)|ml\s*/\s*(?:l|ha|gal|acre|ac)|"
    r"oz\s*/\s*(?:acre|ac|gal)|lbs?\s*/\s*(?:acre|ac)|gal\s*/\s*(?:acre|ac)|"
    r"bu\s*/\s*(?:acre|ac)|"
    r"meq(?:\s*/\s*\w+)?|cmol(?:c)?(?:\s*/\s*kg)?|"
    r"d[sS]\s*/\s*m|[mµμu][sS]\s*/\s*cm|"
    r"°\s*brix|brix"
    r")(?![\w/])",
    re.IGNORECASE,
)

_PH_CLAIM = re.compile(
    rf"\bpH\s*(?:of|=|:|is|at|around|approximately|approx\.?|~|de|em|é|es)?\s*{_RANGE}",
    re.IGNORECASE,
)

_CHEM_TERMS = (
    "nitrogen|phosphorus|potassium|moisture|soil moisture|residue|concentration|"
    "active ingredient|brix|sugar|chlorophyll|salinity|organic matter|"
    "nitrogênio|nitrogenio|fósforo|fosforo|potássio|potassio|umidade|resíduo|residuo|"
    "concentração|concentracao|clorofila|salinidade|matéria orgânica|"
    "nitrógeno|potasio|humedad|concentración|concentracion|salinidad|materia orgánica"
)
_WORD_GAP = r"(?:[\wÀ-ÿ]+[\s,;:()\-]+)"
_PERCENT_CHEM = re.compile(
    rf"{_RANGE}\s*%\s*{_WORD_GAP}{{0,3}}?(?:{_CHEM_TERMS})\b"
    rf"|\b(?:{_CHEM_TERMS})[\s,;:()\-]+{_WORD_GAP}{{0,4}}?{_RANGE}\s*%",
    re.IGNORECASE,
)
# Elemental nutrient symbols next to a percentage ("leaf N 1.8%", "K: 2%").
# Case-sensitive so ordinary words are not mistaken for element symbols; B and
# S are omitted because lettered blocks ("Block B 30% defoliated") are common.
_ELEMENT_PERCENT = re.compile(rf"\b(?:N|P|K|Ca|Mg|Fe|Zn|Mn|Cu|Mo)\s*(?:=|:|at|of)?\s*{_RANGE}\s*%")

_PATTERNS = (_UNIT_CLAIM, _PH_CLAIM, _PERCENT_CHEM, _ELEMENT_PERCENT)


def find_unsupported_measurements(text: str) -> list[str]:
    """Return every unsupported quantitative claim found in ``text``."""
    if not text:
        return []
    found: list[str] = []
    for pattern in _PATTERNS:
        found.extend(match.group(0).strip() for match in pattern.finditer(text))
    return found


def redact_unsupported_measurements(text: str) -> tuple[str, int]:
    """Replace unsupported quantitative claims; return (text, replacements)."""
    if not text:
        return text, 0
    total = 0
    for pattern in _PATTERNS:
        text, count = pattern.subn(REDACTION_MARKER, text)
        total += count
    return text, total


def redact_value(value: Any) -> tuple[Any, int]:
    """Recursively redact strings inside lists/dicts; non-strings pass through."""
    if isinstance(value, str):
        return redact_unsupported_measurements(value)
    if isinstance(value, list):
        total = 0
        cleaned = []
        for item in value:
            item, count = redact_value(item)
            cleaned.append(item)
            total += count
        return cleaned, total
    if isinstance(value, dict):
        total = 0
        cleaned_dict: dict[str, Any] = {}
        for key, item in value.items():
            item, count = redact_value(item)
            cleaned_dict[key] = item
            total += count
        return cleaned_dict, total
    return value, 0
