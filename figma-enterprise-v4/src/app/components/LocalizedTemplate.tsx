import { Fragment, ReactNode } from "react";
import { useLocale } from "../hooks/useLocale";
import { translatePortalLiteral } from "../portalLiteralCatalog";

/**
 * Render a whole-sentence template in the active locale, substituting React
 * nodes (links, emphasis, values) for {placeholders}. Translators see the
 * complete sentence, so each language can order it naturally; the catalog
 * validators guarantee every placeholder survives translation.
 */
export function LocalizedTemplate({ template, values }: { template: string; values: Record<string, ReactNode> }) {
  const { selectedLocale } = useLocale();
  const translated = translatePortalLiteral(template, selectedLocale);
  const parts = translated.split(/(\{[A-Za-z_][A-Za-z0-9_]*\})/);
  return (
    <>
      {parts.map((part, index) => {
        const match = /^\{([A-Za-z_][A-Za-z0-9_]*)\}$/.exec(part);
        if (match && match[1] in values) return <Fragment key={index}>{values[match[1]]}</Fragment>;
        return <Fragment key={index}>{part}</Fragment>;
      })}
    </>
  );
}
