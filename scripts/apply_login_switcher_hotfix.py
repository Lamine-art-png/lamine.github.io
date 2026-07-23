from pathlib import Path

root = Path(__file__).resolve().parents[1]
source_path = root / "cloudflare/platform-api-marketing-worker/src/index.ts"
test_path = root / "cloudflare/platform-api-marketing-worker/tests/contract.mjs"

source = source_path.read_text(encoding="utf-8")
old = 'const target=[...document.querySelectorAll("header a,header button")].find(e=>visible(e)&&clean(e.textContent)==="open portal");'
new = 'const loginLabels=new Set(["open portal","log in","login"]);const target=[...document.querySelectorAll("header a,header button")].find(e=>{if(!visible(e))return false;const label=clean(e.textContent);const href=e instanceof HTMLAnchorElement?e.href:"";return loginLabels.has(label)||href===PORTAL||href===PORTAL+"/"});'
if old in source:
    source = source.replace(old, new, 1)
elif new not in source:
    raise SystemExit("Login switcher selector contract not found")
source_path.write_text(source, encoding="utf-8")

test = test_path.read_text(encoding="utf-8")
needle = "  'Open API Platform',\n"
addition = "  'const loginLabels=new Set([\\\"open portal\\\",\\\"log in\\\",\\\"login\\\"])',\n  'href===PORTAL',\n"
if addition.strip() not in test:
    if needle not in test:
        raise SystemExit("Worker contract insertion point not found")
    test = test.replace(needle, needle + addition, 1)
test_path.write_text(test, encoding="utf-8")

print("Login switcher selector hotfix applied")
