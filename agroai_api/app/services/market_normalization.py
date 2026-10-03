"""Normalization for AGRO-AI Commercial Intelligence market evidence.

Upstream market sources publish in many shapes: "€244,36" per TONNES, "2,36"
R$/kg, "Rs./Quintal", "USD/bu", Portuguese and French commodity names, weekly
or monthly periods. Everything that reaches the economics engine or the shared
observation store passes through this module so the rules live in one place.

Rules are deliberately conservative: an unrecognised unit, commodity or price
format returns ``None`` (the caller must keep the evidence out of commercial
calculations) instead of guessing.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

NORMALIZATION_VERSION = "market-normalization-2026.10.1"


def _fold(value: str | None) -> str:
    """Lowercase, strip accents and collapse separators to single spaces."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[_\-/,()]+", " ", text).split())


# ---------------------------------------------------------------------------
# Commodities
# ---------------------------------------------------------------------------

# Canonical commodity id -> (family, aliases in the languages AGRO-AI serves).
_COMMODITIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "soybean": ("oilseeds", ("soybean", "soybeans", "soy", "soya", "soya beans", "soja", "soja em graos", "soja grao", "graines de soja")),
    "corn": ("grains", ("corn", "maize", "yellow corn", "white maize", "milho", "milho em graos", "mais", "maize white", "maiz", "feed maize")),
    "wheat": ("grains", ("wheat", "trigo", "ble", "ble tendre", "milling wheat", "breadmaking common wheat", "feed wheat", "common wheat")),
    "durum_wheat": ("grains", ("durum wheat", "ble dur", "trigo duro")),
    "barley": ("grains", ("barley", "cevada", "orge", "feed barley", "malting barley", "cebada")),
    "sorghum": ("grains", ("sorghum", "sorgo", "milo", "grain sorghum")),
    "oats": ("grains", ("oats", "aveia", "avoine", "feed oats", "avena")),
    "rice": ("grains", ("rice", "arroz", "riz", "paddy", "paddy rice", "arroz em casca", "dhan", "chawal")),
    "rapeseed": ("oilseeds", ("rapeseed", "canola", "colza", "colza graines")),
    "sunflower": ("oilseeds", ("sunflower", "sunflower seed", "girassol", "tournesol", "girasol")),
    "cotton": ("fibre", ("cotton", "algodao", "algodao em pluma", "coton", "algodon")),
    "coffee": ("softs", ("coffee", "cafe", "cafe arabica", "cafe robusta", "cafe conilon", "arabica", "robusta")),
    "cocoa": ("softs", ("cocoa", "cacau", "cacao")),
    "sugar": ("softs", ("sugar", "acucar", "sucre", "azucar")),
    "beans": ("pulses", ("beans", "dry beans", "feijao", "haricots", "frijol")),
    "almonds": ("tree_nuts", ("almond", "almonds", "amendoa", "amandes", "almendra")),
    "walnuts": ("tree_nuts", ("walnut", "walnuts", "noz", "noix")),
    "pistachios": ("tree_nuts", ("pistachio", "pistachios")),
    "groundnuts": ("oilseeds", ("groundnut", "groundnuts", "peanut", "peanuts", "amendoim", "arachide")),
    "onions": ("horticulture", ("onion", "onions", "cebola", "oignon", "cebolla")),
    "tomatoes": ("horticulture", ("tomato", "tomatoes", "tomate", "tomates")),
    "mangoes": ("horticulture", ("mango", "mangoes", "manga", "mangue")),
    "milk": ("dairy", ("milk", "raw milk", "leite", "lait", "leche")),
    "cattle": ("livestock", ("cattle", "beef cattle", "boi", "boi gordo", "bovins", "ganado", "live cattle")),
    "hogs": ("livestock", ("hogs", "pigs", "suinos", "porcs", "lean hogs")),
}
_ALIAS_INDEX: dict[str, str] = {}
for _canonical, (_family, _aliases) in _COMMODITIES.items():
    for _alias in (_canonical, *_aliases):
        _ALIAS_INDEX[_fold(_alias)] = _canonical


def canonical_commodity(value: str | None) -> str | None:
    """Map a customer or provider commodity label to AGRO-AI's canonical id."""
    folded = _fold(value)
    if not folded:
        return None
    if folded in _ALIAS_INDEX:
        return _ALIAS_INDEX[folded]
    # Provider labels often carry grade/class suffixes ("SOJA EM GRAOS",
    # "Maize (white, dry)"). Accept the longest alias that is a whole-word prefix.
    best: tuple[int, str] | None = None
    for alias, canonical in _ALIAS_INDEX.items():
        if folded == alias or folded.startswith(alias + " "):
            if best is None or len(alias) > best[0]:
                best = (len(alias), canonical)
    return best[1] if best else None


def commodity_family(value: str | None) -> str | None:
    canonical = canonical_commodity(value)
    return _COMMODITIES[canonical][0] if canonical else None


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

# Canonical quantity units understood by the economics engine.
_UNIT_ALIASES: dict[str, str] = {
    "kg": "kg", "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kgs": "kg", "quilo": "kg",
    "t": "tonne", "mt": "tonne", "ton metric": "tonne", "tonne": "tonne", "tonnes": "tonne", "metric ton": "tonne",
    "metric tonne": "tonne", "metric tons": "tonne", "metric tonnes": "tonne", "tons": "tonne", "ton": "tonne",
    "tonelada": "tonne", "toneladas": "tonne",
    "lb": "pound", "lbs": "pound", "pound": "pound", "pounds": "pound",
    "bu": "bushel", "bushel": "bushel", "bushels": "bushel",
    "quintal": "quintal", "quintals": "quintal", "qtl": "quintal", "qtls": "quintal",
    "cwt": "cwt", "hundredweight": "cwt",
    "short ton": "short_ton", "short tons": "short_ton",
    "long ton": "long_ton", "long tons": "long_ton",
    "saca": "saca_60kg", "sacas": "saca_60kg", "saca 60kg": "saca_60kg", "saca de 60 kg": "saca_60kg", "60 kg": "saca_60kg",
    "sack 60kg": "saca_60kg", "bag 60kg": "saca_60kg",
    "90 kg": "bag_90kg", "bag 90kg": "bag_90kg", "90kg": "bag_90kg",
    "50 kg": "bag_50kg", "bag 50kg": "bag_50kg", "50kg": "bag_50kg",
}


def canonical_unit(value: str | None) -> str | None:
    folded = _fold(value)
    if not folded:
        return None
    return _UNIT_ALIASES.get(folded)


_PRICE_UNIT_SPLIT = re.compile(r"\s*(?:/|\bper\b)\s*", re.IGNORECASE)
_CURRENCY_TOKENS: dict[str, str] = {
    "$": "USD", "us$": "USD", "usd": "USD", "r$": "BRL", "brl": "BRL", "€": "EUR", "eur": "EUR",
    "rs": "INR", "rs.": "INR", "inr": "INR", "₹": "INR", "a$": "AUD", "aud": "AUD", "ksh": "KES", "kes": "KES",
    "cfa": "XOF", "fcfa": "XOF", "xof": "XOF", "£": "GBP", "gbp": "GBP", "cad": "CAD", "c$": "CAD",
}


@dataclass(frozen=True)
class PriceUnit:
    currency: str | None
    quantity_unit: str


def parse_price_unit(value: str | None, *, default_currency: str | None = None) -> PriceUnit | None:
    """Parse "USD/bu", "Rs./Quintal", "national currency/ton", "TONNES", "R$/kg".

    A bare quantity unit ("TONNES") is accepted with ``default_currency`` only
    when the caller knows the publication currency. Unknown quantity units
    return None so the price is never silently promoted.
    """
    text = str(value or "").strip()
    if not text:
        return None
    parts = _PRICE_UNIT_SPLIT.split(text, maxsplit=1)
    if len(parts) == 2:
        currency_text, quantity_text = parts
        token = currency_text.strip().lower()
        currency = _CURRENCY_TOKENS.get(token)
        if currency is None and token in {"national currency", "local currency"}:
            currency = default_currency
        if currency is None and len(token) == 3 and token.isalpha():
            currency = token.upper()
    else:
        currency, quantity_text = default_currency, parts[0]
    quantity = canonical_unit(quantity_text)
    if quantity is None:
        return None
    return PriceUnit(currency=currency.upper() if currency else None, quantity_unit=quantity)


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile("[-+]?\\d(?:[\\d.,\\s\u00a0\u202f]*\\d)?")


def parse_decimal(value: object, *, decimal_comma: bool | None = None) -> Decimal | None:
    """Parse provider numbers including "€244,36", "1.234,56", "1,234.56", "2,36".

    ``decimal_comma`` forces the convention when the source documents it
    (e.g. CONAB publishes "2,36"). Without it, the rightmost separator followed
    by one or two digits is treated as the decimal separator; an ambiguous
    "1,234" or "1.234" with exactly three trailing digits is rejected.
    """
    if value is None:
        return None
    if isinstance(value, (int, Decimal)):
        result = Decimal(value)
        return result if result.is_finite() else None
    if isinstance(value, float):
        result = Decimal(str(value))
        return result if result.is_finite() else None
    match = _NUMBER_RE.search(str(value))
    if not match:
        return None
    raw = re.sub(r"[\s  ]", "", match.group(0))
    sign = ""
    if raw[0] in "+-":
        sign, raw = raw[0], raw[1:]
    if decimal_comma is True:
        normalized = raw.replace(".", "").replace(",", ".")
    elif decimal_comma is False:
        normalized = raw.replace(",", "")
    else:
        last_comma, last_dot = raw.rfind(","), raw.rfind(".")
        separator_index = max(last_comma, last_dot)
        if separator_index == -1:
            normalized = raw
        else:
            decimals = raw[separator_index + 1:]
            only_one_kind = (last_comma == -1) or (last_dot == -1)
            occurrences = raw.count(raw[separator_index])
            if only_one_kind and occurrences == 1 and len(decimals) == 3:
                return None  # "1,234" vs "1.234": refuse to guess
            if only_one_kind and occurrences > 1:
                normalized = raw.replace(raw[separator_index], "")
            else:
                integer = re.sub(r"[.,]", "", raw[:separator_index])
                normalized = f"{integer}.{decimals}"
    try:
        result = Decimal(sign + normalized)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------

# ISO-3166 alpha-2 -> (default currency, IANA timezone used for market dates).
COUNTRY_DEFAULTS: dict[str, tuple[str, str]] = {
    "US": ("USD", "America/Chicago"), "BR": ("BRL", "America/Sao_Paulo"), "AR": ("ARS", "America/Argentina/Buenos_Aires"),
    "CA": ("CAD", "America/Toronto"), "MX": ("MXN", "America/Mexico_City"), "FR": ("EUR", "Europe/Paris"),
    "DE": ("EUR", "Europe/Berlin"), "ES": ("EUR", "Europe/Madrid"), "IT": ("EUR", "Europe/Rome"),
    "PT": ("EUR", "Europe/Lisbon"), "NL": ("EUR", "Europe/Amsterdam"), "BE": ("EUR", "Europe/Brussels"),
    "PL": ("PLN", "Europe/Warsaw"), "RO": ("RON", "Europe/Bucharest"), "HU": ("HUF", "Europe/Budapest"),
    "GB": ("GBP", "Europe/London"), "UA": ("UAH", "Europe/Kyiv"), "AU": ("AUD", "Australia/Sydney"),
    "NZ": ("NZD", "Pacific/Auckland"), "IN": ("INR", "Asia/Kolkata"), "CN": ("CNY", "Asia/Shanghai"),
    "ID": ("IDR", "Asia/Jakarta"), "TH": ("THB", "Asia/Bangkok"), "VN": ("VND", "Asia/Ho_Chi_Minh"),
    "KE": ("KES", "Africa/Nairobi"), "SN": ("XOF", "Africa/Dakar"), "CI": ("XOF", "Africa/Abidjan"),
    "ML": ("XOF", "Africa/Bamako"), "BF": ("XOF", "Africa/Ouagadougou"), "CM": ("XAF", "Africa/Douala"),
    "NG": ("NGN", "Africa/Lagos"), "GH": ("GHS", "Africa/Accra"), "ET": ("ETB", "Africa/Addis_Ababa"),
    "TZ": ("TZS", "Africa/Dar_es_Salaam"), "UG": ("UGX", "Africa/Kampala"), "ZA": ("ZAR", "Africa/Johannesburg"),
    "MA": ("MAD", "Africa/Casablanca"), "EG": ("EGP", "Africa/Cairo"), "CO": ("COP", "America/Bogota"),
    "PE": ("PEN", "America/Lima"), "CL": ("CLP", "America/Santiago"), "PY": ("PYG", "America/Asuncion"),
    "UY": ("UYU", "America/Montevideo"),
}

# Currencies whose value is fixed by treaty against EUR (CFA francs). These are
# legal parities, not market quotes; AGRO-AI derives them exactly.
EUR_FIXED_PARITIES: dict[str, Decimal] = {"XOF": Decimal("655.957"), "XAF": Decimal("655.957")}

# Brazilian state names -> UF codes used by CONAB.
BR_STATE_CODES: dict[str, str] = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA", "mato grosso": "MT",
    "mato grosso do sul": "MS", "minas gerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR",
    "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}


def country_default_currency(country_code: str | None) -> str | None:
    entry = COUNTRY_DEFAULTS.get(str(country_code or "").upper())
    return entry[0] if entry else None


def country_timezone(country_code: str | None) -> str:
    entry = COUNTRY_DEFAULTS.get(str(country_code or "").upper())
    return entry[1] if entry else "UTC"


def brazil_state_code(region: str | None) -> str | None:
    folded = _fold(region)
    if not folded:
        return None
    if len(folded) == 2 and folded.upper() in BR_STATE_CODES.values():
        return folded.upper()
    return BR_STATE_CODES.get(folded)


def fold(value: str | None) -> str:
    """Public accent/case-insensitive folding for provider label matching."""
    return _fold(value)
