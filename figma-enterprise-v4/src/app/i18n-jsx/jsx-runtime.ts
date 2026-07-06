import { Fragment, jsx as reactJsx, jsxs as reactJsxs } from "react/jsx-runtime";
import { createLocalizedJsx } from "./runtimeCore";

export { Fragment };
export function jsx(type: any, props: any, key?: any) {
  return createLocalizedJsx(reactJsx, type, props, key);
}
export function jsxs(type: any, props: any, key?: any) {
  return createLocalizedJsx(reactJsxs, type, props, key);
}
