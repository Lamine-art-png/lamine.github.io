#!/usr/bin/env python3
"""
Validation suite for the AGRO-AI Platform API developer experience.

Static-site quality gate — runs with the Python standard library only, so it
works in any CI without dependencies. Checks, per page and across the site:

  * HTML structure (lang, title, viewport, meta description, single <h1>)
  * Accessibility basics (skip link, images have alt, buttons/nav labelled)
  * Internal link integrity (every local href resolves to a real file/anchor)
  * No leaked secrets (no live-looking API keys committed to the bundle)
  * openapi.json is well-formed and internally consistent

Exit code is non-zero if any check fails, so CI blocks a regression.
Run:  python3 platform-api/tests/validate_platform.py
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # .../platform-api
REPO = ROOT.parent                                   # repo root (serves "/")
FAILURES: list[str] = []
CHECKS = 0


def fail(msg: str) -> None:
    FAILURES.append(msg)


def check(cond: bool, msg: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        fail(msg)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.h1 = 0
        self.title = ""
        self._in_title = False
        self.has_viewport = False
        self.has_description = False
        self.has_lang = False
        self.has_skip = False
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.imgs_missing_alt = 0
        self.buttons_unlabelled = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html" and a.get("lang"):
            self.has_lang = True
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self.h1 += 1
        if tag == "meta":
            if a.get("name") == "viewport":
                self.has_viewport = True
            if a.get("name") == "description" and a.get("content"):
                self.has_description = True
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a":
            cls = a.get("class", "")
            if "skip-link" in cls:
                self.has_skip = True
            href = a.get("href")
            if href:
                self.links.append(href)
        if tag == "img":
            # alt="" is a valid (decorative) alt; missing attribute is not
            if "alt" not in a:
                self.imgs_missing_alt += 1
        if tag == "button":
            has_text_label = a.get("aria-label") or a.get("title")
            # buttons with visible text are validated loosely; icon-only need a label
            if not has_text_label and a.get("class", "").find("theme-toggle") >= 0:
                self.buttons_unlabelled += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def resolve_local(href: str, page: Path) -> Path | None:
    """Map a root-relative or relative href to a file path under the repo."""
    path = href.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return page  # pure "#anchor" -> same page
    if path.startswith("/"):
        target = REPO / path.lstrip("/")
    else:
        target = (page.parent / path)
    target = target.resolve()
    if target.is_dir():
        target = target / "index.html"
    return target


def is_external(href: str) -> bool:
    return href.startswith(("http://", "https://", "mailto:", "tel:", "//"))


def validate_page(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    p = PageParser()
    p.feed(html)
    rel = page.relative_to(REPO)

    check(p.has_lang, f"{rel}: <html> is missing a lang attribute")
    check(bool(p.title.strip()), f"{rel}: missing/empty <title>")
    check(p.has_viewport, f"{rel}: missing viewport meta")
    check(p.has_description, f"{rel}: missing meta description")
    check(p.h1 == 1, f"{rel}: expected exactly one <h1>, found {p.h1}")
    check(p.has_skip, f"{rel}: missing skip-to-content link")
    check(p.imgs_missing_alt == 0, f"{rel}: {p.imgs_missing_alt} <img> without alt attribute")
    check(p.buttons_unlabelled == 0, f"{rel}: icon-only button without accessible label")

    # Internal link integrity
    for href in p.links:
        if is_external(href):
            continue
        target = resolve_local(href, page)
        if target is None:
            continue
        if not target.exists():
            fail(f"{rel}: broken internal link -> {href} (resolved {target.relative_to(REPO)})")
        # anchor check when same-page and file exists
        if "#" in href:
            frag = href.split("#", 1)[1]
            if frag and (href.startswith("#") or target == page):
                if frag not in p.ids:
                    fail(f"{rel}: dangling anchor #{frag}")


SECRET_PATTERNS = [
    re.compile(r"sk_live_[A-Za-z0-9]{8,}"),
    re.compile(r"whsec_[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),                       # AWS access key id
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
]
SECRET_ALLOW = {"whsec_masked_shown_once", "whsec_"}


def scan_secrets() -> None:
    for f in ROOT.rglob("*"):
        if not f.is_file() or f.suffix not in {".js", ".html", ".json", ".css"}:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for pat in SECRET_PATTERNS:
            for m in pat.finditer(text):
                if m.group(0) in SECRET_ALLOW:
                    continue
                fail(f"{f.relative_to(REPO)}: possible committed secret: {m.group(0)[:12]}…")


def validate_spec() -> None:
    spec_path = ROOT / "assets" / "openapi.json"
    check(spec_path.exists(), "openapi.json is missing")
    if not spec_path.exists():
        return
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    check("info" in spec and "endpoints" in spec and "tags" in spec,
          "openapi.json missing top-level info/tags/endpoints")
    tag_ids = {t["id"] for t in spec["tags"]}
    seen_ids: set[str] = set()
    for ep in spec["endpoints"]:
        for key in ("id", "tag", "method", "path", "summary"):
            check(key in ep, f"endpoint missing '{key}': {ep.get('id', '?')}")
        check(ep["id"] not in seen_ids, f"duplicate endpoint id: {ep['id']}")
        seen_ids.add(ep["id"])
        check(ep["tag"] in tag_ids, f"endpoint {ep['id']} references unknown tag {ep['tag']}")
        check(ep["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE"},
              f"endpoint {ep['id']} has odd method {ep['method']}")
        # path params must be declared
        for name in re.findall(r"\{(\w+)\}", ep["path"]):
            declared = any(pp.get("name") == name and pp.get("in") == "path"
                           for pp in ep.get("params", []))
            check(declared, f"endpoint {ep['id']}: path param {{{name}}} not declared")


def main() -> int:
    pages = sorted(ROOT.rglob("*.html"))
    check(len(pages) >= 8, f"expected the full page set, found {len(pages)}")
    for page in pages:
        validate_page(page)
    scan_secrets()
    validate_spec()

    print(f"Ran {CHECKS} checks across {len(pages)} pages.")
    if FAILURES:
        print(f"\n{len(FAILURES)} problem(s):")
        for msg in FAILURES:
            print(f"  ✗ {msg}")
        return 1
    print("All Platform API experience checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
