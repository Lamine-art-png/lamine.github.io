"""Ask AGRO-AI for Commercial Intelligence.

The assistant answers from the organization's structured commercial position,
never as a generic commodity chatbot:

- "What happens if soybean prices fall another 8%?", "What if BRL strengthens
  5%?", "What if yield drops 7%?", "Show me selling another 10%, 25% and 40%"
  are parsed deterministically (English, Portuguese, Spanish, French) into
  scenario levers and computed by the deterministic scenario engine;
- results become evidence ids the model must cite exactly (numeric grounding
  rejects anything else) and the deterministic fallback states them directly;
- open material changes, data freshness, provenance and saved scenarios are
  supplied as facts so "what changed", "which number is stale" and "where did
  this price come from" are answered from records, not invented.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.services.market_intelligence import MarketCalculationError, scenario_position

_PERCENT = re.compile(r"([-+−]?\d{1,3}(?:[.,]\d{1,2})?)\s?%")
_LEVER_WORDS: dict[str, tuple[str, ...]] = {
    "sell_pct_now": ("sell", "selling", "sold", "commit", "contract another", "vender", "vendo", "vendre", "vendiendo", "comprometer", "engager"),
    "yield_pct": ("yield", "production", "harvest", "crop size", "produtividade", "produção", "producao", "rendimento", "safra", "rendement", "récolte", "rendimiento", "cosecha", "producción"),
    "fx_pct": ("fx", "exchange rate", "currency", "dollar", "real", "brl", "usd", "eur", "euro", "aud", "inr", "kes", "câmbio", "cambio", "devise", "taux de change", "tipo de cambio", "strengthen", "weaken", "fortalece", "enfraquece", "s'apprécie", "se déprécie"),
    "production_cost_pct": ("cost", "costs", "custo", "custos", "coût", "coûts", "costo", "costos", "input"),
    "price_pct": ("price", "prices", "preço", "preços", "preco", "precos", "prix", "precio", "precios", "market", "mercado", "marché"),
}
_DOWN = ("fall", "falls", "drop", "drops", "decline", "lower", "decrease", "down", "weaken", "weakens", "cai", "caem", "cair", "queda",
         "recua", "baixa", "menor", "enfraquece", "baisse", "chute", "diminue", "se déprécie", "baja", "cae", "caen", "bajan", "desciende", "debilita")
_UP = ("rise", "rises", "increase", "higher", "up", "strengthen", "strengthens", "sobe", "sobem", "alta", "aumenta", "fortalece",
       "hausse", "augmente", "s'apprécie", "sube", "suben", "aumentan")
_LANGUAGE_REQUESTS = {
    "pt": ("in portuguese", "em português", "em portugues", "en portugués", "en portugais"),
    "es": ("in spanish", "en español", "en espanol", "em espanhol", "en espagnol"),
    "fr": ("in french", "en français", "en francais", "em francês", "en francés"),
    "en": ("in english", "em inglês", "en anglais", "en inglés"),
}
_CURRENCY = re.compile(r"\b([A-Z]{3})\b")


# Free-text what-if phrasing is understood in these languages; in any other
# advertised locale the response says so explicitly and the portal points to
# the structured What-if panel, which works identically in every locale.
SCENARIO_PARSE_LANGUAGES = ("en", "pt", "es", "fr")


def scenario_parse_status(question: str, language: str, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    root = str(language or "en").strip().lower().split("-")[0]
    if scenarios:
        status = "parsed"
    elif not _PERCENT.search(question or ""):
        status = "not_requested"
    elif root not in SCENARIO_PARSE_LANGUAGES:
        status = "unsupported_language"
    else:
        status = "not_understood"
    return {"status": status, "language": root, "supported_languages": list(SCENARIO_PARSE_LANGUAGES)}


def requested_language(question: str) -> str | None:
    text = question.lower()
    for language, phrases in _LANGUAGE_REQUESTS.items():
        if any(phrase in text for phrase in phrases):
            return language
    return None


def _clause_lever(clause: str) -> str | None:
    text = f" {clause.lower()} "
    for lever, words in _LEVER_WORDS.items():
        if any(re.search(rf"(?<![a-zà-ÿ]){re.escape(word)}(?![a-zà-ÿ])", text) for word in words):
            return lever
    return None


def _direction(clause: str) -> int:
    text = clause.lower()
    if any(re.search(rf"(?<![a-zà-ÿ]){re.escape(w)}(?![a-zà-ÿ])", text) for w in _DOWN):
        return -1
    if any(re.search(rf"(?<![a-zà-ÿ]){re.escape(w)}(?![a-zà-ÿ])", text) for w in _UP):
        return 1
    return 0


_CLAUSE_BREAK = re.compile(r"(?:[;?!.]|\s(?:and|e|et|y|but|mas|mais|pero|while)\s)", re.IGNORECASE)


def parse_scenario_intents(question: str, position: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic what-if extraction. Returns labelled lever sets (max 6).

    Each percentage takes its lever and direction from the words that lead up
    to it (since the previous percentage), so "prices fall 8% and BRL
    strengthens 5%" yields a price scenario and an FX scenario. A percentage
    with no lever words inherits the previous lever and direction ("selling
    another 10%, 25% and 40%"). Only explicit percentages are used; a question
    without a number produces no scenario rather than an invented magnitude.
    """
    text = str(question or "")
    matches = list(_PERCENT.finditer(text))
    if not matches:
        return []
    reporting = str(position.get("reporting_currency") or "").upper()
    price_currency = str(position.get("price_currency") or position.get("reporting_currency") or "").upper()
    scenarios: list[dict[str, Any]] = []
    previous_end = 0
    current_lever: str | None = None
    current_direction = 0
    for index, match in enumerate(matches):
        lead = text[previous_end:match.start()]
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        tail_text = text[match.end():next_start]
        breaker = _CLAUSE_BREAK.search(tail_text)
        tail = tail_text[: breaker.start()] if breaker else tail_text[:30]
        previous_end = match.end()
        lever = _clause_lever(lead) or _clause_lever(tail) or current_lever
        if lever is None:
            continue
        if lever != current_lever:
            current_direction = 0
        current_lever = lever
        raw = match.group(1).replace("−", "-").replace(",", ".")
        value = Decimal(raw)
        explicit_sign = raw.startswith(("-", "+"))
        if lever == "sell_pct_now":
            magnitude = abs(value)
            if magnitude <= 0 or magnitude > 100:
                continue
            scenarios.append({"label": f"commit {magnitude}% more", "sell_pct_now": str(magnitude)})
            continue
        direction = (1 if value > 0 else -1) if explicit_sign else (_direction(lead) or _direction(tail) or current_direction)
        if direction == 0:
            continue
        current_direction = direction
        magnitude = abs(value)
        if lever == "fx_pct":
            mentioned = {code for code in _CURRENCY.findall((lead + tail).upper()) if code in {reporting, price_currency}}
            sign = direction
            if mentioned == {reporting} and reporting != price_currency:
                sign = -direction  # reporting currency strengthening = fewer reporting units per source unit
            scenarios.append({"label": f"FX {'+' if sign > 0 else '-'}{magnitude}%", "fx_pct": str(sign * magnitude)})
        else:
            scenarios.append({"label": f"{lever.removesuffix('_pct')} {'+' if direction > 0 else '-'}{magnitude}%", lever: str(direction * magnitude)})
    return scenarios[:6]


def scenario_evidence(position_row: Any, contracts: list[Any], intents: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Run intents through the deterministic engine; return results and evidence ids."""
    results: list[dict[str, Any]] = []
    evidence: dict[str, str] = {}
    for index, intent in enumerate(intents, start=1):
        assumptions = {k: v for k, v in intent.items() if k != "label"}
        try:
            outcome = scenario_position(position_row, contracts, assumptions)
        except MarketCalculationError as exc:
            results.append({"label": intent["label"], "status": "invalid", "message": str(exc)})
            continue
        prefix = f"scenario_{index}"
        summary = {"label": intent["label"], "status": "ok", "assumptions": outcome["assumptions"], "evidence_prefix": prefix}
        for key in ("projected_margin", "exposed_revenue", "locked_revenue", "projected_revenue", "contracted_percent"):
            value = outcome["result"].get(key)
            change = outcome["delta"].get(key)
            if value is not None:
                evidence[f"{prefix}.{key}"] = str(value)
                summary[key] = value
            if change is not None:
                evidence[f"{prefix}.delta_{key}"] = str(change)
                summary[f"delta_{key}"] = change
        results.append(summary)
    return results, evidence


_TEMPLATES = {
    "en": {
        "scenario": "Scenario {label}: projected margin {margin} {ccy} ({delta} {ccy} versus today); exposed revenue {exposed} {ccy}.",
        "scenario_no_margin": "Scenario {label}: exposed revenue {exposed} {ccy} ({delta} {ccy} versus today); margin is unavailable until inputs are complete.",
        "stale": "Evidence needing attention: {items}.",
        "change": "Open material change: {level} on {position}.",
        "source": "Current price source: {source} ({state}, observed {observed}).",
        "not_forecast": "Scenarios are deterministic what-ifs, not forecasts.",
    },
    "pt": {
        "scenario": "Cenário {label}: margem projetada {margin} {ccy} ({delta} {ccy} em relação a hoje); receita exposta {exposed} {ccy}.",
        "scenario_no_margin": "Cenário {label}: receita exposta {exposed} {ccy} ({delta} {ccy} em relação a hoje); a margem fica indisponível até os dados estarem completos.",
        "stale": "Evidências que precisam de atenção: {items}.",
        "change": "Mudança material em aberto: {level} em {position}.",
        "source": "Fonte do preço atual: {source} ({state}, observado em {observed}).",
        "not_forecast": "Cenários são simulações determinísticas, não previsões.",
    },
    "es": {
        "scenario": "Escenario {label}: margen proyectado {margin} {ccy} ({delta} {ccy} frente a hoy); ingreso expuesto {exposed} {ccy}.",
        "scenario_no_margin": "Escenario {label}: ingreso expuesto {exposed} {ccy} ({delta} {ccy} frente a hoy); el margen no está disponible hasta completar los datos.",
        "stale": "Evidencia que requiere atención: {items}.",
        "change": "Cambio material abierto: {level} en {position}.",
        "source": "Fuente del precio actual: {source} ({state}, observado {observed}).",
        "not_forecast": "Los escenarios son simulaciones deterministas, no pronósticos.",
    },
    "fr": {
        "scenario": "Scénario {label} : marge projetée {margin} {ccy} ({delta} {ccy} par rapport à aujourd'hui) ; revenu exposé {exposed} {ccy}.",
        "scenario_no_margin": "Scénario {label} : revenu exposé {exposed} {ccy} ({delta} {ccy} par rapport à aujourd'hui) ; la marge reste indisponible tant que les données sont incomplètes.",
        "stale": "Éléments à vérifier : {items}.",
        "change": "Changement significatif ouvert : {level} sur {position}.",
        "source": "Source du prix actuel : {source} ({state}, observé le {observed}).",
        "not_forecast": "Les scénarios sont des simulations déterministes, pas des prévisions.",
    },
}


_LEVER_LABELS = {
    "en": {"price_pct": "price", "yield_pct": "yield", "fx_pct": "FX", "production_cost_pct": "costs", "sell_pct_now": "commit more volume"},
    "pt": {"price_pct": "preço", "yield_pct": "produtividade", "fx_pct": "câmbio", "production_cost_pct": "custos", "sell_pct_now": "comprometer mais volume"},
    "es": {"price_pct": "precio", "yield_pct": "rendimiento", "fx_pct": "tipo de cambio", "production_cost_pct": "costos", "sell_pct_now": "comprometer más volumen"},
    "fr": {"price_pct": "prix", "yield_pct": "rendement", "fx_pct": "change", "production_cost_pct": "coûts", "sell_pct_now": "engager plus de volume"},
}


def scenario_label(assumptions: dict[str, Any], language: str) -> str:
    """Localized label built from the scenario's own deterministic assumptions."""
    names = _LEVER_LABELS.get(language, _LEVER_LABELS["en"])
    parts = []
    for lever, name in names.items():
        raw = assumptions.get(lever)
        if raw in (None, "", "0"):
            continue
        value = Decimal(str(raw))
        if value == 0:
            continue
        sign = "" if lever == "sell_pct_now" else ("+" if value > 0 else "")
        parts.append(f"{name} {sign}{value.normalize():f}%")
    return ", ".join(parts) or "—"


def deterministic_context_facts(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Language-neutral facts behind the deterministic answer.

    Every advertised portal locale renders these codes with its own catalog;
    numbers come straight from deterministic results, no model involved.
    """
    ccy = str(context.get("reporting_currency") or "")
    facts: list[dict[str, Any]] = []
    for item in context.get("scenarios") or []:
        if item.get("status") != "ok":
            continue
        assumptions = {k: str(v) for k, v in (item.get("assumptions") or {}).items() if v not in (None, "", "0")}
        if item.get("projected_margin") is not None:
            facts.append({"code": "scenario", "params": {"assumptions": assumptions, "projected_margin": str(item["projected_margin"]),
                                                         "delta": str(item.get("delta_projected_margin") or "0.00"),
                                                         "exposed_revenue": str(item.get("exposed_revenue")) if item.get("exposed_revenue") is not None else None,
                                                         "currency": ccy}})
        else:
            facts.append({"code": "scenario_no_margin", "params": {"assumptions": assumptions,
                                                                   "exposed_revenue": str(item.get("exposed_revenue")) if item.get("exposed_revenue") is not None else None,
                                                                   "delta": str(item.get("delta_exposed_revenue") or "0.00"), "currency": ccy}})
    if context.get("scenarios"):
        facts.append({"code": "not_forecast", "params": {}})
    stale = [{"evidence": item["evidence"], "state": item["state"]} for item in context.get("data_states") or [] if item.get("state") in {"STALE", "UNAVAILABLE", "SELECTION_REQUIRED"}]
    if stale:
        facts.append({"code": "stale", "params": {"items": stale}})
    for event in (context.get("material_changes") or [])[:2]:
        facts.append({"code": "change", "params": {"level": event.get("level"), "position": event.get("position_name") or event.get("position_id")}})
    source = context.get("price_source")
    if source and (source.get("provider") or source.get("source_name")):
        facts.append({"code": "source", "params": {"provider": source.get("provider"), "source_name": source.get("source_name"),
                                                   "state": source.get("state"), "observed": (source.get("observed_at") or "")[:10]}})
    return facts


def _evidence_label(key: str) -> str:
    return key.replace("contract_fx:", "contract FX ") if key.startswith("contract_fx:") else key


def deterministic_context_lines(context: dict[str, Any], language: str) -> list[str]:
    """Server-rendered text for the languages with reviewed templates (en, pt, es, fr)."""
    copy = _TEMPLATES.get(language, _TEMPLATES["en"])
    lines: list[str] = []
    for fact in deterministic_context_facts(context):
        params = fact["params"]
        if fact["code"] == "scenario":
            lines.append(copy["scenario"].format(label=scenario_label(params["assumptions"], language), margin=params["projected_margin"],
                                                 ccy=params["currency"], delta=params["delta"], exposed=params.get("exposed_revenue") or "-"))
        elif fact["code"] == "scenario_no_margin":
            lines.append(copy["scenario_no_margin"].format(label=scenario_label(params["assumptions"], language), exposed=params.get("exposed_revenue") or "-",
                                                           ccy=params["currency"], delta=params["delta"]))
        elif fact["code"] == "not_forecast":
            lines.append(copy["not_forecast"])
        elif fact["code"] == "stale":
            lines.append(copy["stale"].format(items=", ".join(f"{_evidence_label(item['evidence'])}={item['state']}" for item in params["items"])))
        elif fact["code"] == "change":
            lines.append(copy["change"].format(level=params["level"], position=params["position"]))
        elif fact["code"] == "source" and params.get("source_name"):
            lines.append(copy["source"].format(source=params["source_name"], state=params.get("state"), observed=params.get("observed") or ""))
    return lines
