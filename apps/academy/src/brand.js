// AGRO-AI Academy brand: the single source for logo assets, colours and the
// brand typeface, shared by pages, emails, certificates and the CSP. Logo
// files are generated from the official lockup (brand/agro-ai-academy-logo.svg)
// by scripts/brand/; the palette is sampled from the same artwork.

export const BRAND = {
  name: "AGRO-AI Academy",
  colors: {
    forestDeep: "#082503", // darkest tone of the mark
    forest: "#0c3e03",
    green: "#1c4c07", // AGRO-AI wordmark
    leaf: "#27570b",
    leafBright: "#6fac1e",
    lime: "#b1e646",
    limeBright: "#d6fc5b", // brightest tone of the mark
    sage: "#42771d", // ACADEMY wordmark
    paper: "#fbfbf7",
    ink: "#0f2410",
    muted: "#55664f",
  },
  // Glacial Indifference, AGRO-AI's typeface, from the same source as
  // agroai-pilot.com. To self-host, serve the OFL font files and point
  // fontStylesheet at a local stylesheet; the CSP follows this setting.
  fontStylesheet: "https://fonts.cdnfonts.com/css/glacial-indifference-2",
  // Logo assets under /static/brand/.
  logo: {
    horizontal: "brand/academy-lockup-h.webp",
    horizontalLight: "brand/academy-lockup-h-light.webp",
    stacked: "brand/academy-lockup.webp",
    stackedLight: "brand/academy-lockup-light.webp",
    mark: (size) => `brand/academy-mark-${size}.png`,
    email: "brand/email-lockup.png",
    social: "brand/og-academy.png",
    appleTouch: "brand/apple-touch-icon.png",
  },
  // Intrinsic size of the horizontal lockup (for width/height attributes).
  horizontalSize: { width: 326, height: 112 },
  stackedSize: { width: 560, height: 594 },
};

/** Origin of the brand font, if hosted elsewhere (allowed by the CSP). */
export const fontOrigin = BRAND.fontStylesheet.startsWith("https://") ? new URL(BRAND.fontStylesheet).origin : null;
