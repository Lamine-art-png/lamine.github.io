import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapPin } from "lucide-react";
import { apiClient } from "../api/client";

/**
 * Production MapLibre field map.
 *
 * The style URL comes from the backend (`/map` -> map_style_url), never from a
 * client-side secret. Observations render as severity-colored, clustered pins;
 * selection is synchronized with the timeline through `selectedId`/`onSelect`.
 * When no style is configured or the browser cannot run WebGL the component
 * degrades to the accessible list fallback, and the fallback also renders when
 * no observation carries a location.
 */

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#B23B2E",
  high: "#D97706",
  medium: "#B7950B",
  low: "#2D6A4F",
  info: "#4A7A63",
};

type Observation = Record<string, any>;

type Props = {
  t: (key: string) => string;
  observations: Observation[];
  selectedId?: string | null;
  onSelect?: (observation: Observation) => void;
  workspaceId?: string;
};

function toGeoJSON(observations: Observation[]) {
  return {
    type: "FeatureCollection" as const,
    features: observations
      .filter((o) => o.location && Number.isFinite(o.location.latitude) && Number.isFinite(o.location.longitude))
      .map((o) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [o.location.longitude, o.location.latitude] },
        properties: {
          id: o.id,
          severity: (o.severity || "info").toLowerCase(),
          color: SEVERITY_COLORS[(o.severity || "info").toLowerCase()] || SEVERITY_COLORS.info,
          hasMedia: Array.isArray(o.assets) && o.assets.length > 0 ? 1 : 0,
          fieldName: o.field_name || "",
        },
      })),
  };
}

export function FieldMap({ t, observations, selectedId, onSelect, workspaceId }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const [styleUrl, setStyleUrl] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapFailed, setMapFailed] = useState(false);

  const geojson = useMemo(() => toGeoJSON(observations), [observations]);
  const hasPoints = geojson.features.length > 0;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res: any = await apiClient.fieldIntelligence.map(workspaceId);
        if (!cancelled) setStyleUrl(res?.map_style_configured ? res.map_style_url : null);
      } catch {
        if (!cancelled) setStyleUrl(null);
      }
    })();
    return () => { cancelled = true; };
  }, [workspaceId]);

  const syncData = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource("fi-observations");
    if (source) source.setData(geojson);
    if (geojson.features.length > 0) {
      const lons = geojson.features.map((f) => f.geometry.coordinates[0]);
      const lats = geojson.features.map((f) => f.geometry.coordinates[1]);
      map.fitBounds(
        [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
        { padding: 56, maxZoom: 14, duration: 400 },
      );
    }
  }, [geojson]);

  useEffect(() => {
    if (!styleUrl || !hasPoints || !containerRef.current || mapRef.current) return;
    let disposed = false;
    (async () => {
      try {
        const maplibre = await import("maplibre-gl");
        // @ts-ignore vite handles css imports
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !containerRef.current) return;
        const map = new maplibre.Map({
          container: containerRef.current,
          style: styleUrl,
          center: [geojson.features[0].geometry.coordinates[0], geojson.features[0].geometry.coordinates[1]],
          zoom: 11,
          attributionControl: { compact: true } as any,
        });
        mapRef.current = map;
        map.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
        map.on("error", () => setMapFailed(true));
        map.on("load", () => {
          map.addSource("fi-observations", {
            type: "geojson", data: geojson, cluster: true, clusterMaxZoom: 13, clusterRadius: 44,
          });
          map.addLayer({
            id: "fi-clusters", type: "circle", source: "fi-observations",
            filter: ["has", "point_count"],
            paint: {
              "circle-color": "#2D6A4F", "circle-opacity": 0.85,
              "circle-radius": ["step", ["get", "point_count"], 16, 10, 22, 50, 28],
            },
          });
          map.addLayer({
            id: "fi-cluster-count", type: "symbol", source: "fi-observations",
            filter: ["has", "point_count"],
            layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12 },
            paint: { "text-color": "#FFFFFF" },
          });
          map.addLayer({
            id: "fi-points", type: "circle", source: "fi-observations",
            filter: ["!", ["has", "point_count"]],
            paint: {
              "circle-color": ["get", "color"],
              "circle-radius": ["case", ["==", ["get", "hasMedia"], 1], 9, 7],
              "circle-stroke-width": 2,
              "circle-stroke-color": "#FFFFFF",
            },
          });
          map.on("click", "fi-points", (event: any) => {
            const feature = event.features?.[0];
            const id = feature?.properties?.id;
            const observation = observations.find((o) => o.id === id);
            if (observation && onSelect) onSelect(observation);
          });
          map.on("click", "fi-clusters", async (event: any) => {
            const feature = event.features?.[0];
            const source: any = map.getSource("fi-observations");
            const zoom = await source.getClusterExpansionZoom(feature.properties.cluster_id);
            map.easeTo({ center: feature.geometry.coordinates, zoom });
          });
          map.on("mouseenter", "fi-points", () => { map.getCanvas().style.cursor = "pointer"; });
          map.on("mouseleave", "fi-points", () => { map.getCanvas().style.cursor = ""; });
          setMapReady(true);
          syncData();
        });
      } catch {
        setMapFailed(true);
      }
    })();
    return () => {
      disposed = true;
      if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }
      setMapReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [styleUrl, hasPoints]);

  useEffect(() => { if (mapReady) syncData(); }, [mapReady, syncData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !selectedId) return;
    const feature = geojson.features.find((f) => f.properties.id === selectedId);
    if (feature) map.easeTo({ center: feature.geometry.coordinates as any, zoom: Math.max(map.getZoom(), 13) });
  }, [selectedId, mapReady, geojson]);

  if (!hasPoints || !styleUrl || mapFailed) {
    return (
      <div className="rounded-xl border border-[#D6DDD0] bg-[#F2F5F0] p-4" role="region" aria-label={t("fieldIntel.map")}>
        <div className="flex items-center gap-2 text-[13px] font-semibold text-[#10231B]">
          <MapPin className="h-4 w-4" aria-hidden /> {t("fieldIntel.mapFallback")}
        </div>
        {!hasPoints ? (
          <p className="mt-3 text-[13px] text-[#65736A]">{t("fieldIntel.noGeolocated")}</p>
        ) : (
          <ul className="mt-3 space-y-1">
            {geojson.features.map((feature) => {
              const observation = observations.find((o) => o.id === feature.properties.id);
              return (
                <li key={feature.properties.id}>
                  <button
                    type="button"
                    onClick={() => observation && onSelect?.(observation)}
                    className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-[12px] text-[#3B4A41] hover:bg-white"
                  >
                    <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full"
                      style={{ background: feature.properties.color }} />
                    <span>{feature.properties.fieldName || t("fieldIntel.unassignedField")}</span>
                    <span className="text-[#9AA79E]">
                      {feature.geometry.coordinates[1].toFixed(4)}, {feature.geometry.coordinates[0].toFixed(4)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-[#D6DDD0]">
      <div ref={containerRef} className="h-[420px] w-full" role="region" aria-label={t("fieldIntel.map")} />
      <div className="flex flex-wrap items-center gap-3 border-t border-[#D6DDD0] bg-white px-3 py-2">
        {Object.entries(SEVERITY_COLORS).map(([severity, color]) => (
          <span key={severity} className="inline-flex items-center gap-1 text-[11px] text-[#3B4A41]">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
            {t(`fieldIntel.sev.${severity}`)}
          </span>
        ))}
      </div>
    </div>
  );
}
