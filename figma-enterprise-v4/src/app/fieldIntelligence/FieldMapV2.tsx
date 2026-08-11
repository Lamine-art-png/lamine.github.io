import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Clock3, LocateFixed, MapPin, Navigation, Sparkles, Loader2 } from "lucide-react";
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

type Point = {
  observation: Observation;
  coordinates: [number, number];
  severity: string;
};

const DEFAULT_MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const ACTIONABLE_SEVERITIES = new Set(["critical", "high", "medium"]);

function coordinates(observation: Observation): [number, number] | null {
  const latitude = Number(observation.location?.latitude ?? observation.latitude);
  const longitude = Number(observation.location?.longitude ?? observation.longitude);
  return Number.isFinite(latitude) && Number.isFinite(longitude) ? [longitude, latitude] : null;
}

function safeText(value: unknown): string {
  if (typeof value === "string") {
    const text = value.replace(/\s+/g, " ").trim();
    return text.toLowerCase() === "[object object]" ? "" : text;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const key of ["summary", "text", "label", "message", "description"]) {
      const candidate = safeText(record[key]);
      if (candidate) return candidate;
    }
  }
  return "";
}

function summaryFor(observation: Observation): string {
  const vision = observation?.structured?.vision || observation?.structured_json?.vision || {};
  return safeText(observation.summary)
    || safeText(vision.summary)
    || safeText(observation.corrected_transcript)
    || safeText(observation.transcript);
}

function recommendationFor(observation: Observation): string {
  const vision = observation?.structured?.vision || observation?.structured_json?.vision || {};
  const correlation = observation?.correlation || observation?.correlation_json || {};
  return safeText(observation.recommended_action)
    || safeText(vision.recommended_follow_up)
    || safeText(correlation.recommended_next_action);
}

function taskIds(observation: Observation): string[] {
  const values = observation.task_ids || observation.task_ids_json || [];
  return Array.isArray(values) ? values.map((value) => String(value || "")).filter(Boolean) : [];
}

function pointData(observations: Observation[]): Point[] {
  return observations.flatMap((observation) => {
    const point = coordinates(observation);
    if (!point) return [];
    return [{
      observation,
      coordinates: point,
      severity: String(observation.severity || "info").toLowerCase(),
    }];
  });
}

function toGeoJSON(points: Point[]) {
  return {
    type: "FeatureCollection" as const,
    features: points.map(({ observation, coordinates: point, severity }) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: point },
      properties: {
        id: String(observation.id || ""),
        severity,
        color: SEVERITY_COLORS[severity] || SEVERITY_COLORS.info,
        hasMedia: Array.isArray(observation.assets) && observation.assets.length > 0 ? 1 : 0,
        hasTask: taskIds(observation).length > 0 ? 1 : 0,
        fieldName: safeText(observation.field_name),
        blockName: safeText(observation.block_name),
      },
    })),
  };
}

function isActionable(observation: Observation): boolean {
  const severity = String(observation.severity || "info").toLowerCase();
  return taskIds(observation).length === 0
    && (ACTIONABLE_SEVERITIES.has(severity) || Boolean(recommendationFor(observation)));
}

function occurredAt(observation: Observation): number {
  const value = observation.occurred_at || observation.observed_at || observation.created_at;
  const timestamp = value ? new Date(value).getTime() : 0;
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function formatWhen(observation: Observation): string {
  const value = observation.occurred_at || observation.observed_at || observation.created_at;
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

export function FieldMapV2({ t, observations, selectedId, onSelect, workspaceId }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const currentMarkerRef = useRef<any>(null);
  const popupRef = useRef<any>(null);
  const [style, setStyle] = useState<any>(DEFAULT_MAP_STYLE);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [locationState, setLocationState] = useState<"checking" | "ready" | "unavailable">("checking");
  const [currentLocation, setCurrentLocation] = useState<[number, number] | null>(null);
  const [focusedId, setFocusedId] = useState<string>(String(selectedId || ""));
  const [creatingTask, setCreatingTask] = useState(false);
  const [createdTaskIds, setCreatedTaskIds] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState("");

  const points = useMemo(() => pointData(observations), [observations]);
  const geojson = useMemo(() => toGeoJSON(points), [points]);
  const pointById = useMemo(() => new Map(points.map((point) => [String(point.observation.id), point])), [points]);
  const pointByIdRef = useRef(pointById);
  useEffect(() => { pointByIdRef.current = pointById; }, [pointById]);
  const recentPoints = useMemo(() => [...points].sort((a, b) => occurredAt(b.observation) - occurredAt(a.observation)), [points]);
  const actionableCount = useMemo(() => points.filter((point) => isActionable(point.observation)).length, [points]);
  const linkedTaskCount = useMemo(() => points.filter((point) => taskIds(point.observation).length > 0).length, [points]);
  const mediaCount = useMemo(() => points.filter((point) => Array.isArray(point.observation.assets) && point.observation.assets.length > 0).length, [points]);
  const focused = focusedId ? pointById.get(focusedId)?.observation || null : null;
  const anchor = points[0]?.coordinates || currentLocation || null;
  const anchorKey = anchor ? `${anchor[0].toFixed(6)},${anchor[1].toFixed(6)}` : "";

  const requestCurrentLocation = () => {
    if (!navigator.geolocation) {
      setLocationState("unavailable");
      return;
    }
    setLocationState("checking");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCurrentLocation([position.coords.longitude, position.coords.latitude]);
        setLocationState("ready");
      },
      () => setLocationState("unavailable"),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  };

  useEffect(() => { requestCurrentLocation(); }, []);
  useEffect(() => {
    if (selectedId) setFocusedId(String(selectedId));
  }, [selectedId]);

  useEffect(() => {
    if (focusedId && !pointById.has(focusedId)) setFocusedId("");
  }, [focusedId, pointById]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response: any = await apiClient.fieldIntelligence.map(workspaceId);
        if (!cancelled && response?.map_style_configured && response.map_style_url) setStyle(response.map_style_url);
      } catch {
        // Public vector fallback keeps the spatial workspace available.
      }
    })();
    return () => { cancelled = true; };
  }, [workspaceId]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current || !anchor) return;
    let disposed = false;
    (async () => {
      try {
        const maplibre = await import("maplibre-gl");
        await import("maplibre-gl/dist/maplibre-gl.css");
        if (disposed || !containerRef.current) return;
        const map = new maplibre.Map({
          container: containerRef.current,
          style,
          center: anchor,
          zoom: 16,
          attributionControl: { compact: true } as any,
        });
        mapRef.current = map;
        map.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
        map.addControl(new maplibre.GeolocateControl({
          positionOptions: { enableHighAccuracy: true },
          trackUserLocation: true,
          showUserHeading: true,
          showAccuracyCircle: true,
        }), "top-right");
        map.on("load", () => {
          if (disposed) return;
          map.addSource("fi-observations", { type: "geojson", data: geojson, cluster: true, clusterMaxZoom: 14, clusterRadius: 44 });
          map.addLayer({
            id: "fi-clusters",
            type: "circle",
            source: "fi-observations",
            filter: ["has", "point_count"],
            paint: {
              "circle-color": "#173F2B",
              "circle-opacity": 0.92,
              "circle-radius": ["step", ["get", "point_count"], 18, 10, 23, 50, 29],
              "circle-stroke-width": 3,
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
              "circle-radius": ["case", ["==", ["get", "hasTask"], 1], 10, ["==", ["get", "hasMedia"], 1], 9, 8],
              "circle-stroke-width": 3,
              "circle-stroke-color": "#FFFFFF",
            },
          });
          map.addLayer({
            id: "fi-selected",
            type: "circle",
            source: "fi-observations",
            filter: ["==", ["get", "id"], focusedId || "__none__"],
            paint: {
              "circle-color": "rgba(255,255,255,0)",
              "circle-radius": 16,
              "circle-stroke-width": 3,
              "circle-stroke-color": "#10231B",
            },
          });
          map.on("click", "fi-points", (event: any) => {
            const id = String(event.features?.[0]?.properties?.id || "");
            if (id) setFocusedId(id);
          });
          map.on("click", "fi-clusters", async (event: any) => {
            const feature = event.features?.[0];
            const source: any = map.getSource("fi-observations");
            const zoom = await source.getClusterExpansionZoom(feature.properties.cluster_id);
            map.easeTo({ center: feature.geometry.coordinates, zoom });
          });
          map.on("mouseenter", "fi-points", (event: any) => {
            map.getCanvas().style.cursor = "pointer";
            const id = String(event.features?.[0]?.properties?.id || "");
            const observation = pointByIdRef.current.get(id)?.observation;
            if (!observation) return;
            const node = document.createElement("div");
            node.style.maxWidth = "240px";
            node.style.fontSize = "12px";
            node.style.lineHeight = "1.45";
            const title = document.createElement("div");
            title.style.fontWeight = "700";
            title.style.color = "#10231B";
            title.textContent = safeText(observation.field_name) || t("fieldIntel.unassignedField");
            const summary = document.createElement("div");
            summary.style.marginTop = "4px";
            summary.style.color = "#536158";
            summary.textContent = summaryFor(observation).slice(0, 180) || t("fieldIntel.needsReview");
            node.append(title, summary);
            popupRef.current?.remove?.();
            popupRef.current = new maplibre.Popup({ closeButton: false, closeOnClick: false, offset: 16 })
              .setLngLat(event.features?.[0]?.geometry?.coordinates)
              .setDOMContent(node)
              .addTo(map);
          });
          map.on("mouseleave", "fi-points", () => {
            map.getCanvas().style.cursor = "";
            popupRef.current?.remove?.();
            popupRef.current = null;
          });
          setReady(true);
        });
      } catch {
        setFailed(true);
      }
    })();
    return () => {
      disposed = true;
      popupRef.current?.remove?.();
      popupRef.current = null;
      currentMarkerRef.current?.remove?.();
      currentMarkerRef.current = null;
      mapRef.current?.remove?.();
      mapRef.current = null;
      setReady(false);
    };
  }, [style, anchorKey]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.getSource("fi-observations")?.setData?.(geojson);
    if (points.length === 1) {
      map.easeTo({ center: points[0].coordinates, zoom: 16, duration: 450 });
      return;
    }
    if (points.length > 1) {
      const longitudes = points.map((point) => point.coordinates[0]);
      const latitudes = points.map((point) => point.coordinates[1]);
      map.fitBounds(
        [[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]],
        { padding: 70, maxZoom: 16, duration: 500 },
      );
      return;
    }
    if (currentLocation) map.easeTo({ center: currentLocation, zoom: 16, duration: 450 });
  }, [geojson, points, currentLocation, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setFilter("fi-selected", ["==", ["get", "id"], focusedId || "__none__"]);
    const point = focusedId ? pointById.get(focusedId) : null;
    if (point) map.easeTo({ center: point.coordinates, zoom: Math.max(map.getZoom(), 15), duration: 350 });
  }, [focusedId, pointById, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !currentLocation) return;
    (async () => {
      const maplibre = await import("maplibre-gl");
      currentMarkerRef.current?.remove?.();
      const node = document.createElement("div");
      node.className = "h-4 w-4 rounded-full border-[3px] border-white bg-[#1976D2] shadow-lg";
      currentMarkerRef.current = new maplibre.Marker({ element: node }).setLngLat(currentLocation).addTo(map);
    })();
  }, [currentLocation, ready]);

  const focusActivity = () => {
    const map = mapRef.current;
    if (!map) return;
    if (points.length === 1) map.easeTo({ center: points[0].coordinates, zoom: 16 });
    else if (points.length > 1) {
      const longitudes = points.map((point) => point.coordinates[0]);
      const latitudes = points.map((point) => point.coordinates[1]);
      map.fitBounds([[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]], { padding: 70, maxZoom: 16 });
    } else if (currentLocation) map.easeTo({ center: currentLocation, zoom: 16 });
  };

  const createTask = async (observation: Observation) => {
    setCreatingTask(true);
    setActionError("");
    try {
      const response: any = await apiClient.fieldIntelligence.createTask(observation.id, {});
      const task = response?.task || response;
      if (!task?.id) throw new Error("task_missing");
      setCreatedTaskIds((current) => ({ ...current, [String(observation.id)]: String(task.id) }));
    } catch {
      setActionError(t("fieldIntel.needsReview"));
    } finally {
      setCreatingTask(false);
    }
  };

  if (!anchor && locationState !== "checking") {
    return <div className="flex min-h-[520px] items-center justify-center rounded-xl border border-[#D6DDD0] bg-[#F7F8F5] p-8 text-center" role="region" aria-label={t("fieldIntel.map")}>
      <div className="max-w-sm">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[#E8F2EC]"><MapPin className="h-6 w-6 text-[#2D6A4F]" /></div>
        <div className="mt-4 text-[14px] font-semibold text-[#10231B]">{t("fieldIntel.noGeolocated")}</div>
        <button type="button" onClick={requestCurrentLocation} className="mt-4 inline-flex min-h-[42px] items-center gap-2 rounded-lg border border-[#D6DDD0] bg-white px-4 text-[12px] font-semibold text-[#10231B]">
          <LocateFixed className="h-4 w-4 text-[#2D6A4F]" />{t("fieldIntel.captureLocation")}
        </button>
      </div>
    </div>;
  }

  if (failed) {
    return <div className="rounded-xl border border-[#D6DDD0] bg-[#F2F5F0] p-4" role="region" aria-label={t("fieldIntel.map")}>
      <div className="flex items-center gap-2 text-[13px] font-semibold text-[#10231B]"><MapPin className="h-4 w-4" />{t("fieldIntel.mapFallback")}</div>
      <div className="mt-3 space-y-2">
        {recentPoints.slice(0, 8).map((point) => <button key={point.observation.id} type="button" onClick={() => onSelect?.(point.observation)} className="flex w-full items-start gap-2 rounded-lg border border-[#D6DDD0] bg-white p-3 text-left">
          <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SEVERITY_COLORS[point.severity] || SEVERITY_COLORS.info }} />
          <span><span className="block text-[12px] font-semibold text-[#10231B]">{safeText(point.observation.field_name) || t("fieldIntel.unassignedField")}</span><span className="mt-1 block line-clamp-2 text-[11px] text-[#65736A]">{summaryFor(point.observation) || t("fieldIntel.needsReview")}</span></span>
        </button>)}
      </div>
    </div>;
  }

  const existingTaskId = focused ? taskIds(focused)[0] || createdTaskIds[String(focused.id)] || "" : "";
  const focusedSummary = focused ? summaryFor(focused) : "";
  const focusedRecommendation = focused ? recommendationFor(focused) : "";

  return <div className="overflow-hidden rounded-xl border border-[#D6DDD0] bg-[#F7F8F5]">
    <div className="grid min-h-[520px] lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="relative min-h-[420px] bg-[#E8ECE7] lg:min-h-[520px]">
        <div ref={containerRef} className="absolute inset-0" role="region" aria-label={t("fieldIntel.map")} />
        {!ready && <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-[#F4F6F2]/75"><Loader2 className="h-6 w-6 animate-spin text-[#2D6A4F]" /></div>}
        <div className="absolute left-3 top-3 flex gap-2">
          <button type="button" onClick={focusActivity} title={t("fieldIntel.map")} className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/80 bg-white/95 text-[#10231B] shadow"><Navigation className="h-4 w-4" /></button>
          <button type="button" onClick={() => { requestCurrentLocation(); if (currentLocation) mapRef.current?.easeTo?.({ center: currentLocation, zoom: 16 }); }} title={t("fieldIntel.captureLocation")} className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/80 bg-white/95 text-[#10231B] shadow"><LocateFixed className="h-4 w-4" /></button>
        </div>
        {!points.length && <div className="pointer-events-none absolute bottom-3 left-3 right-3 rounded-xl border border-white/70 bg-white/92 p-3 shadow-lg backdrop-blur">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#10231B]"><MapPin className="h-4 w-4 text-[#2D6A4F]" />{t("fieldIntel.noGeolocated")}</div>
        </div>}
      </div>

      <aside className="border-t border-[#D6DDD0] bg-white p-4 lg:border-l lg:border-t-0">
        <div className="grid grid-cols-3 gap-2">
          <Metric value={points.length} label={t("fieldIntel.map")} />
          <Metric value={actionableCount} label={t("fieldIntel.recommended")} />
          <Metric value={linkedTaskCount} label={t("tasks")} />
        </div>
        <div className="mt-2"><Metric value={mediaCount} label={t("fieldIntel.attachments")} wide /></div>

        {focused ? <div className="mt-4 rounded-xl border border-[#BFD8C9] bg-[#F3F8F5] p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[13px] font-semibold text-[#10231B]">{safeText(focused.field_name) || t("fieldIntel.unassignedField")}</div>
              {safeText(focused.block_name) && <div className="mt-0.5 truncate text-[11px] text-[#65736A]">{safeText(focused.block_name)}</div>}
            </div>
            <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SEVERITY_COLORS[String(focused.severity || "info").toLowerCase()] || SEVERITY_COLORS.info }} />
          </div>
          {formatWhen(focused) && <div className="mt-2 flex items-center gap-1 text-[10px] text-[#7A877F]"><Clock3 className="h-3 w-3" />{formatWhen(focused)}</div>}
          <p className="mt-2 line-clamp-4 text-[12px] leading-5 text-[#3B4A41]">{focusedSummary || t("fieldIntel.needsReview")}</p>
          {focusedRecommendation && <div className="mt-3 rounded-lg border border-[#D6DDD0] bg-white p-2.5"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#2D6A4F]">{t("fieldIntel.recommended")}</div><p className="mt-1 text-[11px] leading-5 text-[#3B4A41]">{focusedRecommendation}</p></div>}
          {actionError && <p className="mt-2 text-[11px] text-[#B23B2E]">{actionError}</p>}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button type="button" onClick={() => onSelect?.(focused)} className="min-h-[40px] rounded-lg border border-[#D6DDD0] bg-white px-2 text-[11px] font-semibold text-[#10231B]">{t("fieldIntel.reviewTitle")}</button>
            <a href={`/intelligence?field_observation_id=${encodeURIComponent(String(focused.id))}&source=field-intelligence-map`} className="inline-flex min-h-[40px] items-center justify-center gap-1 rounded-lg bg-[#0D2B1E] px-2 text-[11px] font-semibold text-white"><Sparkles className="h-3.5 w-3.5" />{t("askAgroAi")}</a>
          </div>
          {existingTaskId ? <a href={`/tasks?task_id=${encodeURIComponent(existingTaskId)}&observation_id=${encodeURIComponent(String(focused.id))}`} className="mt-2 inline-flex min-h-[40px] w-full items-center justify-center gap-2 rounded-lg border border-[#9DC4AD] bg-[#EAF5EE] px-3 text-[11px] font-semibold text-[#1B5E3F]"><CheckCircle2 className="h-4 w-4" />{t("tasks")}</a>
            : <button type="button" disabled={creatingTask} onClick={() => void createTask(focused)} className="mt-2 inline-flex min-h-[40px] w-full items-center justify-center gap-2 rounded-lg border border-[#D6DDD0] bg-white px-3 text-[11px] font-semibold text-[#10231B] disabled:opacity-50">{creatingTask ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4 text-[#2D6A4F]" />}{t("fieldIntel.createTask")}</button>}
        </div> : <div className="mt-4 rounded-xl border border-dashed border-[#C9D4CC] bg-[#FAFBF9] p-4 text-center">
          <MapPin className="mx-auto h-5 w-5 text-[#2D6A4F]" />
          <p className="mt-2 text-[11px] leading-5 text-[#65736A]">{points.length ? t("fieldIntel.reviewHint") : t("fieldIntel.noGeolocated")}</p>
        </div>}

        {recentPoints.length > 0 && <div className="mt-4 space-y-1.5 border-t border-[#EEE9DE] pt-3">
          {recentPoints.slice(0, 5).map((point) => {
            const observation = point.observation;
            const active = String(observation.id) === focusedId;
            return <button key={observation.id} type="button" onClick={() => setFocusedId(String(observation.id))} className={`w-full rounded-lg border p-2.5 text-left transition ${active ? "border-[#8FC3A6] bg-[#EDF7F1]" : "border-transparent bg-[#F8F9F6] hover:border-[#D6DDD0]"}`}>
              <div className="flex items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: SEVERITY_COLORS[point.severity] || SEVERITY_COLORS.info }} /><span className="truncate text-[11px] font-semibold text-[#10231B]">{safeText(observation.field_name) || t("fieldIntel.unassignedField")}</span>{taskIds(observation).length > 0 && <CheckCircle2 className="ml-auto h-3.5 w-3.5 shrink-0 text-[#2D6A4F]" />}</div>
              <div className="mt-1 truncate pl-4 text-[10px] text-[#77847C]">{summaryFor(observation) || t("fieldIntel.needsReview")}</div>
            </button>;
          })}
        </div>}
      </aside>
    </div>
    <div className="flex flex-wrap items-center gap-3 border-t border-[#D6DDD0] bg-white px-3 py-2">
      {Object.entries(SEVERITY_COLORS).map(([severity, color]) => <span key={severity} className="inline-flex items-center gap-1 text-[10px] text-[#3B4A41]"><span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />{t(`fieldIntel.sev.${severity}`)}</span>)}
    </div>
  </div>;
}

function Metric({ value, label, wide = false }: { value: number; label: string; wide?: boolean }) {
  return <div className={`rounded-lg border border-[#E3E8E2] bg-[#FAFBF9] px-2.5 py-2 ${wide ? "flex items-center justify-between" : ""}`}>
    <div className="text-[15px] font-semibold text-[#10231B]">{value}</div>
    <div className={`${wide ? "ml-3" : "mt-0.5"} truncate text-[9px] font-medium uppercase tracking-[0.08em] text-[#78857D]`}>{label}</div>
  </div>;
}
