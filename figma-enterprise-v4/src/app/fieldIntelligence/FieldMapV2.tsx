import { useEffect, useMemo, useRef, useState } from "react";
import { LocateFixed, MapPin } from "lucide-react";
import { apiClient } from "../api/client";

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

const DEFAULT_MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

function coordinates(observation: Observation): [number, number] | null {
  const latitude = Number(observation.location?.latitude ?? observation.latitude);
  const longitude = Number(observation.location?.longitude ?? observation.longitude);
  return Number.isFinite(latitude) && Number.isFinite(longitude) ? [longitude, latitude] : null;
}

function toGeoJSON(observations: Observation[]) {
  return {
    type: "FeatureCollection" as const,
    features: observations.flatMap((observation) => {
      const point = coordinates(observation);
      if (!point) return [];
      const severity = String(observation.severity || "info").toLowerCase();
      return [{
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: point },
        properties: {
          id: observation.id,
          severity,
          color: SEVERITY_COLORS[severity] || SEVERITY_COLORS.info,
          hasMedia: Array.isArray(observation.assets) && observation.assets.length > 0 ? 1 : 0,
          fieldName: observation.field_name || "",
        },
      }];
    }),
  };
}

export function FieldMapV2({ t, observations, selectedId, onSelect, workspaceId }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const markerRef = useRef<any>(null);
  const [style, setStyle] = useState<any>(DEFAULT_MAP_STYLE);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [currentLocation, setCurrentLocation] = useState<[number, number] | null>(null);
  const geojson = useMemo(() => toGeoJSON(observations), [observations]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response: any = await apiClient.fieldIntelligence.map(workspaceId);
        if (!cancelled && response?.map_style_configured && response.map_style_url) {
          setStyle(response.map_style_url);
        }
      } catch {
        // The public vector fallback keeps the map functional without a token.
      }
    })();
    return () => { cancelled = true; };
  }, [workspaceId]);

  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (position) => setCurrentLocation([position.coords.longitude, position.coords.latitude]),
      () => {},
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  }, []);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    let disposed = false;
    (async () => {
      try {
        const maplibre = await import("maplibre-gl");
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !containerRef.current) return;
        const first = geojson.features[0]?.geometry.coordinates as [number, number] | undefined;
        const center = currentLocation || first || [-98.5795, 39.8283];
        const map = new maplibre.Map({
          container: containerRef.current,
          style,
          center,
          zoom: currentLocation || first ? 12 : 3,
          attributionControl: { compact: true } as any,
        });
        mapRef.current = map;
        map.addControl(new maplibre.NavigationControl(), "top-right");
        map.addControl(new maplibre.GeolocateControl({
          positionOptions: { enableHighAccuracy: true },
          trackUserLocation: true,
          showUserHeading: true,
        }), "top-right");
        map.on("load", () => {
          map.addSource("fi-observations", {
            type: "geojson",
            data: geojson,
            cluster: true,
            clusterMaxZoom: 13,
            clusterRadius: 46,
          });
          map.addLayer({
            id: "fi-clusters",
            type: "circle",
            source: "fi-observations",
            filter: ["has", "point_count"],
            paint: {
              "circle-color": "#2D6A4F",
              "circle-opacity": 0.88,
              "circle-radius": ["step", ["get", "point_count"], 18, 10, 23, 50, 29],
              "circle-stroke-width": 2,
              "circle-stroke-color": "#FFFFFF",
            },
          });
          map.addLayer({
            id: "fi-cluster-count",
            type: "symbol",
            source: "fi-observations",
            filter: ["has", "point_count"],
            layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12 },
            paint: { "text-color": "#FFFFFF" },
          });
          map.addLayer({
            id: "fi-points",
            type: "circle",
            source: "fi-observations",
            filter: ["!", ["has", "point_count"]],
            paint: {
              "circle-color": ["get", "color"],
              "circle-radius": ["case", ["==", ["get", "hasMedia"], 1], 10, 8],
              "circle-stroke-width": 3,
              "circle-stroke-color": "#FFFFFF",
            },
          });
          map.on("click", "fi-points", (event: any) => {
            const id = event.features?.[0]?.properties?.id;
            const observation = observations.find((item) => item.id === id);
            if (observation) onSelect?.(observation);
          });
          map.on("click", "fi-clusters", async (event: any) => {
            const feature = event.features?.[0];
            const source: any = map.getSource("fi-observations");
            const zoom = await source.getClusterExpansionZoom(feature.properties.cluster_id);
            map.easeTo({ center: feature.geometry.coordinates, zoom });
          });
          map.on("mouseenter", "fi-points", () => { map.getCanvas().style.cursor = "pointer"; });
          map.on("mouseleave", "fi-points", () => { map.getCanvas().style.cursor = ""; });
          setReady(true);
        });
      } catch {
        setFailed(true);
      }
    })();
    return () => {
      disposed = true;
      markerRef.current?.remove?.();
      markerRef.current = null;
      mapRef.current?.remove?.();
      mapRef.current = null;
      setReady(false);
    };
    // A style change should rebuild the map; data is synchronized separately.
  }, [style]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource("fi-observations");
    source?.setData?.(geojson);
    if (geojson.features.length) {
      const longitudes = geojson.features.map((feature) => feature.geometry.coordinates[0]);
      const latitudes = geojson.features.map((feature) => feature.geometry.coordinates[1]);
      map.fitBounds(
        [[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]],
        { padding: 70, maxZoom: 15, duration: 500 },
      );
    }
  }, [geojson, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !currentLocation) return;
    (async () => {
      const maplibre = await import("maplibre-gl");
      markerRef.current?.remove?.();
      const node = document.createElement("div");
      node.className = "h-4 w-4 rounded-full border-2 border-white bg-[#1976D2] shadow";
      markerRef.current = new maplibre.Marker({ element: node }).setLngLat(currentLocation).addTo(map);
    })();
  }, [currentLocation, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !selectedId) return;
    const feature = geojson.features.find((item) => item.properties.id === selectedId);
    if (feature) map.easeTo({ center: feature.geometry.coordinates as [number, number], zoom: Math.max(map.getZoom(), 14) });
  }, [selectedId, ready, geojson]);

  if (failed) {
    return <div className="rounded-xl border border-[#D6DDD0] bg-[#F2F5F0] p-4" role="region" aria-label={t("fieldIntel.map")}>
      <div className="flex items-center gap-2 text-[13px] font-semibold text-[#10231B]"><MapPin className="h-4 w-4" />{t("fieldIntel.mapFallback")}</div>
      <ul className="mt-3 space-y-1">
        {geojson.features.map((feature) => <li key={feature.properties.id}>
          <button type="button" onClick={() => { const observation = observations.find((item) => item.id === feature.properties.id); if (observation) onSelect?.(observation); }}
            className="flex w-full items-center gap-2 rounded px-1 py-1 text-left text-[12px] text-[#3B4A41] hover:bg-white">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: feature.properties.color }} />
            {feature.properties.fieldName || t("fieldIntel.unassignedField")}
          </button>
        </li>)}
      </ul>
    </div>;
  }

  return <div className="overflow-hidden rounded-xl border border-[#D6DDD0]">
    <div className="relative">
      <div ref={containerRef} className="h-[520px] w-full" role="region" aria-label={t("fieldIntel.map")} />
      {!geojson.features.length && <div className="pointer-events-none absolute bottom-4 left-4 right-4 rounded-xl border border-white/70 bg-white/90 p-3 shadow-lg backdrop-blur">
        <div className="flex items-center gap-2 text-[13px] font-semibold text-[#10231B]"><LocateFixed className="h-4 w-4 text-[#2D6A4F]" />{t("fieldIntel.map")}</div>
        <p className="mt-1 text-[12px] text-[#65736A]">{t("fieldIntel.noGeolocated")}</p>
      </div>}
    </div>
    <div className="flex flex-wrap items-center gap-3 border-t border-[#D6DDD0] bg-white px-3 py-2">
      {Object.entries(SEVERITY_COLORS).map(([severity, color]) => <span key={severity} className="inline-flex items-center gap-1 text-[11px] text-[#3B4A41]">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />{t(`fieldIntel.sev.${severity}`)}
      </span>)}
    </div>
  </div>;
}
