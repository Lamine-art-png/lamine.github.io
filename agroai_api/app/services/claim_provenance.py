from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.evidence_freshness import evaluate_evidence_freshness


_NUM = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?(?![\w])")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_ACTION = re.compile(r"\b(?:irrigat\w*|apply|increase|decrease|stop|start|open|close|run|dose|water|schedule|execute|irriguer|appliquer|regar|aplicar|irrigar|parar)\b", re.IGNORECASE)
_STOP = {"the", "and", "that", "this", "with", "from", "your", "you", "for", "are", "les", "des", "une", "dans", "pour", "avec", "los", "las", "una", "para", "con", "por"}


def _norm_number(value: str) -> str:
    try:
        text = format(Decimal(value.replace(",", ".")).normalize(), "f")
    except InvalidOperation:
        return value
    return text.rstrip("0").rstrip(".") if "." in text else text


def _numbers(text: str) -> set[str]:
    return {_norm_number(match.group(0)) for match in _NUM.finditer(text or "")}


def _tokens(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text or "") if word.casefold() not in _STOP}


def _source_text(item: dict[str, Any]) -> str:
    keys = ("title", "summary", "source_excerpt", "filename", "type", "evidence_type", "provider", "units", "value_json", "payload", "metadata_json")
    return " ".join(str(item.get(key)) for key in keys if item.get(key) not in (None, ""))


def _source_id(item: dict[str, Any], index: int) -> str:
    return str(item.get("id") or item.get("source_id") or item.get("filename") or f"context-{index}")


def build_claim_provenance(*, task: str, answer: str, context: Any) -> dict[str, Any]:
    evidence = [item for item in (getattr(context, "evidence", []) or []) if isinstance(item, dict)]
    freshness = evaluate_evidence_freshness(task=task, evidence=evidence)
    fresh_by_id = {str(item["source_id"]): item for item in freshness.get("records", [])}
    sources = []
    for index, item in enumerate(evidence):
        text = _source_text(item)
        sources.append({"id": _source_id(item, index), "item": item, "numbers": _numbers(text), "tokens": _tokens(text)})

    claims = []
    unsupported = 0
    stale_count = 0
    for position, raw in enumerate(_SENTENCE.split(answer or "")):
        claim = raw.strip()
        if not claim:
            continue
        numbers = _numbers(claim)
        tokens = _tokens(claim)
        operational = bool(_ACTION.search(claim))
        links = []
        for source in sources:
            overlap = tokens.intersection(source["tokens"])
            numeric_match = bool(numbers and numbers.issubset(source["numbers"]))
            lexical_match = len(overlap) >= (2 if len(tokens) >= 5 else 1)
            if not numeric_match and not lexical_match:
                continue
            item = source["item"]
            fresh = fresh_by_id.get(source["id"], {})
            reasons = []
            if numeric_match:
                reasons.append("numeric_match")
            if lexical_match:
                reasons.append("term_overlap")
            links.append({
                "source_id": source["id"],
                "source_type": str(item.get("type") or item.get("evidence_type") or item.get("source_type") or "unknown"),
                "title": item.get("title"),
                "citation_label": item.get("citation_label"),
                "observed_at": fresh.get("observed_at"),
                "freshness_status": fresh.get("status"),
                "support_reasons": reasons,
            })
        links = links[:8]
        considered = [link for link in links if link.get("freshness_status") != "not_required"]
        stale_support = bool(considered) and all(link.get("freshness_status") in {"stale", "unknown"} for link in considered)
        numeric_supported = not numbers or any(numbers.issubset(source["numbers"]) for source in sources if any(link["source_id"] == source["id"] for link in links))
        if not links:
            status = "unsupported" if (numbers or operational) else "narrative_unverified"
        elif not numeric_supported:
            status = "partially_supported"
        elif stale_support and operational:
            status = "stale_support"
        else:
            status = "supported"
        if status in {"unsupported", "partially_supported"} and (operational or numbers):
            unsupported += 1
        if status == "stale_support" and operational:
            stale_count += 1
        claims.append({
            "claim_id": hashlib.sha256(f"{position}|{claim}".encode("utf-8")).hexdigest()[:16],
            "claim": claim,
            "operational": operational,
            "numeric_values": sorted(numbers),
            "status": status,
            "evidence_links": links,
            "stale_support": stale_support,
        })
    return {"claims": claims[:40], "unsupported_consequential_count": unsupported, "stale_operational_count": stale_count, "freshness": freshness}
