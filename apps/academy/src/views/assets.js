// Versioned URLs for files under /static/. Bump BUILD whenever static files
// change: they are served as immutable for a year under ?v=<BUILD>.
export const BUILD = "2026.10.25b";

export const asset = (p) => `/static/${p}?v=${BUILD}`;
