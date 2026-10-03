"""Hallucinated machine translation must never be advertised.

Providers that do not know a language loop on a token or return one stock
phrase for unrelated strings; both passed key/placeholder/script checks before
(the first Wolof authoring pass, Somali UI, Amharic and Somali legal pages).
"""
from __future__ import annotations

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from i18n_public_translate import _normalize_markers  # noqa: E402
from i18n_quality import collapsed_values, degenerate, has_placeholder_bracket_residue, quality_errors  # noqa: E402

SOURCE = {f"k{i}": text for i, text in enumerate([
    "Settings", "Billing", "Password", "Continue", "Log out", "Reports", "Create account",
    "Your plan includes 3 users.", "Invite your team", "Connect data", "Open Market Intelligence",
])}


def _lifecycle_ready():
    spec = spec_from_file_location("lifecycle_ready", ROOT / "scripts" / "i18n-lifecycle-catalog-ready.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_token_loops_and_blowups_are_degenerate():
    assert degenerate("Markaas oo" + " mid ka mid ah" * 6, "The decision changed.")
    assert degenerate("AGRO-AI Téléphone : Téléphone : Téléphone : Téléphone : Téléphone :", "Connect a supported system.")
    assert degenerate("x" * 200, "A short sentence of thirty chars")
    assert not degenerate("Ihr Plan umfasst 3 Benutzer.", "Your plan includes 3 users.")


def test_one_stock_phrase_for_unrelated_strings_is_collapsed():
    garbage = {key: "Lees meer »" for key in SOURCE}
    assert collapsed_values(SOURCE, garbage)
    assert any(error.startswith("collapsed_output:wo") for error in quality_errors("wo", SOURCE, garbage))
    healthy = {key: f"t{i}" for i, key in enumerate(SOURCE)}
    assert not collapsed_values(SOURCE, healthy)


def test_every_shipped_lifecycle_catalog_passes_the_strengthened_gate():
    ready = _lifecycle_ready()
    manifest = json.loads((ROOT / "shared" / "supported-locales.json").read_text(encoding="utf-8"))
    failing = [code for code in manifest["targetUiLocales"] if code not in {"auto", "en"} and not ready.ready(code)]
    assert failing == []


def test_advertised_ui_catalogs_have_no_degenerate_or_collapsed_entries():
    manifest = json.loads((ROOT / "shared" / "supported-locales.json").read_text(encoding="utf-8"))
    source = json.loads((ROOT / "shared" / "localization" / "source.json").read_text(encoding="utf-8"))["catalog"]
    failing = {}
    for code in manifest["enabledUiLocales"]:
        if code in {"auto", "en"}:
            continue
        catalog = json.loads((ROOT / "shared" / "localization" / "catalogs" / f"{code}.json").read_text(encoding="utf-8"))["catalog"]
        errors = [e for e in quality_errors(code, source, catalog) if e.startswith(("degenerate_output", "collapsed_output", "placeholder_bracket_residue"))]
        if errors:
            failing[code] = errors
    assert failing == {}


def test_widened_protection_markers_leave_no_bracket_next_to_placeholders():
    # Providers sometimes widen ">>>" to ">>>>"; a 1-3 bracket match left "{price}>" in
    # Punjabi/Gujarati/Tagalog catalogs, which passed the placeholder check.
    assert _normalize_markers("a <<<<AGROAI_KEEP_0001>>>> b") == "a <<<AGROAI_KEEP_0001>>> b"
    assert _normalize_markers("《AGROAI KEEP 0002》》") == "<<<AGROAI_KEEP_0002>>>"
    assert has_placeholder_bracket_residue("ਕੀਮਤ {price}> {currency}", "Price {price} {currency}")
    assert has_placeholder_bracket_residue("<{plan} plano", "{plan} plan")
    assert not has_placeholder_bracket_residue("Step {step} of {total}", "Step {step} of {total}")
    assert not has_placeholder_bracket_residue("<{tag}>", "<{tag}>")
    errors = quality_errors("pa", {"k": "Price {price} {currency}"}, {"k": "ਕੀਮਤ {price}> {currency}"})
    assert any(e.startswith("placeholder_bracket_residue:pa:k") for e in errors)


def test_single_string_requests_need_no_item_delimiter(monkeypatch):
    # Serbian dropped the item delimiter for one sentence, failing the whole
    # locale build after bisection had already isolated that one string.
    import io
    import urllib.parse

    import i18n_public_translate as public

    sent: list[str] = []

    def fake_urlopen(request, timeout=0):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)["q"][0]
        sent.append(query)
        # Echo the request as the "translation", the way a provider preserves markers.
        return io.BytesIO(json.dumps([[[query.replace("Price", "Cena"), query]]]).encode())

    monkeypatch.setattr(public.urllib.request, "urlopen", fake_urlopen)
    single = public._translate_pack("sr", [("k", "Price {price} {currency}.")])
    assert single == {"k": "Cena {price} {currency}."}
    assert "AGROAI_ITEM" not in sent[-1]
    many = public._translate_pack("sr", [("a", "Price {price}."), ("b", "Price now.")])
    assert many == {"a": "Cena {price}.", "b": "Cena now."}
    assert "AGROAI_ITEM_0000" in sent[-1] and "AGROAI_ITEM_0001" in sent[-1]
