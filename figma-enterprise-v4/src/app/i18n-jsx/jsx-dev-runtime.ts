import { Fragment, jsxDEV as reactJsxDEV } from "react/jsx-dev-runtime";
import { createLocalizedJsx } from "./runtimeCore";

export { Fragment };
export function jsxDEV(type: any, props: any, key?: any, isStaticChildren?: boolean, source?: any, self?: any) {
  return createLocalizedJsx(
    (nextType, nextProps, nextKey) => reactJsxDEV(nextType, nextProps, nextKey, isStaticChildren, source, self),
    type,
    props,
    key,
  );
}
