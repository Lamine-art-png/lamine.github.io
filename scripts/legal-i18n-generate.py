#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
from pathlib import Path
import re
import time
import urllib.request
from i18n_public_translate import translate_catalog as public_translate_catalog
from i18n_quality import degenerate, has_marker_residue

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "http://127.0.0.1:8787/api/chat"
DOCS = {
    "terms-of-service": "https://agroai-pilot.com/terms-of-service",
    "privacy-policy": "https://agroai-pilot.com/privacy-policy",
}
TOKEN_RE = re.compile(r"(?is)(<!--.*?-->|<script\b.*?</script\s*>|<style\b.*?</style\s*>|<[^>]+>)")
WORD_RE = re.compile(r"[A-Za-z]{2,}")
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
# Navigation labels injected by platform-api/trust/legal-integration.js. They are
# translated with the snapshot and embedded in it, so the chrome around a
# localized legal document is in the same language as the document.
LEGAL_CHROME = {
    "trustLegal": "AGRO-AI Trust & Legal",
    "trustLegalAria": "AGRO-AI Trust and Legal",
    "description": "Contractual documents and the standards that explain how AGRO-AI governs agricultural, operational and personal data.",
    "trustData": "Trust & data governance",
    "trustCenter": "Trust Center",
    "dataGovernance": "Data Governance",
    "aiData": "AI & Model Data Use",
    "security": "Security",
    "legalDocuments": "Legal documents",
    "terms": "Terms of Service",
    "privacy": "Privacy Policy",
    "pilot": "Pilot Agreement",
    "footer": "Trust & Legal",
}
MAX_KEYS = 10


def canonical_legal_versions() -> dict[str, str]:
    """The legal version identifiers recorded at clickwrap acceptance."""
    auth = (ROOT / "agroai_api/app/api/v1/auth.py").read_text(encoding="utf-8")
    versions = {}
    for slug, name in (("terms-of-service", "SELF_SERVICE_TERMS_VERSION"), ("privacy-policy", "SELF_SERVICE_PRIVACY_VERSION")):
        match = re.search(rf'^{name}\s*=\s*"([^"]+)"', auth, flags=re.M)
        if not match:
            raise RuntimeError(f"canonical_legal_version_missing:{name}")
        versions[slug] = match.group(1)
    return versions
MAX_CHARS = 1200
ATTEMPTS = 4

def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "Accept": "text/html,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 AGRO-AI-Legal-Localization-Release/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="strict")

def split_visible_text(raw: str):
    tokens = TOKEN_RE.split(raw)
    source = {}
    locations = {}
    seq = 0
    for index, token in enumerate(tokens):
        if not token or token.startswith("<"):
            continue
        decoded = html.unescape(token)
        stripped = decoded.strip()
        if not stripped or not WORD_RE.search(stripped):
            continue
        seq += 1
        key = f"legal.{seq:04d}"
        source[key] = stripped
        locations[key] = (index, decoded[:len(decoded)-len(decoded.lstrip())], decoded[len(decoded.rstrip()):])
    return tokens, source, locations

def clean_object(raw: str):
    value = raw.strip()
    value = re.sub(r"^\`\`\`(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*\`\`\`$", "", value).strip()
    start, end = value.find("{"), value.rfind("}")
    if start >= 0 and end > start:
        value = value[start:end+1]
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(value)
    if not isinstance(parsed, dict):
        raise ValueError("legal_translation_not_object")
    return parsed

def validate(source, candidate):
    if set(source) != set(candidate):
        raise ValueError("legal_translation_key_mismatch")
    out = {}
    for key, original in source.items():
        value = candidate.get(key)
        if not isinstance(value, str) or not value.strip() or value.strip().lower() == "[object object]":
            raise ValueError(f"legal_invalid_value:{key}")
        value = value.strip()
        if sorted(PLACEHOLDER_RE.findall(original)) != sorted(PLACEHOLDER_RE.findall(value)):
            raise ValueError(f"legal_placeholder_mismatch:{key}")
        if has_marker_residue(value) and not has_marker_residue(original):
            raise ValueError(f"legal_marker_residue:{key}")
        if degenerate(value, original):
            raise ValueError(f"legal_degenerate_output:{key}")
        out[key] = value
    return out

def call(locale, source, endpoint):
    prompt = (
        f"Translate every JSON string value into the requested locale ({locale}). This is a faithful presentation translation of an existing "
        "AGRO-AI legal document, not new legal drafting. Preserve legal meaning, defined terms, company/product names, "
        "URLs, email addresses, numbers, section numbering and placeholders exactly. For pt-BR use natural Brazilian "
        "Portuguese legal/business language. Return one object with exactly the same keys and no explanation."
    )
    body = {
        "model": "legal-localization-authoring",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "QUESTION: " + json.dumps(source, ensure_ascii=False, separators=(",", ":"))},
        ],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 1500},
    }
    last = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            try:
                return validate(source, public_translate_catalog(locale, source))
            except Exception as public_exc:
                last = public_exc
            req = urllib.request.Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode(), headers={
                "content-type": "application/json",
                "accept": "application/json",
                "user-agent": "Mozilla/5.0 AGRO-AI-Legal-Localization-Release/1.0",
            })
            with urllib.request.urlopen(req, timeout=55) as response:
                payload = json.load(response)
            raw = payload.get("message", {}).get("content") or payload.get("response") or ""
            if payload.get("done") is not True or not isinstance(raw, str) or not raw.strip():
                raise ValueError("legal_authoring_invalid_response")
            return validate(source, clean_object(raw))
        except Exception as exc:
            last = exc
            if attempt < ATTEMPTS:
                time.sleep(attempt * 1.2)
    raise RuntimeError(f"legal_chunk_failed:{locale}:{type(last).__name__}:{str(last)[:300]}")

def resilient(locale, source, endpoint):
    try:
        return call(locale, source, endpoint)
    except RuntimeError:
        if len(source) <= 1:
            raise
        items = list(source.items())
        mid = max(1, len(items)//2)
        out = {}
        out.update(resilient(locale, dict(items[:mid]), endpoint))
        out.update(resilient(locale, dict(items[mid:]), endpoint))
        return out

def chunks(source):
    out, current, chars = [], {}, 0
    for key, value in source.items():
        cost = len(key) + len(value) + 12
        if current and (len(current) >= MAX_KEYS or chars + cost > MAX_CHARS):
            out.append(current); current, chars = {}, 0
        current[key] = value; chars += cost
    if current: out.append(current)
    return out

MARKETING_ORIGIN = "https://agroai-pilot.com"
LEGAL_PAGE_PATHS = {"/terms-of-service", "/privacy-policy", "/pilot-agreement"}


def finalize_links(rendered: str, locale: str) -> str:
    """Make site links absolute and keep legal navigation in the same locale.

    Snapshots are served on agroai-pilot.com; absolute links are unambiguous
    wherever the static artifact is validated or served from.
    """
    def repl(match: re.Match) -> str:
        attr, quote, href = match.group(1), match.group(2), match.group(3)
        if not href.startswith("/") or href.startswith("//"):
            return match.group(0)
        path, _, fragment = href.partition("#")
        path_only = path.split("?", 1)[0].rstrip("/") or "/"
        target = MARKETING_ORIGIN + path
        if path_only in LEGAL_PAGE_PATHS and "lang=" not in path:
            target += ("&" if "?" in path else "?") + f"lang={locale}"
        if fragment:
            target += "#" + fragment
        return f"{attr}={quote}{target}{quote}"
    return re.sub(r'\b(href)=(["\'])([^"\']*)\2', repl, rendered)


def finalize_dir(directory: Path) -> None:
    for html_path in sorted(directory.glob("*/*.html")):
        if html_path.parent.name == "canonical":
            continue
        raw = html_path.read_text(encoding="utf-8")
        updated = finalize_links(raw, html_path.parent.name)
        if updated != raw:
            html_path.write_text(updated, encoding="utf-8")


def localize_document(slug, locale, endpoint, outdir, source_dir=None):
    canonical_url = DOCS[slug]
    source_path = Path(source_dir) / f"{slug}.html" if source_dir else None
    raw = source_path.read_text(encoding="utf-8") if source_path and source_path.exists() else fetch_html(canonical_url)
    source_hash = hashlib.sha256(raw.encode()).hexdigest()
    # The localized legal artifact is a static presentation snapshot. Remove
    # executable application scripts so client-side hydration cannot repaint
    # the translated DOM back into English after load.
    raw = re.sub(r"(?is)<script\b.*?</script\s*>", "", raw)
    if not re.search(r'class=["\'][^"\']*\bskip-link\b', raw, flags=re.I):
        raw = re.sub(
            r"(<body\b[^>]*>)",
            r'\1<a class="skip-link" href="#main-content">Skip to main content</a>',
            raw,
            count=1,
            flags=re.I,
        )
    if re.search(r"<main\b", raw, flags=re.I) and not re.search(r"<main\b[^>]*\bid=[\"\']main-content[\"\']", raw, flags=re.I):
        raw = re.sub(r"<main\b", '<main id="main-content"', raw, count=1, flags=re.I)
    tokens, source, locations = split_visible_text(raw)
    translated = {}
    for chunk in chunks(source):
        translated.update(resilient(locale, chunk, endpoint))
        print(f"{slug} {locale}: {len(translated)}/{len(source)} visible text nodes", flush=True)
    changed = sum(translated[k] != source[k] for k in source)
    if changed < max(10, len(source)//3):
        raise ValueError(f"legal_translation_insufficient_progress:{slug}:{changed}/{len(source)}")
    for key, value in translated.items():
        index, leading, trailing = locations[key]
        tokens[index] = leading + html.escape(value, quote=False) + trailing
    rendered = "".join(tokens)
    if re.search(r"<html\b", rendered, flags=re.I):
        if re.search(r"<html\b[^>]*\blang=", rendered, flags=re.I):
            rendered = re.sub(r'(<html\b[^>]*\blang=)(["\']).*?\2', rf'\1"{locale}"', rendered, count=1, flags=re.I)
        else:
            rendered = re.sub(r"<html\b", f'<html lang="{locale}"', rendered, count=1, flags=re.I)
    chrome = resilient(locale, dict(LEGAL_CHROME), endpoint)
    chrome_json = json.dumps(chrome, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    marker = (
        f'<script type="application/json" id="agroai-legal-chrome">{chrome_json}</script>'
        f'<meta name="agroai-legal-locale" content="{locale}">'
        f'<meta name="agroai-legal-version" content="{canonical_legal_versions()[slug]}">'
        f'<meta name="agroai-legal-source-sha256" content="{source_hash}">'
        f'<link rel="canonical" href="{canonical_url}">'
    )
    rendered = rendered.replace("</head>", marker + "</head>", 1) if "</head>" in rendered else marker + rendered
    rendered = finalize_links(rendered, locale)
    destdir = outdir / locale
    destdir.mkdir(parents=True, exist_ok=True)
    (destdir / f"{slug}.html").write_text(rendered, encoding="utf-8")
    (destdir / f"{slug}.meta.json").write_text(json.dumps({
        "schemaVersion": 1,
        "locale": locale,
        "canonicalUrl": canonical_url,
        "sourceSha256": source_hash,
        "legalVersion": canonical_legal_versions()[slug],
        "presentation": "translation-of-canonical-english",
        "visibleTextNodes": len(source),
        "translatedTextNodes": changed,
        "status": "complete-generated",
    }, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--locale", default="pt-BR")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--outdir", default=str(ROOT/"platform-api/legal/localized"))
    parser.add_argument("--source-dir", default="")
    parser.add_argument("--finalize-dir", default="", help="post-process existing snapshots in place")
    args = parser.parse_args()
    if args.finalize_dir:
        finalize_dir(Path(args.finalize_dir))
        return
    outdir = Path(args.outdir)
    for slug in DOCS:
        localize_document(slug, args.locale, args.endpoint, outdir, args.source_dir or None)

if __name__ == "__main__":
    main()
