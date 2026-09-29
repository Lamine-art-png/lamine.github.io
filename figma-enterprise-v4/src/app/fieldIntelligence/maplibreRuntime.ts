// MapLibre GL 6 runs tiles in a module web worker that it resolves relative to
// its own module. Bundled by Vite, that relative URL does not exist, so the
// worker is bundled explicitly (?worker&url) and registered before any map is
// created.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

let configured: Promise<typeof import("maplibre-gl")> | null = null;

export function loadMaplibre(): Promise<typeof import("maplibre-gl")> {
  if (!configured) {
    configured = import("maplibre-gl").then((maplibre) => {
      maplibre.setWorkerUrl(maplibreWorkerUrl);
      return maplibre;
    });
  }
  return configured;
}
