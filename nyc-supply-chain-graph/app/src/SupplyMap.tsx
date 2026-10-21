import { LngLatBounds, Map as MapLibreMap, Marker, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef } from "react";
import type { Graph, Link, Parcel, UpstreamRow } from "@/data";

// Free vector tiles with no key: https://openfreemap.org
const STYLE = "https://tiles.openfreemap.org/styles/positron";
// MapLibre 6 runs its tile worker from a separate module that Vite has to bundle and point it at.
setWorkerUrl(workerUrl);

export function floodColor(zone: string | null): string {
  if (zone === "VE" || zone === "AE" || zone === "A" || zone === "AO") return "#dc2626";
  if (zone === "X 0.2%") return "#f59e0b";
  return "#64748b";
}

type Props = { graph: Graph; parcel: Parcel; rows: UpstreamRow[]; links: Link[] };

export function SupplyMap({ graph, parcel, rows, links }: Props) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const at = (name: string) => graph.locations[name];
    const facilities = rows.flatMap((row) => {
      const point = at(row.upstream);
      if (!point) return [];
      return [
        {
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: point },
          properties: { name: `${row.rank}. ${row.upstream}`, color: floodColor(row.flood_zone) },
        },
      ];
    });
    const lines = links.flatMap((link) => {
      const from = at(link.supplier);
      const to = at(link.consumer);
      if (!from || !to) return [];
      const tie = link.source === "nyiso-bps";
      return [
        {
          type: "Feature" as const,
          geometry: { type: "LineString" as const, coordinates: [from, to] },
          properties: { inferred: link.status === "inferred", tie },
        },
      ];
    });
    const points = [...facilities.map((f) => f.geometry.coordinates), ...(parcel.location ? [parcel.location] : [])];
    const bounds = new LngLatBounds();
    for (const point of points) bounds.extend(point);

    const map = new MapLibreMap({
      container: container.current,
      style: STYLE,
      bounds,
      fitBoundsOptions: { padding: 40 },
    });
    map.on("load", () => {
      map.addSource("links", { type: "geojson", data: { type: "FeatureCollection", features: lines } });
      map.addLayer({
        id: "links",
        type: "line",
        source: "links",
        paint: {
          "line-color": ["case", ["get", "tie"], "#94a3b8", "#334155"],
          "line-width": 2,
          "line-dasharray": ["case", ["get", "inferred"], ["literal", [2, 2]], ["literal", [1, 0]]],
        },
      });
      map.addSource("facilities", { type: "geojson", data: { type: "FeatureCollection", features: facilities } });
      map.addLayer({
        id: "facilities",
        type: "circle",
        source: "facilities",
        paint: {
          "circle-radius": 7,
          "circle-color": ["get", "color"],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "facility-names",
        type: "symbol",
        source: "facilities",
        layout: { "text-field": ["get", "name"], "text-size": 12, "text-offset": [0, 1.2], "text-anchor": "top" },
        paint: { "text-halo-color": "#fff", "text-halo-width": 1.5 },
      });
    });
    // Tells the browser test the tiles and layers have drawn.
    map.once("idle", () => container.current?.setAttribute("data-ready", "true"));
    if (parcel.location) new Marker({ color: "#2563eb" }).setLngLat(parcel.location).addTo(map);
    return () => map.remove();
  }, [graph, parcel, rows, links]);

  return <div ref={container} className="h-[480px] w-full rounded-lg border" data-testid="map" />;
}
