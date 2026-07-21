#!/usr/bin/env python3
"""
Truthfulness + quality gate for the AGRO-AI developer platform (private beta).

Standard-library only. Beyond structure/accessibility/links, it enforces the
commercial-truthfulness and contract-fidelity rules that the earlier draft
violated:

  * No invented key prefixes. Only agro_test_ / agro_live_ may appear;
    sk_test_ / sk_live_ (and similar) are rejected.
  * No un-gated commercial claims: uptime %, SLA, SOC 2, latency numbers,
    "no credit card", hardcoded prices. Pricing is runtime-gated only.
  * Every /v1/platform/... path referenced in the pages must exist in the
    curated contract snapshot (plus a small allowlist of runtime-gated probes).
  * Localization is complete: every data-i18n key exists in every locale.

Run from the repository root:
    python3 platform-api/tests/validate_platform.py
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]     # platform-api/
REPO = ROOT.parent
CONTRACT = ROOT / "contract" / "platform_api_openapi.json"
FAILURES: list[str] = []
CHECKS = 0


def fail(m): FAILURES.append(m)
def check(cond, m):
    global CHECKS
    CHECKS += 1
    if not cond:
        fail(m)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.title = ""
        self._t = False
        self.viewport = self.desc = self.lang = self.skip = False
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.i18n_keys: set[str] = set()
        self.img_no_alt = 0
        self.icon_btn_unlabelled = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html" and a.get("lang"):
            self.lang = True
        if tag == "title":
            self._t = True
        if tag == "h1":
            self.h1 += 1
        if tag == "meta":
            if a.get("name") == "viewport":
                self.viewport = True
            if a.get("name") == "description" and a.get("content"):
                self.desc = True
        if a.get("id"):
            self.ids.add(a["id"])
        if a.get("data-i18n"):
            self.i18n_keys.add(a["data-i18n"])
        if tag == "a":
            if "skip-link" in a.get("class", ""):
                self.skip = True
            if a.get("href"):
                self.links.append(a["href"])
        if tag == "img" and "alt" not in a:
            self.img_no_alt += 1
        if tag == "button" and "theme-toggle" in a.get("class", "") and not (a.get("aria-label") or a.get("title")):
            self.icon_btn_unlabelled += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._t = False

    def handle_data(self, data):
        if self._t:
            self.title += data


def is_external(h): return h.startswith(("http://", "https://", "mailto:", "tel:", "//"))


def resolve_local(href, page):
    p = href.split("#", 1)[0].split("?", 1)[0]
    if not p:
        return page
    t = (REPO / p.lstrip("/")) if p.startswith("/") else (page.parent / p)
    t = t.resolve()
    if t.is_dir():
        t = t / "index.html"
    return t


def validate_page(page):
    html = page.read_text(encoding="utf-8")
    p = PageParser(); p.feed(html)
    rel = page.relative_to(REPO)
    # Pages marked data-dynamic render their headings/anchors from the contract
    # at runtime; skip static anchor-existence checks for those.
    dynamic = "data-dynamic" in html
    check(p.lang, f"{rel}: <html> missing lang")
    check(bool(p.title.strip()), f"{rel}: missing <title>")
    check(p.viewport, f"{rel}: missing viewport meta")
    check(p.desc, f"{rel}: missing meta description")
    check(p.h1 == 1, f"{rel}: expected exactly one <h1>, found {p.h1}")
    check(p.skip, f"{rel}: missing skip link")
    check(p.img_no_alt == 0, f"{rel}: {p.img_no_alt} <img> without alt")
    check(p.icon_btn_unlabelled == 0, f"{rel}: icon-only button without label")
    for href in p.links:
        if is_external(href):
            continue
        t = resolve_local(href, page)
        if t and not t.exists():
            fail(f"{rel}: broken link -> {href}")
        if not dynamic and href.startswith("#") and href[1:] and href[1:] not in p.ids:
            fail(f"{rel}: dangling anchor {href}")


# ---- truthfulness scans ----
# Applied to all page/style/script files.
FORBIDDEN = [
    (re.compile(r"\bsk_(test|live)_"), "invented key prefix sk_*; use agro_test_/agro_live_"),
    (re.compile(r"\b99\.9\d*\s*%"), "uptime percentage claim"),
    (re.compile(r"\bSOC\s?-?\s?2\b", re.I), "SOC 2 claim"),
    (re.compile(r"\bSLA\b"), "SLA claim"),
    (re.compile(r"<\s?\d+\s?ms|\d+\s?ms\s+median", re.I), "latency claim"),
    (re.compile(r"no (credit )?card", re.I), "no-credit-card claim"),
]
# Prices are only meaningful as visible claims in rendered HTML text, and only
# when a currency amount is attached to a billing period. A runtime-gated
# pricing block that formats server-provided numbers is not a static claim.
PRICE_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s*(?:/|per\s)?(?:mo|month|yr|year)\b", re.I)
SECRET_PATTERNS = [
    re.compile(r"agro_live_[A-Za-z0-9]{12,}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
]


def scan_content():
    for f in ROOT.rglob("*"):
        if not f.is_file() or f.suffix not in {".js", ".html", ".css"}:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        rel = f.relative_to(REPO)
        for pat, label in FORBIDDEN:
            for m in pat.finditer(text):
                fail(f"{rel}: forbidden {label}: '{m.group(0).strip()}'")
        if f.suffix == ".html":
            for m in PRICE_RE.finditer(text):
                fail(f"{rel}: forbidden hardcoded price: '{m.group(0).strip()}'")
        for pat in SECRET_PATTERNS:
            for m in pat.finditer(text):
                fail(f"{rel}: possible committed secret: {m.group(0)[:14]}…")


# ---- endpoint fidelity against the contract ----
RUNTIME_GATED_PROBES = {"/v1/platform/pricing"}


def scan_endpoints(contract):
    contract_paths = {"/v1" + p for p in contract.get("paths", {})}
    contract_paths.add("/v1/platform")  # documented base path
    # normalise concrete ids in referenced paths back to templated form
    templ = {}
    for p in contract.get("paths", {}):
        templ["/v1" + p] = re.sub(r"\{[^}]+\}", "{}", "/v1" + p)
    contract_norm = set(templ.values()) | {"/v1/platform"} | RUNTIME_GATED_PROBES
    ref = re.compile(r"/v1/platform[/A-Za-z0-9_{}-]*")
    for f in ROOT.rglob("*"):
        if not f.is_file() or f.suffix not in {".html", ".js"}:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in set(ref.findall(text)):
            path = m.rstrip("/")
            norm = re.sub(r"/(fld_[A-Za-z0-9]+|whk_[A-Za-z0-9]+|[A-Za-z0-9]+_[A-Za-z0-9]{6,})", "/{}", path)
            if path in contract_paths or norm in contract_norm or path in RUNTIME_GATED_PROBES:
                continue
            # tolerate example resource ids under known collections
            base = re.sub(r"/[^/]+$", "", path)
            if base in {p.rsplit('/', 1)[0] for p in contract_paths} and base != "/v1/platform":
                continue
            fail(f"{f.relative_to(REPO)}: references path not in contract: {path}")


# ---- localization completeness ----
def scan_localization():
    index = ROOT / "index.html"
    if not index.exists():
        return
    html = index.read_text(encoding="utf-8")
    m = re.search(r"window\.AGROAI_I18N\s*=\s*(\{.*?\});", html, re.S)
    check(bool(m), "index.html: AGROAI_I18N dictionary not found")
    if not m:
        return
    # Evaluate the JS object literal safely enough via a JSON-ish transform:
    # keys are simple identifiers, values are double-quoted strings.
    raw = m.group(1)
    try:
        # convert `key:` to `"key":`
        jsonish = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', raw)
        data = json.loads(jsonish)
    except Exception as e:
        fail(f"index.html: could not parse i18n dictionary ({e})")
        return
    locales = list(data.keys())
    check("en" in locales, "index.html: i18n missing 'en' locale")
    base = set(data["en"].keys())
    for loc in locales:
        missing = base - set(data[loc].keys())
        extra = set(data[loc].keys()) - base
        check(not missing, f"index.html: locale '{loc}' missing keys: {sorted(missing)}")
        check(not extra, f"index.html: locale '{loc}' has extra keys: {sorted(extra)}")
    p = PageParser(); p.feed(html)
    for k in p.i18n_keys:
        check(k in base, f"index.html: data-i18n key '{k}' not in dictionary")


def main():
    pages = sorted(ROOT.rglob("*.html"))
    check(len(pages) >= 8, f"expected full page set, found {len(pages)}")
    for pg in pages:
        validate_page(pg)
    scan_content()
    check(CONTRACT.exists(), "contract snapshot missing")
    if CONTRACT.exists():
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        scan_endpoints(contract)
    scan_localization()

    print(f"Ran {CHECKS} checks across {len(pages)} pages.")
    if FAILURES:
        print(f"\n{len(FAILURES)} problem(s):")
        for m in FAILURES:
            print(f"  ✗ {m}")
        return 1
    print("All developer-platform truthfulness & quality checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
