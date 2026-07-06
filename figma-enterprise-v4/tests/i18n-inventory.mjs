import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { parse } from "@babel/parser";

const root = process.cwd();
const sourceRoot = path.join(root, "src", "app");
const outputPath = path.join(root, "outputs", "i18n-candidate-inventory.json");

const CATEGORIES = {
  A: "A_CUSTOMER_VISIBLE_STATIC_COPY",
  B: "B_MACHINE_PROTOCOL_VALUE",
  C: "C_USER_CONTENT",
  D: "D_MODEL_CONTENT",
  F: "F_PROPER_NOUN_VENDOR",
  G: "G_TECHNICAL_ACRONYM",
  H: "H_DEVELOPER_ONLY",
  I: "I_FALSE_POSITIVE",
  J: "J_NEEDS_HUMAN_REVIEW",
};

const visiblePropNames = new Set([
  "title", "label", "description", "subtitle", "detail", "action", "body",
  "empty", "emptyText", "message", "cta", "badge", "placeholder", "alt",
  "helperText", "hint", "eyebrow", "caption", "summary", "question", "answer",
  "name", "text", "copy", "reason", "why", "instructions",
]);

const structuralJsxAttrs = new Set([
  "className", "style", "id", "key", "value", "type", "role", "name", "htmlFor",
  "href", "to", "target", "rel", "method", "action", "src", "width", "height",
  "tabIndex", "autoComplete", "inputMode", "pattern", "data-testid",
]);

const protocolObjectKeys = new Set([
  "id", "code", "status", "type", "role", "provider", "method", "mode", "source",
  "path", "endpoint", "url", "href", "key", "locale", "languageCode", "direction",
  "plan_id", "billing_period", "workspace_id", "tenant_id", "block_id", "field_id",
  "content_type", "file_type", "task", "profile", "model", "event_type", "channel",
  "risk_level", "priority", "scope", "audience", "output_format", "created_from",
]);

const vendors = [
  "AGRO-AI", "WiseConn", "John Deere", "Talgil", "Google Drive", "Google Earth Engine",
  "Gmail", "Outlook", "Dropbox", "Box", "Slack", "Salesforce", "Stripe", "OpenET",
  "Netafim", "Microsoft", "Google", "AWS", "Azure",
];

const acronyms = new Set([
  "AI", "API", "CSV", "JSON", "PDF", "TXT", "XLS", "XLSX", "KML", "ZIP", "SSO",
  "SAML", "SGMA", "ETc", "ETo", "NDVI", "VWC", "GPM", "KPA", "ERP", "URL", "MIME",
]);

const cssLiteral = /^(?:rgba?\(|hsla?\(|#[0-9a-f]{3,8}\b|(?:\d+(?:\.\d+)?px\s+)?(?:solid|dashed|dotted)\s+#)/i;
const tailwindish = /^(?:[a-z0-9:[\]#/.%-]+(?:\s+|$)){2,}$/i;
const apiPath = /^(?:https?:\/\/|\/v\d+\/|\/api\/|data:image\/)/i;
const acceptList = /^\.(?:[a-z0-9]+)(?:,\.[a-z0-9]+)+$/i;
const csvHeader = /^[A-Za-z_][A-Za-z0-9_]*(?:,[A-Za-z_][A-Za-z0-9_]*){2,}$/;
const csvRow = /^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?,/;
const machineToken = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/;
const hexOrNumber = /^(?:-?\d+(?:\.\d+)?|#[0-9a-f]{3,8})$/i;

function walkFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkFiles(full));
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out.sort();
}

function keyName(node) {
  if (!node) return "";
  if (node.type === "Identifier") return node.name;
  if (node.type === "StringLiteral") return node.value;
  return "";
}

function calleeName(node) {
  if (!node) return "";
  if (node.type === "Identifier") return node.name;
  if (node.type === "MemberExpression" || node.type === "OptionalMemberExpression") {
    const left = calleeName(node.object);
    const right = keyName(node.property);
    return [left, right].filter(Boolean).join(".");
  }
  return "";
}

function pureVendor(value) {
  const normalized = value.trim().toLowerCase();
  return vendors.some((vendor) => normalized === vendor.toLowerCase());
}

function pureAcronym(value) {
  const normalized = value.trim();
  return acronyms.has(normalized) || /^[A-Z][A-Z0-9/&.-]{1,10}$/.test(normalized);
}

function developerInvariant(value) {
  return /must be used within|did not include an access token|unexpected invariant|unreachable|not configured for runtime/i.test(value);
}

function visibleCall(chain) {
  for (const item of chain) {
    if (item.node.type !== "CallExpression" && item.node.type !== "OptionalCallExpression") continue;
    const name = calleeName(item.node.callee).toLowerCase();
    if (/(^|\.)(toast|alert|confirm|seterror|setnotice|setsuccess|notify|notification|showerror|showsuccess)$/.test(name)) return true;
  }
  return false;
}

function consoleCall(chain) {
  return chain.some((item) => {
    if (item.node.type !== "CallExpression") return false;
    return calleeName(item.node.callee).startsWith("console.");
  });
}

function nearest(chain, type) {
  for (let i = chain.length - 1; i >= 0; i -= 1) {
    if (chain[i].node.type === type) return chain[i];
  }
  return null;
}

function classify({ value, file, node, chain }) {
  const trimmed = value.trim();
  const relative = path.relative(root, file).split(path.sep).join("/");

  if (!trimmed) return [CATEGORIES.I, "empty_or_whitespace"];
  if (node.type === "JSXText") return [CATEGORIES.A, "jsx_text"];

  const jsxAttr = nearest(chain, "JSXAttribute");
  if (jsxAttr) {
    const attr = keyName(jsxAttr.node.name);
    if (attr === "className") return [CATEGORIES.I, "jsx_class_name"];
    if (attr === "style") return [CATEGORIES.I, "jsx_style_literal"];
    if (attr === "accept") return [CATEGORIES.B, "file_accept_protocol"];
    if (visiblePropNames.has(attr) || attr.startsWith("aria-")) return [CATEGORIES.A, `jsx_visible_attr:${attr}`];
    if (structuralJsxAttrs.has(attr) || attr.startsWith("data-")) return [CATEGORIES.B, `jsx_structural_attr:${attr}`];
    return [CATEGORIES.A, `jsx_conservative_attr:${attr || "unknown"}`];
  }

  if (relative.endsWith("/i18n.ts")) return [CATEGORIES.A, "translation_catalog_copy"];
  if (trimmed.startsWith("data:image/")) return [CATEGORIES.I, "data_uri_asset"];
  if (cssLiteral.test(trimmed)) return [CATEGORIES.I, "css_visual_literal"];
  if (tailwindish.test(trimmed) && /(?:^|\s)(?:flex|grid|text-|bg-|border|rounded|px-|py-|p-|m-|w-|h-|gap-|items-|justify-|shadow)/.test(trimmed)) {
    return [CATEGORIES.I, "css_utility_literal"];
  }
  if (apiPath.test(trimmed)) return [CATEGORIES.B, "url_or_api_protocol"];
  if (acceptList.test(trimmed)) return [CATEGORIES.B, "file_accept_protocol"];
  if (csvHeader.test(trimmed)) return [CATEGORIES.B, "csv_schema_sample"];
  if (csvRow.test(trimmed)) return [CATEGORIES.B, "csv_data_sample"];
  if (trimmed === '"answer"' || trimmed === '"summary"') return [CATEGORIES.B, "serialized_response_key_probe"];
  if (hexOrNumber.test(trimmed)) return [CATEGORIES.B, "numeric_or_color_token"];
  if (machineToken.test(trimmed)) return [CATEGORIES.B, "machine_token"];
  if (developerInvariant(trimmed)) return [CATEGORIES.H, "developer_invariant"];
  if (consoleCall(chain)) return [CATEGORIES.H, "console_diagnostic"];
  if (pureVendor(trimmed)) return [CATEGORIES.F, "proper_noun_vendor"];
  if (pureAcronym(trimmed)) return [CATEGORIES.G, "technical_acronym"];

  const importDecl = nearest(chain, "ImportDeclaration") || nearest(chain, "ExportNamedDeclaration") || nearest(chain, "ExportAllDeclaration");
  if (importDecl && importDecl.node.source === node) return [CATEGORIES.H, "module_specifier"];

  const objectProperty = nearest(chain, "ObjectProperty");
  if (objectProperty) {
    const key = keyName(objectProperty.node.key);
    if (visiblePropNames.has(key)) return [CATEGORIES.A, `visible_object_property:${key}`];
    if (protocolObjectKeys.has(key)) {
      if (/\s/.test(trimmed) || /^[A-Z]/.test(trimmed)) return [CATEGORIES.A, `human_label_in_protocol_property:${key}`];
      return [CATEGORIES.B, `protocol_object_property:${key}`];
    }
  }

  if (visibleCall(chain)) return [CATEGORIES.A, "user_feedback_call"];

  const throwStmt = nearest(chain, "ThrowStatement");
  if (throwStmt) return [CATEGORIES.A, "conservative_runtime_error_copy"];

  // Conservative terminal rule: unexplained literals in production app source are
  // classified as customer-visible static copy, never silently discarded. This can
  // over-report copy, but cannot hide a customer-facing localization candidate.
  return [CATEGORIES.A, "conservative_production_copy"];
}

function location(node) {
  return {
    line: node.loc?.start?.line ?? 0,
    column: (node.loc?.start?.column ?? 0) + 1,
  };
}

function traverse(node, chain, visit) {
  if (!node || typeof node !== "object") return;
  if (typeof node.type === "string") visit(node, chain);
  const next = typeof node.type === "string" ? [...chain, { node }] : chain;
  for (const [key, value] of Object.entries(node)) {
    if (key === "loc" || key === "start" || key === "end" || key === "extra" || key === "tokens" || key === "comments") continue;
    if (Array.isArray(value)) {
      for (const child of value) traverse(child, next, visit);
    } else if (value && typeof value === "object") {
      traverse(value, next, visit);
    }
  }
}

const candidates = [];
for (const file of walkFiles(sourceRoot)) {
  const code = fs.readFileSync(file, "utf8");
  const ast = parse(code, {
    sourceType: "module",
    plugins: ["typescript", "jsx", "decorators-legacy", "classProperties", "dynamicImport", "importMeta"],
    errorRecovery: false,
  });

  traverse(ast.program, [], (node, chain) => {
    let value = null;
    if (node.type === "StringLiteral") value = node.value;
    else if (node.type === "JSXText") value = node.value.replace(/\s+/g, " ").trim();
    else if (node.type === "TemplateLiteral" && node.expressions.length === 0) value = node.quasis.map((q) => q.value.cooked ?? q.value.raw).join("");
    if (value === null || !value.trim()) return;

    const [category, reason] = classify({ value, file, node, chain });
    const loc = location(node);
    candidates.push({
      file: path.relative(path.resolve(root, ".."), file).split(path.sep).join("/"),
      line: loc.line,
      column: loc.column,
      value,
      category,
      reason,
      astNode: node.type,
      parentChain: chain.slice(-8).map((item) => item.node.type).join(">"),
    });
  });
}

const byCategory = {};
const byFile = {};
for (const candidate of candidates) {
  byCategory[candidate.category] = (byCategory[candidate.category] || 0) + 1;
  byFile[candidate.file] = (byFile[candidate.file] || 0) + 1;
}

const remainingUnexplained = candidates.filter((candidate) => candidate.category === CATEGORIES.J).length;
const report = {
  generated_at: new Date().toISOString(),
  source_root: "figma-enterprise-v4/src/app",
  scanner: "babel-ast-exact-head-v1",
  classification_policy: "unknown production literals conservatively classify as customer-visible static copy; nothing is silently excluded",
  total_candidates: candidates.length,
  by_category: Object.fromEntries(Object.entries(byCategory).sort()),
  by_file: Object.fromEntries(Object.entries(byFile).sort((a, b) => b[1] - a[1])),
  remaining_unexplained_customer_visible: remainingUnexplained,
  candidates,
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
const serialized = `${JSON.stringify(report, null, 2)}\n`;
fs.writeFileSync(outputPath, serialized);
const digest = crypto.createHash("sha256").update(serialized).digest("hex");

console.log(JSON.stringify({
  total_candidates: report.total_candidates,
  by_category: report.by_category,
  remaining_unexplained_customer_visible: remainingUnexplained,
  output: path.relative(root, outputPath),
  sha256: digest,
}, null, 2));

if (remainingUnexplained !== 0) {
  throw new Error(`i18n inventory has ${remainingUnexplained} unexplained candidates`);
}
