from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str, label: str) -> None:
    text = read(path)
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise RuntimeError(f"{label}: expected one match in {path}, found {count}")
    write(path, text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, label: str, minimum: int = 1) -> None:
    text = read(path)
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count < minimum:
        raise RuntimeError(f"{label}: expected at least {minimum} matches in {path}, found {count}")
    write(path, text.replace(old, new))


replace_once(
    "platform-api/index.html",
    '<html lang="en">',
    '<html lang="en" data-agroai-platform-page="landing">',
    "landing identity marker",
)
replace_once(
    "platform-api/index.html",
    "<title>AGRO-AI Platform API — private beta</title>",
    "<title>AGRO-AI Platform API</title>",
    "landing title",
)
replace_once(
    "platform-api/docs/index.html",
    '<html lang="en">',
    '<html lang="en" data-agroai-platform-page="docs">',
    "docs identity marker",
)
replace_once(
    "platform-api/docs/index.html",
    "<title>Documentation — AGRO-AI Platform API</title>",
    "<title>AGRO-AI Platform API Documentation</title>",
    "docs title",
)
replace_once(
    "platform-api/docs/index.html",
    "Field-level water intelligence over a curated REST API. Access is provisioned per organization; test and live projects are gated separately.",
    "Operational agriculture intelligence through a curated REST API. Access is provisioned per organization, with test and live projects gated separately.",
    "docs positioning",
)

for html_path in sorted((ROOT / "platform-api").rglob("*.html")):
    text = html_path.read_text(encoding="utf-8")
    text = text.replace("https://app.agroai-pilot.com/developers/api/apply?type=developer_beta", "https://platform.agroai-pilot.com")
    text = text.replace("https://app.agroai-pilot.com/developers/api/apply?type=strategic_partner", "https://platform.agroai-pilot.com")
    text = text.replace('href="https://app.agroai-pilot.com"', 'href="https://platform.agroai-pilot.com"')
    html_path.write_text(text, encoding="utf-8")

replace_once(
    "index.html",
    'apiLink.textContent = "API";',
    'apiLink.textContent = "API Platform";',
    "website API navigation label",
)

replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    "  BrainCircuit,\n",
    "  BrainCircuit,\n  Code2,\n",
    "Platform icon import",
)
replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    "    platformAdmin,\n    platformDeveloper,\n    logout,",
    "    platformAdmin,\n    logout,",
    "remove hidden enrollment nav dependency",
)
replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    '''  const workspaceItems: NavItem[] = [
    { name: t("sources"), path: "/sources", icon: FolderOpen },
    { name: t("team"), path: "/team", icon: Users, locked: !canInviteTeam, upgradeTo: "team" },
    { name: t("settings"), path: "/settings", icon: Settings },
  ];
''',
    '''  const productItems: NavItem[] = [
    { name: "Platform API", path: "/platform", icon: Code2 },
  ];

  const workspaceItems: NavItem[] = [
    { name: t("sources"), path: "/sources", icon: FolderOpen },
    { name: t("team"), path: "/team", icon: Users, locked: !canInviteTeam, upgradeTo: "team" },
    { name: t("settings"), path: "/settings", icon: Settings },
  ];
''',
    "first-class product navigation",
)
replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    '''    { name: t("admin"), path: "/admin", icon: Settings },
    ...(platformDeveloper ? [
      { name: "Developers/API", path: "/developers/api", icon: Shield },
    ] : []),
    ...(platformAdmin ? [
      { name: "Customer accounts", path: "/admin/customers", icon: Users },
      { name: "Platform API review", path: "/admin/platform-api", icon: Shield },
    ] : []),
''',
    '''    { name: t("admin"), path: "/admin", icon: Settings },
    ...(platformAdmin ? [
      { name: "Customer accounts", path: "/admin/customers", icon: Users },
      { name: "API access reviews", path: "/admin/platform-api", icon: Shield },
    ] : []),
''',
    "separate developer product from administration",
)
replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    "  const allPrimaryItems = [...operateItems, ...intelligenceItems, ...workspaceItems, ...accountItems];",
    "  const allPrimaryItems = [...operateItems, ...intelligenceItems, ...productItems, ...workspaceItems, ...accountItems];",
    "active product label",
)
replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    "    intelligenceItems,\n    workspaceItems,",
    "    intelligenceItems,\n    productItems,\n    workspaceItems,",
    "sidebar product props",
)
replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    "  intelligenceItems,\n  workspaceItems,\n  accountItems,",
    "  intelligenceItems,\n  productItems,\n  workspaceItems,\n  accountItems,",
    "sidebar parameter product items",
)
replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    "  intelligenceItems: NavItem[];\n  workspaceItems: NavItem[];",
    "  intelligenceItems: NavItem[];\n  productItems: NavItem[];\n  workspaceItems: NavItem[];",
    "sidebar product item type",
)
replace_once(
    "figma-enterprise-v4/src/app/components/MainLayout.tsx",
    '''        <NavSection title={t("operate")} items={operateItems} onNavigate={onNavigate} collapsed={isCollapsed} />
        <NavSection title={t("intelligence")} items={intelligenceItems} onNavigate={onNavigate} collapsed={isCollapsed} />
        <NavSection title={t("workspace")} items={workspaceItems} onNavigate={onNavigate} collapsed={isCollapsed} />
''',
    '''        <NavSection title={t("operate")} items={operateItems} onNavigate={onNavigate} collapsed={isCollapsed} />
        <NavSection title={t("intelligence")} items={intelligenceItems} onNavigate={onNavigate} collapsed={isCollapsed} />
        <NavSection title="Products" items={productItems} onNavigate={onNavigate} collapsed={isCollapsed} />
        <NavSection title={t("workspace")} items={workspaceItems} onNavigate={onNavigate} collapsed={isCollapsed} />
''',
    "render first-class product section",
)

replace_once(
    "figma-enterprise-v4/src/app/routes.tsx",
    '{ path: "developers/api", lazy: lazyComponent(() => import("./components/DevelopersApi"), "DevelopersApi") },',
    '{ path: "developers/api", element: <Navigate to="/platform" replace /> },',
    "legacy developer console redirect",
)

contract_path = "figma-enterprise-v4/tests/platform-api-console-contract.mjs"
contract = read(contract_path)
routes_import = 'const routesSource = readFileSync(new URL("../src/app/routes.tsx", import.meta.url), "utf8");'
layout_import = 'const layoutSource = readFileSync(new URL("../src/app/components/MainLayout.tsx", import.meta.url), "utf8");'
if layout_import not in contract:
    if routes_import not in contract:
        raise RuntimeError("Platform console route source import missing")
    contract = contract.replace(routes_import, routes_import + "\n" + layout_import, 1)

needle = 'assert.ok(routesSource.includes("<PlatformSafetyNotice />"), "enrolled developers must see the controlled-launch state");\n'
assertion = 'assert.ok(layoutSource.includes(\'{ name: "Platform API", path: "/platform", icon: Code2 }\'), "the Enterprise Portal must expose the unified Platform product to every verified organization");'
if assertion not in contract:
    if needle not in contract:
        raise RuntimeError("Platform console contract insertion point missing")
    insert = '''assert.ok(routesSource.includes("<PlatformSafetyNotice />"), "enrolled developers must see the controlled-launch state");
assert.ok(layoutSource.includes('{ name: "Platform API", path: "/platform", icon: Code2 }'), "the Enterprise Portal must expose the unified Platform product to every verified organization");
assert.ok(layoutSource.includes('<NavSection title="Products" items={productItems}'), "Platform API must be presented as a first-class product, not an account utility");
assert.ok(layoutSource.includes('{ name: "API access reviews", path: "/admin/platform-api"'), "internal approval operations must be visibly distinct from the developer console");
assert.ok(!layoutSource.includes('name: "Developers/API"'), "the duplicate legacy developer navigation must be removed");
assert.ok(routesSource.includes('path: "developers/api", element: <Navigate to="/platform" replace />'), "legacy deep links must converge on the unified Platform console");
'''
    contract = contract.replace(needle, insert, 1)
write(contract_path, contract)

print("Platform product discovery and console patch applied")
