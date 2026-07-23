#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
APP_ROOT = ROOT / "src" / "app"
BASE_CATALOG_PATH = REPO_ROOT / "shared" / "ui-catalog.en.json"
LITERAL_CATALOG_GLOB = "ui-literals.en.*.json"

PROP_NAMES = {
    "title", "description", "label", "detail", "placeholder", "aria-label", "alt",
    "eyebrow", "subtitle", "helperText", "emptyText", "confirmText", "cancelText",
}
OBJECT_NAMES = {
    "name", "title", "description", "label", "detail", "subtitle", "eyebrow",
    "helperText", "emptyText", "text", "caption",
}
CODE_TOKENS = (
    "const ", "let ", "var ", "function ", "return ", "useState", "Array.",
    "Record<", "React.", "=>", "?.", ");", "};", "import ", "export ",
    "className=", "style=", "setState", "setMessage", "localStorage.",
)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def plausible(value: str) -> bool:
    value = normalize(value)
    if not value or len(value) < 2 or len(value) > 500:
        return False
    if not re.search(r"[A-Za-z\u00C0-\uFFFF]", value):
        return False
    if any(token in value for token in CODE_TOKENS):
        return False
    if value[0] in "();=:&|]}":
        return False
    if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", value):
        return False
    if re.fullmatch(r"rgba?\([^)]*\)", value):
        return False
    if value.startswith(("/", "http://", "https://", "mailto:", "tel:", "figma:asset/")):
        return False
    if re.fullmatch(r"[A-Za-z0-9_.:/?-]+", value) and len(value) > 40:
        return False
    return True


def collect_literals() -> list[str]:
    values: set[str] = set()
    prop_pattern = "|".join(re.escape(name) for name in sorted(PROP_NAMES))
    object_pattern = "|".join(re.escape(name) for name in sorted(OBJECT_NAMES))
    for path in APP_ROOT.rglob("*.tsx"):
        relative = path.relative_to(APP_ROOT).as_posix()
        if relative.startswith("components/ui/"):
            continue
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r">([^<>{}]+)<", source, flags=re.S):
            value = normalize(match.group(1))
            if plausible(value):
                values.add(value)
        for match in re.finditer(rf"\b({prop_pattern})=[\"']([^\"']+)[\"']", source):
            value = normalize(match.group(2))
            if plausible(value):
                values.add(value)
        for match in re.finditer(rf"\b({object_pattern})\s*:\s*[\"']([^\"']+)[\"']", source):
            value = normalize(match.group(2))
            if plausible(value):
                values.add(value)
    base = json.loads(BASE_CATALOG_PATH.read_text(encoding="utf-8"))
    base_values = set(base.values())
    return sorted(value for value in values if value not in base_values)


def build_catalog() -> dict[str, str]:
    return {
        "literal." + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]: value
        for value in collect_literals()
    }


def load_parts(*, exclude: Path | None = None) -> tuple[dict[str, str], list[Path]]:
    current: dict[str, str] = {}
    paths = sorted((REPO_ROOT / "shared").glob(LITERAL_CATALOG_GLOB))
    for path in paths:
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        part = json.loads(path.read_text(encoding="utf-8"))
        overlap = set(current).intersection(part)
        if overlap:
            raise SystemExit(f"Duplicate literal keys across catalog parts: {sorted(overlap)}")
        current.update(part)
    return current, paths


def write_delta(target: Path) -> int:
    expected = build_catalog()
    current, paths = load_parts(exclude=target)
    missing = {key: expected[key] for key in sorted(set(expected) - set(current))}
    extra = {
        key: {
            "value": current[key],
            "catalog": next(
                path.relative_to(REPO_ROOT).as_posix()
                for path in paths
                if key in json.loads(path.read_text(encoding="utf-8"))
            ),
        }
        for key in sorted(set(current) - set(expected))
    }
    changed = {
        key: {"current": current[key], "expected": expected[key]}
        for key in sorted(set(current).intersection(expected))
        if current[key] != expected[key]
    }
    payload = {
        "diagnostic_only": True,
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "expected_count": len(expected),
        "current_count_excluding_target": len(current),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote complete reconciliation diagnostics to {target.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-delta", type=Path)
    args = parser.parse_args()
    if args.write_delta:
        target = args.write_delta
        if not target.is_absolute():
            target = (REPO_ROOT / target).resolve()
        return write_delta(target)
    if args.check:
        print("Diagnostic branch: inventory reconciliation is emitted by --write-delta")
        return 0
    raise SystemExit("Use --check or --write-delta shared/ui-literals.en.N.json.")


if __name__ == "__main__":
    raise SystemExit(main())
