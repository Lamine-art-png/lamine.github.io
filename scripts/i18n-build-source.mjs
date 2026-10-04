import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { build } from '../figma-enterprise-v4/node_modules/esbuild/lib/main.js';
const root = path.resolve(import.meta.dirname, '..');
const app = path.join(root, 'figma-enterprise-v4/src/app');
const require = createRequire(fs.realpathSync(path.join(root, 'figma-enterprise-v4/node_modules/@vitejs/plugin-react/package.json')));
const { parse } = createRequire(require.resolve('@babel/core'))('@babel/parser');
const normalize = s => s.trim().replace(/\s+/g, ' ');
const literalKey = s => 'literal.' + createHash('sha256').update(s).digest('hex').slice(0, 16);
const source = {};
const literals = {};
const merge = entries => Object.assign(source, entries);
for (const name of fs.readdirSync(path.join(root, 'shared')).sort()) {
  if (/^ui-.*\.en(?:\.\d+)?\.json$/.test(name)) merge(JSON.parse(fs.readFileSync(path.join(root, 'shared', name), 'utf8')));
}
const compiled = await build({stdin:{contents:`import './commercialBoundaryConversionLabels'; import { TRANSLATIONS } from './i18n'; import { installCommercialBoundaryBaseCatalogs } from './commercialBoundaryI18n'; installCommercialBoundaryBaseCatalogs(); globalThis.catalogs = TRANSLATIONS;`, resolveDir:app, loader:'ts'},bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent'});
const sandbox = {};
vm.runInNewContext(compiled.outputFiles[0].text, sandbox);
merge(sandbox.catalogs.en);
const knownValues = new Set(Object.values(source).map(normalize));
// JSX text is always rendered to customers, including lowercase fragments such
// as "rows" or ", and confirm ..."; other string literals need a word-case
// signal ("I verified ...", "A clean workspace ...") to exclude class names,
// enum values and identifiers.
function plausibleJsxText(text) {
  return text.length > 1 && text.length < 2000 && /[A-Za-z]{2,}/.test(text)
    && !/^(?:https?:|\/|#[0-9a-f]|@|\.\.)/i.test(text)
    && !/(?:=>|className=|\b(?:const|import|export) |\b(?:rgba?|var)\(|\.[jt]sx?$)/.test(text);
}
function plausible(text) {
  return text.length > 1 && text.length < 2000 && (/[A-Z][a-z]/.test(text) || /^(?:I|A) [a-z]/.test(text))
    && !/^(?:https?:|\/|#[0-9a-f]|@|\.\.)/i.test(text)
    && !/(?:=>|className=|\b(?:const|import|export) |\b(?:rgba?|var)\(|\.[jt]sx?$)/.test(text)
    && !/^[A-Za-z0-9_.:/-]+$/.test(text.replace(/^[A-Z][a-z]+$/, ''));
}
// Explicit copy tables (`const COPY = [...]`, `*_LABELS`, `*_COPY`,
// `*_TEMPLATES`, `*_HINTS`) are customer copy by declaration: every string
// value inside them is a source string whatever its casing ("tonnes",
// "Customer-supplied", "AGRO-AI will use"). Object keys are identifiers.
const COPY_TABLE = /^(?:COPY|[A-Z][A-Z0-9_]*_(?:LABELS|COPY|TEMPLATES|HINTS))$/;
function plausibleCopy(text) {
  return text.length > 1 && text.length < 2000 && /\p{L}/u.test(text);
}
function walk(node, inCopy = false) {
  if (!node || typeof node !== 'object') return;
  if (node.type === 'VariableDeclarator' && node.id?.type === 'Identifier' && COPY_TABLE.test(node.id.name)) inCopy = true;
  if (node.type === 'JSXText' || node.type === 'StringLiteral') {
    const value = normalize(node.value);
    const ok = node.type === 'JSXText' ? plausibleJsxText(value) : (inCopy ? plausibleCopy(value) : plausible(value));
    if (ok && !knownValues.has(value)) literals[literalKey(value)] = value;
  }
  for (const [key,value] of Object.entries(node)) {
    if (['loc','start','end','extra','comments'].includes(key)) continue;
    if (inCopy && key === 'key' && node.type === 'ObjectProperty') continue;
    if (Array.isArray(value)) value.forEach((child) => walk(child, inCopy)); else if (value && typeof value === 'object') walk(value, inCopy);
  }
}
// Non-English translation tables (hand-authored fr-FR/pt copy) are not sources.
const TRANSLATION_TABLES = new Set(['i18n.ts', 'commercialBoundaryI18n.ts', 'decisionMemoryI18n.ts', 'commercialBoundaryConversionLabels.ts']);
for (const file of fs.readdirSync(app,{recursive:true}).sort()) {
  const tsx = file.endsWith('.tsx');
  const ts = file.endsWith('.ts') && !file.endsWith('.d.ts') && !TRANSLATION_TABLES.has(file);
  if ((!tsx && !ts) || file.startsWith('components/ui/')) continue;
  walk(parse(fs.readFileSync(path.join(app,file),'utf8'),{sourceType:'module',plugins: tsx ? ['typescript','jsx'] : ['typescript']}));
}
merge(literals);
const sorted = Object.fromEntries(Object.entries(source).sort(([a],[b])=>a.localeCompare(b,'en')));
const fingerprint = createHash('sha256').update(JSON.stringify(sorted)).digest('hex');
const outputs = {
 'source.json': JSON.stringify({schemaVersion:1,sourceFingerprint:fingerprint,catalog:sorted},null,2)+'\n',
 'literals.json': JSON.stringify(literals,null,2)+'\n',
};
for (const [file,content] of Object.entries(outputs)) {
 const dest = path.join(root,'shared/localization',file);
 if (process.argv.includes('--check')) { if (!fs.existsSync(dest) || fs.readFileSync(dest,'utf8')!==content) throw new Error(`Stale canonical source: ${file}`); }
 else fs.writeFileSync(dest,content);
}
console.log(JSON.stringify({keys:Object.keys(source).length,extraLiterals:Object.keys(literals).length,sourceFingerprint:fingerprint}));
