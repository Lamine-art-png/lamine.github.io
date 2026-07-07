import { useSyncExternalStore } from "react";
import { jsx as reactJsx } from "react/jsx-runtime";
import { getStoredLocale } from "../i18n";
import { hasLiteralTranslationSource, translatePortalLiteral } from "../portalLiteralCatalog";
import { getLocaleRuntimeSnapshot, subscribeLocaleRuntime } from "../localeRuntimeStore";

type JsxFactory = (type: any, props: any, key?: any) => any;

const LOCALIZABLE_PROPS = new Set([
  "title",
  "description",
  "label",
  "detail",
  "placeholder",
  "aria-label",
  "alt",
  "eyebrow",
  "subtitle",
  "helperText",
  "emptyText",
  "confirmText",
  "cancelText",
]);

function useLocaleRuntimeRevision() {
  useSyncExternalStore(subscribeLocaleRuntime, getLocaleRuntimeSnapshot, getLocaleRuntimeSnapshot);
}

function localizeStaticString(value: string): string {
  return hasLiteralTranslationSource(value) ? translatePortalLiteral(value, getStoredLocale()) : value;
}

function LocalizedText({ source }: { source: string }) {
  useLocaleRuntimeRevision();
  return localizeStaticString(source);
}

function localizeChild(value: any, keyPrefix = "i18n"): any {
  if (typeof value === "string") {
    if (!hasLiteralTranslationSource(value)) return value;
    return reactJsx(LocalizedText, { source: value }, keyPrefix);
  }
  if (Array.isArray(value)) {
    return value.map((child, index) => localizeChild(child, `${keyPrefix}-${index}`));
  }
  return value;
}

function hasStringLocalizableProp(props: any): boolean {
  if (!props || typeof props !== "object") return false;
  for (const prop of LOCALIZABLE_PROPS) {
    if (typeof props[prop] === "string") return true;
  }
  return false;
}

function localizeProps(props: any): any {
  if (!props || typeof props !== "object") return props;
  const next = { ...props };
  if ("children" in next) next.children = localizeChild(next.children);
  for (const prop of LOCALIZABLE_PROPS) {
    if (typeof next[prop] === "string" && hasLiteralTranslationSource(next[prop])) {
      next[prop] = localizeStaticString(next[prop]);
    }
  }
  return next;
}

function LocalizedElement({ type, props, factory, elementKey }: { type: any; props: any; factory: JsxFactory; elementKey?: any }) {
  useLocaleRuntimeRevision();
  return factory(type, localizeProps(props), elementKey);
}

export function createLocalizedJsx(factory: JsxFactory, type: any, props: any, key?: any) {
  const childrenLocalized = props && typeof props === "object" && "children" in props
    ? { ...props, children: localizeChild(props.children) }
    : props;

  // Wrapper identity must depend only on prop shape, never on the active language
  // or whether the current value still matches the English source catalog.
  if (hasStringLocalizableProp(childrenLocalized) && !childrenLocalized?.ref) {
    return reactJsx(LocalizedElement, { type, props: childrenLocalized, factory, elementKey: key }, key);
  }
  return factory(type, childrenLocalized, key);
}
