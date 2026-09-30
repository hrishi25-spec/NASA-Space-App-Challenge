import { useEffect, useMemo, useRef, useState } from "react";
// maplibre-gl v6 has NO default export — the ESM build only exposes named exports,
// so `import maplibregl from "maplibre-gl"` throws a SyntaxError and blanks the app.
import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// maplibre-gl resolves its GeoJSON/raster worker via `new URL(..., import.meta.url)`, which
// points into Vite's pre-bundled deps folder where no worker exists ("Worker failed to load"),
// leaving every source stuck unparsed. Hand it the worker URL Vite actually bundles.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { fmt } from "./lib";

setWorkerUrl(maplibreWorkerUrl);

// The single source of truth for the globe <-> flat-map morph. These drive BOTH the style's
// projection expression and the view badge, so the readout can never disagree with what's drawn.
const GLOBE_ZOOM = 3.7;   // at/below this zoom the Earth is a fully 3D globe
const FLAT_ZOOM = 5.2;    // at/above this zoom the map is fully flat (mercator)
const START_ZOOM = 1.65;  // the "zoomed out" opening view
const MAX_TILE_ZOOM = 16; // past this Esri tiles are upscaled: far fewer fetches, no visible loss at fire scale

// Cheap capability probe. Weak machines get fewer GPU-heavy effects, never fewer
// features: no MSAA on the map canvas and no animated camera moves.
const LOW_END = typeof navigator !== "undefined" &&
  ((navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4);
const MOTION_MS = LOW_END ? 0 : 800;

const IMAGERY_ATTRIBUTION = "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community";
const TERRAIN_ATTRIBUTION = "Tiles © Esri — Esri, USGS, NOAA, HERE, Garmin, FAO, METI/NASA";
const EMPTY = { type: "FeatureCollection", features: [] };

function makePointData(points, liveRows) {
  const features = [];
  for (const point of points) {
    features.push({
      type: "Feature",
      properties: { kind: point.sensor === "VIIRS" ? "VIIRS" : "MODIS", frp: point.frp || 0 },
      geometry: { type: "Point", coordinates: [point.lon, point.lat] },
    });
  }
  for (const point of liveRows) {
    features.push({
      type: "Feature",
      properties: { kind: "LIVE", frp: point.frp || 0 },
      geometry: { type: "Point", coordinates: [point.lon, point.lat] },
    });
  }
  return { type: "FeatureCollection", features };
}

function makeClusterData(clusters, liveClusters) {
  const features = [];
  const add = (cluster, live) => {
    const ring = (cluster.hull || []).map(([lat, lon]) => [lon, lat]);
    const distinct = new Set(ring.map(([lon, lat]) => `${lon},${lat}`)).size;
    if (!ring.length) return;
    if (distinct >= 3) {
      const first = ring[0], last = ring[ring.length - 1];
      if (first[0] !== last[0] || first[1] !== last[1]) ring.push(first);
      features.push({
        type: "Feature",
        properties: { kind: live ? "LIVE" : "CLUSTER", count: cluster.n || 0, frp: cluster.frp || 0 },
        geometry: { type: "Polygon", coordinates: [ring] },
      });
    } else if (ring.length > 1) {
      features.push({
        type: "Feature",
        properties: { kind: live ? "LIVE" : "CLUSTER", count: cluster.n || 0, frp: cluster.frp || 0 },
        geometry: { type: "LineString", coordinates: ring },
      });
    }
  };
  clusters.forEach(cluster => add(cluster, false));
  liveClusters.forEach(cluster => add(cluster, true));
  return { type: "FeatureCollection", features };
}

function makeSelectionData(bbox, firstCorner) {
  const features = [];
  if (bbox) {
    const [minLat, minLon, maxLat, maxLon] = bbox;
    features.push({
      type: "Feature",
      properties: { kind: "area" },
      geometry: {
        type: "Polygon",
        coordinates: [[[minLon, minLat], [maxLon, minLat], [maxLon, maxLat], [minLon, maxLat], [minLon, minLat]]],
      },
    });
  }
  if (firstCorner) {
    features.push({
      type: "Feature",
      properties: { kind: "corner" },
      geometry: { type: "Point", coordinates: [firstCorner[1], firstCorner[0]] },
    });
  }
  return { type: "FeatureCollection", features };
}

// Sentence case in source; the badge uppercases it. Keeping the literal words in one
// case means the readout can only ever disagree with the map in its wording, not its casing.
function viewForZoom(zoom) {
  if (zoom <= GLOBE_ZOOM) return "3D globe";
  if (zoom >= FLAT_ZOOM) return "2D map";
  return "Transition";
}

/** One camera and one satellite tile source morph continuously between a 3D Earth and a flat map. */
export default function MissionMap({
  center,
  points = [],
  clusters = [],
  live,
  bbox,
  picking = false,
  onSelectBounds,
  tiles,
  onTilesChange,
  day,
  span,
  end,
  fly,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const firstCornerRef = useRef(null);
  const onSelectBoundsRef = useRef(onSelectBounds);
  const pickingRef = useRef(picking);
  const tilesRef = useRef(tiles);
  const initialCenterRef = useRef(center);
  const lastCenterRef = useRef(center);
  const pointData = useMemo(() => makePointData(points, live?.rows || []), [points, live]);
  const clusterData = useMemo(() => makeClusterData(clusters, live?.clusters || []), [clusters, live]);
  const pointDataRef = useRef(pointData);
  const clusterDataRef = useRef(clusterData);
  // Filled by the ref-sync below on every render, so it needs no memo of its own -- the
  // previous version built this FeatureCollection twice per render and threw one away.
  const selectionDataRef = useRef(null);
  const [firstCorner, setFirstCorner] = useState(null);
  const [view, setView] = useState("3D globe");
  const [spin, setSpin] = useState(false);
  const viewRef = useRef("3D globe");

  onSelectBoundsRef.current = onSelectBounds;
  pickingRef.current = picking;
  tilesRef.current = tiles;
  pointDataRef.current = pointData;
  clusterDataRef.current = clusterData;
  selectionDataRef.current = makeSelectionData(bbox, firstCorner);

  useEffect(() => {
    if (!containerRef.current) return undefined;

    const start = initialCenterRef.current;
    const map = new MapLibreMap({
      container: containerRef.current,
      style: {
        version: 8,
        name: "Pyro-Harmony satellite mission view",
        projection: {
          // Continuous morph: a globe that keeps its curvature below GLOBE_ZOOM
          // ("vertical-perspective") and has blended into mercator by FLAT_ZOOM —
          // interpolating the projection type is what makes the hand-off smooth instead of a snap.
          type: ["interpolate", ["linear"], ["zoom"], GLOBE_ZOOM, "vertical-perspective", FLAT_ZOOM, "mercator"],
        },
        sources: {
          imagery: {
            type: "raster",
            tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
            tileSize: 256,
            maxzoom: MAX_TILE_ZOOM,
            attribution: IMAGERY_ATTRIBUTION,
          },
          terrain: {
            type: "raster",
            // Colourful terrain/vegetation basemap: green canopy, blue water, warm relief — a
            // readable backdrop for fire clusters, unlike the flat greyscale canvas it replaced.
            tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"],
            tileSize: 256,
            maxzoom: MAX_TILE_ZOOM,
            attribution: TERRAIN_ATTRIBUTION,
          },
          fires: { type: "geojson", data: EMPTY },
          clusters: { type: "geojson", data: EMPTY },
          selection: { type: "geojson", data: EMPTY },
        },
        layers: [
          // raster-fade-duration 0: loading a tile no longer triggers a fade animation,
          // which is a per-frame cost on weak GPUs every time you pan or zoom.
          { id: "satellite-imagery", type: "raster", source: "imagery", layout: { visibility: tilesRef.current === "sat" ? "visible" : "none" }, paint: { "raster-opacity": 1, "raster-fade-duration": 0 } },
          { id: "terrain-basemap", type: "raster", source: "terrain", layout: { visibility: tilesRef.current === "terrain" ? "visible" : "none" }, paint: { "raster-opacity": 1, "raster-fade-duration": 0 } },
          { id: "cluster-fill", type: "fill", source: "clusters", filter: ["==", ["geometry-type"], "Polygon"], paint: {
            "fill-color": ["case", ["==", ["get", "kind"], "LIVE"], "#ffe6b0", "#d8e2df"],
            "fill-opacity": 0.16,
          } },
          { id: "cluster-outline", type: "line", source: "clusters", paint: {
            "line-color": ["case", ["==", ["get", "kind"], "LIVE"], "#ffe6b0", "#d8e2df"],
            "line-width": 1.4,
            "line-opacity": 0.9,
          } },
          { id: "fire-points", type: "circle", source: "fires", paint: {
            // Sensor colours are shared with the Illusion diagnostic bars and the basin
            // legend below: MODIS coral, VIIRS amber, live pale gold. One sensor, one colour.
            "circle-color": ["match", ["get", "kind"], "VIIRS", "#f7b26a", "LIVE", "#ffe6b0", "#e2635a"],
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 0, 1.4, 3, 2, 5, 2.8, 9, 4],
            "circle-opacity": 0.9,
            "circle-stroke-color": "#ffeed6",
            "circle-stroke-width": 0.45,
            "circle-stroke-opacity": 0.75,
          } },
          { id: "selection-fill", type: "fill", source: "selection", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#7fd1c8", "fill-opacity": 0.08 } },
          { id: "selection-outline", type: "line", source: "selection", filter: ["==", ["geometry-type"], "Polygon"], paint: { "line-color": "#7fd1c8", "line-width": 1.6, "line-dasharray": [2, 1] } },
          { id: "selection-corner", type: "circle", source: "selection", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-color": "#7fd1c8", "circle-radius": 5, "circle-stroke-color": "#0e1416", "circle-stroke-width": 2 } },
        ],
      },
      center: [start[1], start[0]],
      zoom: START_ZOOM,
      minZoom: 0.5,
      maxZoom: 19,
      maxPitch: 60,
      attributionControl: { compact: true },
      canvasContextAttributes: { antialias: !LOW_END },
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: true, showZoom: true }), "bottom-right");

    map.on("load", () => {
      map.getSource("fires")?.setData(pointDataRef.current);
      map.getSource("clusters")?.setData(clusterDataRef.current);
      map.getSource("selection")?.setData(selectionDataRef.current);
      map.setLayoutProperty("satellite-imagery", "visibility", tilesRef.current === "sat" ? "visible" : "none");
      map.setLayoutProperty("terrain-basemap", "visibility", tilesRef.current === "terrain" ? "visible" : "none");
      map.resize();
    });
    map.on("zoom", () => {
      // `zoom` fires on every frame of a gesture; only touch React state when the
      // label actually changes, instead of scheduling a render per frame.
      const next = viewForZoom(map.getZoom());
      if (viewRef.current === next) return;
      viewRef.current = next;
      setView(next);
    });
    map.on("click", event => {
      if (!pickingRef.current) return;
      const corner = [event.lngLat.lat, event.lngLat.lng];
      if (!firstCornerRef.current) {
        firstCornerRef.current = corner;
        setFirstCorner(corner);
        return;
      }
      const first = firstCornerRef.current;
      const bounds = [
        Math.min(first[0], corner[0]), Math.min(first[1], corner[1]),
        Math.max(first[0], corner[0]), Math.max(first[1], corner[1]),
      ];
      firstCornerRef.current = null;
      setFirstCorner(null);
      onSelectBoundsRef.current?.(bounds);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    map.getSource("fires")?.setData(pointData);
  }, [pointData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    map.getSource("clusters")?.setData(clusterData);
  }, [clusterData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    map.getSource("selection")?.setData(makeSelectionData(bbox, firstCorner));
  }, [bbox, firstCorner]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer("satellite-imagery")) return;
    map.setLayoutProperty("satellite-imagery", "visibility", tiles === "sat" ? "visible" : "none");
    map.setLayoutProperty("terrain-basemap", "visibility", tiles === "terrain" ? "visible" : "none");
  }, [tiles]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (picking) map.doubleClickZoom.disable();
    else {
      map.doubleClickZoom.enable();
      firstCornerRef.current = null;
      setFirstCorner(null);
    }
    map.getCanvas().style.cursor = picking ? "crosshair" : "";
  }, [picking]);

  useEffect(() => {
    const previous = lastCenterRef.current;
    if (center[0] === previous[0] && center[1] === previous[1]) return;
    lastCenterRef.current = center;
    mapRef.current?.easeTo({ center: [center[1], center[0]], zoom: START_ZOOM, duration: MOTION_MS + 100 });
  }, [center[0], center[1]]);

  // Preset navigation: one flight to a curated AOI. Kept separate from the dataset-bounds
  // easing above, which always lands at the opening globe zoom; a preset wants a regional
  // zoom instead. `fly.nonce` changes on every pick, so re-picking the same region re-flies.
  const flyNonce = fly?.nonce;
  useEffect(() => {
    if (!fly || !mapRef.current) return;
    mapRef.current.flyTo({ center: [fly.center[1], fly.center[0]], zoom: fly.zoom ?? START_ZOOM,
                           duration: MOTION_MS + 250 });
  }, [flyNonce]);

  // Opt-in orbital drift. Slower on weak GPUs, and any gesture stops it immediately so it
  // can never fight the operator mid-drag.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !spin) return undefined;
    const step = LOW_END ? 0.12 : 0.22;
    const id = setInterval(() => map.setBearing((map.getBearing() + step) % 360), LOW_END ? 140 : 70);
    return () => clearInterval(id);
  }, [spin]);
  useEffect(() => {
    const el = mapRef.current?.getCanvas();
    if (!el || !spin) return undefined;
    const stop = () => setSpin(false);
    el.addEventListener("pointerdown", stop);
    el.addEventListener("wheel", stop, { passive: true });
    return () => { el.removeEventListener("pointerdown", stop); el.removeEventListener("wheel", stop); };
  }, [spin]);

  const hotspotTotal = points.length + (live?.rows?.length || 0);
  const totalFrp = points.reduce((sum, point) => sum + (point.frp || 0), 0)
    + (live?.rows || []).reduce((sum, point) => sum + (point.frp || 0), 0);

  return <div className="missionMap">
    <div ref={containerRef} className="mapCanvas" aria-label="Interactive satellite map and 3D Earth globe" />
    <div className="chip tl mapLegend">
      <span className="viewBadge"><i className="viewOrb" />{tiles === "sat" ? "Satellite" : "Terrain"} · {view}</span>
      <span className="mapLegendItem"><i className="dot" style={{ background: "#e2635a" }} />MODIS</span>
      <span className="mapLegendItem"><i className="dot" style={{ background: "#f7b26a" }} />VIIRS</span>
      <span className="mapLegendItem"><i className="dot" style={{ background: "#ffe6b0" }} />Live</span>
      <span className="mapLegendItem"><i className="dot" style={{ background: "#d8e2df" }} />Clusters</span>
      <span className="hint mapGestureHint">Scroll to zoom · drag to rotate Earth</span>
    </div>
    {/* All view controls live together in the top-right corner. Keeping the basemap
        toggle out of the bottom-left readout keeps that chip narrow, which is what stops
        it from running underneath the Esri attribution that has to stay legible. */}
    <div className="mapTopTools">
      <span className="mapLayerTools" role="group" aria-label="Basemap style">
        <button className={"btn sm" + (tiles === "sat" ? " on" : "")} onClick={() => onTilesChange("sat")}>Satellite</button>
        <button className={"btn sm" + (tiles === "terrain" ? " on" : "")} onClick={() => onTilesChange("terrain")}>Terrain</button>
      </span>
      <button className="btn sm" onClick={() => mapRef.current?.easeTo({ zoom: START_ZOOM, duration: MOTION_MS })} title="Return to the 3D Earth view">⤢ Globe view</button>
      <button className="btn sm" disabled={!bbox}
        onClick={() => bbox && mapRef.current?.fitBounds([[bbox[1], bbox[0]], [bbox[3], bbox[2]]], { padding: 56, duration: MOTION_MS + 250 })}
        title="Zoom the camera to the selected area">⌖ Fly to AOI</button>
      <button className="btn sm"
        onClick={() => mapRef.current?.easeTo({ center: [0, 0], zoom: START_ZOOM, bearing: 0, pitch: 0, duration: MOTION_MS + 250 })}
        title="Return to the default global view">↺ Reset orbit</button>
      <button className={"btn sm" + (spin ? " on" : "")} onClick={() => setSpin(on => !on)} aria-pressed={spin}
        title="Slowly rotate the view; any gesture stops it">⟳ Auto-rotate</button>
    </div>
    <div className="scan" />
    <div className="chip bl mapReadout">
      <span>{day || "—"}{span > 1 && <> → {end}</>}</span>
      <span>· {fmt(hotspotTotal)} hotspots · {fmt(clusters.length)} clusters · {fmt(totalFrp)} MW</span>
      {picking && <span className="mapPickHint">{firstCorner ? "Click the opposite corner" : "Click two corners to select an area"}</span>}
    </div>
  </div>;
}
