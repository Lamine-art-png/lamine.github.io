from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class OperationalInvariantCheck:
    ok: bool
    violations: tuple[str, ...]


NUMBER_RE = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?(?![\w])")
TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
URL_RE = re.compile(r"https?://[^\s)>\]}]+", re.IGNORECASE)
CITATION_RE = re.compile(r"\[(?:\d+(?:\s*[-,]\s*\d+)*|(?:source|citation|ref)\s*:[^\]]+)\]", re.IGNORECASE)

UNIT_PATTERNS = (
    (re.compile(r"\b(?:acre[-\s]?ft|ac[-\s]?ft|acre[-\s]?feet?)\b", re.IGNORECASE), "acre-ft"),
    (re.compile(r"\bacres?\b", re.IGNORECASE), "acre"),
    (re.compile(r"\bmm/(?:day|d)\b", re.IGNORECASE), "mm/day"),
    (re.compile(r"\bmm\b", re.IGNORECASE), "mm"),
    (re.compile(r"\bm(?:3|³)\b", re.IGNORECASE), "m3"),
    (re.compile(r"\b(?:ha|hectares?)\b", re.IGNORECASE), "ha"),
    (re.compile(r"\b(?:gal|gallons?)\b", re.IGNORECASE), "gallon"),
    (re.compile(r"\bgpm\b", re.IGNORECASE), "gpm"),
    (re.compile(r"\bpsi\b", re.IGNORECASE), "psi"),
    (re.compile(r"\bkpa\b", re.IGNORECASE), "kpa"),
    (re.compile(r"%"), "percent"),
)

PROTECTED_TERMS = ("WiseConn", "John Deere", "SGMA", "ETc", "ETo", "NDVI", "VWC", "AGRO-AI")
NEGATION_MARKERS = ("do not", "don't", "never", "must not", "should not", "avoid", " n’", " n'", " pas ", " jamais ", " no ", " não ", " nao ")
UNCERTAINTY_MARKERS = ("confidence", "uncertain", "estimate", "approximately", "likely", "might", "confiance", "incertain", "environ", "probable", "confianza", "confiança", "±")


def normalize_number(token: str) -> str:
    try:
        value = Decimal(token.replace(",", "."))
    except InvalidOperation:
        return token
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"-0", "+0", ""} else normalized


def numbers(text: str) -> Counter[str]:
    return Counter(normalize_number(match.group(0)) for match in NUMBER_RE.finditer(text or ""))


def times(text: str) -> Counter[str]:
    return Counter(match.group(0) for match in TIME_RE.finditer(text or ""))


def units(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for pattern, family in UNIT_PATTERNS:
        counts[family] += len(pattern.findall(text or ""))
    return +counts


def citations(text: str) -> Counter[str]:
    value = text or ""
    found = [match.group(0) for match in URL_RE.finditer(value)]
    found.extend(match.group(0).casefold() for match in CITATION_RE.finditer(value))
    return Counter(found)


def protected_terms(text: str) -> Counter[str]:
    value = (text or "").casefold()
    return Counter({term: value.count(term.casefold()) for term in PROTECTED_TERMS if term.casefold() in value})


def markdown_signature(text: str) -> tuple[tuple[int, ...], int, int, int, int, int]:
    lines = (text or "").splitlines()
    headings = tuple(len(match.group(1)) for line in lines if (match := re.match(r"^\s*(#{1,6})\s+", line)))
    bullets = sum(bool(re.match(r"^\s*[-*+]\s+", line)) for line in lines)
    ordered = sum(bool(re.match(r"^\s*\d+[.)]\s+", line)) for line in lines)
    quotes = sum(bool(re.match(r"^\s*>\s?", line)) for line in lines)
    tables = sum(line.count("|") >= 2 for line in lines)
    fences = sum(bool(re.match(r"^\s*```", line)) for line in lines)
    return headings, bullets, ordered, quotes, tables, fences


def has_marker(text: str, markers: tuple[str, ...]) -> bool:
    value = f" {(text or '').casefold()} "
    return any(marker.casefold() in value for marker in markers)


def check_operational_invariants(original: str, repaired: str) -> OperationalInvariantCheck:
    violations: list[str] = []
    if numbers(original) != numbers(repaired):
        violations.append("numeric_values_changed")
    if times(original) != times(repaired):
        violations.append("times_changed")
    if units(original) != units(repaired):
        violations.append("units_changed")
    if citations(original) != citations(repaired):
        violations.append("citations_changed")
    if protected_terms(original) != protected_terms(repaired):
        violations.append("protected_terms_changed")
    if markdown_signature(original) != markdown_signature(repaired):
        violations.append("markdown_structure_changed")
    if has_marker(original, NEGATION_MARKERS) and not has_marker(repaired, NEGATION_MARKERS):
        violations.append("negation_lost")
    if has_marker(original, UNCERTAINTY_MARKERS) and not has_marker(repaired, UNCERTAINTY_MARKERS):
        violations.append("uncertainty_lost")
    return OperationalInvariantCheck(ok=not violations, violations=tuple(violations))
