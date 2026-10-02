import { useEffect, useMemo, useRef, useState } from "react";
// maplibre-gl v6 has NO default export — the ESM build only exposes named exports,
// so `import maplibregl from "maplibre-gl"` throws a SyntaxError and blanks the app.
import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// maplibre-gl resolves its GeoJSON/raster worker via `new URL(..., import.meta.url)`, which
// points into Vite's pre-bundled deps folder where no worker exists ("Worker failed to load"),
// leaving every source stuck unparsed. Hand it the worker URL Vite actually bundles.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { fmt, SLOW_LINK } from "./lib";
import { createQualityGovernor } from "./adaptiveQuality";
import { spinHolds, spinRate, spinStep } from "./autoRotate";
// The basemap style documents and the globe/mercator thresholds live in their own module, so
// the style that is drawn and the badge that reports it read the same constants.
import { GLOBE_ZOOM, FLAT_ZOOM, START_ZOOM, rasterStyle, mergeOverlays, VECTOR_STYLE_URL } from "./basemapStyles";

setWorkerUrl(maplibreWorkerUrl);

// The vector basemap is a third-party style document fetched once per session. The promise is
// cached so flipping away and back is instant; a failure is not cached, so a retry after the
// network comes back can still succeed.
let vectorStylePromise = null;
const loadVectorStyle = () => {
  vectorStylePromise ||= fetch(VECTOR_STYLE_URL)
    .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
    .catch(error => { vectorStylePromise = null; throw error; });
  return vectorStylePromise;
};

// The badge names the basemap that is actually drawn, in one place, so a new basemap cannot be
// added to the control row and forgotten here.
const BASEMAP_LABEL = { sat: "Satellite", terrain: "Terrain", vector: "Vector" };

// What the map wears while the vector style is in flight: our own layers, no basemap. On a slow
// link the console opens straight onto this rather than pulling raster tiles it is about to
// throw away, and the dark map well shows through until the real style lands.
const PLACEHOLDER_STYLE = mergeOverlays({ version: 8, name: "Pyro-Harmony mission view (basemap loading)", sources: {}, layers: [] });

// Cheap capability probe. Weak machines get fewer GPU-heavy effects, never fewer
// features: a 1x render ratio and no animated camera moves.
const LOW_END = typeof navigator !== "undefined" &&
  ((navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4);
const MOTION_MS = LOW_END ? 0 : 800;

// Rendering cost scales with canvas pixels, and a HiDPI canvas shades roughly four times the
// fragments of a 1x one. Capping the ratio keeps the raster basemaps legible -- there are no
// symbol layers whose text would soften -- while cutting the per-frame work of every drag and
// zoom on the integrated GPUs this console targets. Weak machines render at a true 1x.
const PIXEL_RATIO = Math.min((typeof window !== "undefined" && window.devicePixelRatio) || 1,
                             LOW_END ? 1 : 1.5);
// What a gesture that is not keeping up drops to: one canvas pixel per CSS pixel, the cheapest
// thing the browser can shade. On a machine already capped at 1x this is the same value, and the
// detection points below are the only lever left.
const DEGRADED_RATIO = Math.min(PIXEL_RATIO, 1);

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
  const rootRef = useRef(null);
  const mapRef = useRef(null);
  const firstCornerRef = useRef(null);
  const onSelectBoundsRef = useRef(onSelectBounds);
  const onTilesChangeRef = useRef(onTilesChange);
  const pickingRef = useRef(picking);
  const tilesRef = useRef(tiles);
  // Which family of style is currently on the map. Switching inside a family is a visibility
  // flip; crossing the boundary is a `setStyle`, which is why it has to be tracked. It starts at
  // "raster" even when the console opens on vector: the map is created on the placeholder, so
  // the vector style is precisely what the switch effect below still has to fetch and install.
  const styleKindRef = useRef("raster");
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
  const [vectorErr, setVectorErr] = useState(null);
  const viewRef = useRef("3D globe");
  // True while a gesture is being served at reduced detail, so the correction survives a
  // basemap swap (a new style would otherwise hand the full-detail layers back mid-drag).
  const degradedRef = useRef(false);
  // True only for the instant the drift sets the bearing. `setBearing` fires its rotate events
  // synchronously, so this is an exact "this move is ours" flag for the frame-rate sampler.
  const spinningRef = useRef(false);

  onSelectBoundsRef.current = onSelectBounds;
  onTilesChangeRef.current = onTilesChange;
  pickingRef.current = picking;
  tilesRef.current = tiles;
  pointDataRef.current = pointData;
  clusterDataRef.current = clusterData;
  selectionDataRef.current = makeSelectionData(bbox, firstCorner);

  // Re-attaches our data and the raster visibility to whichever style is loaded now. A style
  // swap rebuilds every source, so this runs on each `style.load` (which also fires for the
  // first style), not once per mount.
  const hydrateLayers = () => {
    const map = mapRef.current;
    if (!map) return;
    map.getSource("fires")?.setData(pointDataRef.current);
    map.getSource("clusters")?.setData(clusterDataRef.current);
    map.getSource("selection")?.setData(selectionDataRef.current);
    // The vector style has no raster layers at all, so both of these are lookups that miss.
    if (map.getLayer("satellite-imagery")) map.setLayoutProperty("satellite-imagery", "visibility", tilesRef.current === "sat" ? "visible" : "none");
    if (map.getLayer("terrain-basemap")) map.setLayoutProperty("terrain-basemap", "visibility", tilesRef.current === "terrain" ? "visible" : "none");
    if (degradedRef.current && map.getLayer("fire-points")) map.setLayoutProperty("fire-points", "visibility", "none");
  };

  // Reduced detail for the duration of a gesture that is not keeping up: a 1x canvas, and the
  // detection points out of the draw. The ratio is the lever that matters (it is the whole
  // per-frame fragment bill); the points are what is left when the ratio is already 1x. Both
  // come back the moment the motion stops, so a still map is always the full-detail map.
  const applyQuality = reduced => {
    const map = mapRef.current;
    if (!map) return;
    degradedRef.current = reduced;
    const ratio = reduced ? DEGRADED_RATIO : PIXEL_RATIO;
    // setPixelRatio resizes the backing store, so only call it when it actually changes.
    if (map.getPixelRatio() !== ratio) map.setPixelRatio(ratio);
    if (map.getLayer("fire-points")) {
      map.setLayoutProperty("fire-points", "visibility", reduced ? "none" : "visible");
    }
    const root = rootRef.current;
    // A DOM flag, not React state: this toggles mid-gesture, and a render is the last thing a
    // janky drag needs. It also makes the mode visible to devtools and to any styling later.
    if (root) { if (reduced) root.dataset.quality = "reduced"; else delete root.dataset.quality; }
  };

  useEffect(() => {
    if (!containerRef.current) return undefined;

    const start = initialCenterRef.current;
    const map = new MapLibreMap({
      container: containerRef.current,
      // The raster pair is built here; the vector basemap arrives over the network, so an
      // opening on a slow link starts on our layers alone and swaps the real style in below.
      style: tilesRef.current === "vector" ? PLACEHOLDER_STYLE : rasterStyle(tilesRef.current),
      center: [start[1], start[0]],
      zoom: START_ZOOM,
      minZoom: 0.5,
      maxZoom: 19,
      maxPitch: 60,
      attributionControl: { compact: true },
      // No MSAA on the shared canvas -- MapLibre's own default, and the right one here. A
      // multisampled buffer costs a full-resolution resolve every frame, while the only edges
      // it would smooth are the round fire dots: both basemaps are textures, drawn either
      // fully covered or not at all. Satellite and terrain pay the same bill.
      canvasContextAttributes: { antialias: false },
      // Both basemaps are raster layers that keep streaming during a zoom or a drag, and
      // MapLibre's default 300 ms crossfade is per-frame work for every layer it draws, so
      // it is off. The cap on the render ratio applies to the satellite and terrain views
      // alike -- it is a property of the canvas, not of the tiles.
      fadeDuration: 0,
      pixelRatio: PIXEL_RATIO,
      // Esri tiles do not change minute to minute. Re-validating an expired tile mid-gesture
      // buys a conditional request, a decode and a texture re-upload -- a visible hitch -- for
      // pixels that are almost always identical, so expiry checking stays off for the session.
      refreshExpiredTiles: false,
      // At the opening zoom the same world can be drawn up to seven times in one frame, and
      // each copy is another tile cover to project and rasterize. A fire console never shows
      // a repeated Earth, so the extra covers are pure cost.
      renderWorldCopies: false,
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: true, showZoom: true }), "bottom-right");

    // The bottom-left column has to clear MapLibre's attribution notice, and that notice is a
    // legal requirement whose height we do not control: it grows a line or two on a narrow map
    // and for a moment when both basemaps report. Measure it rather than guess, and hand the
    // measurement to the CSS as the height the column sits above, so the controls are never
    // parked on the notice at any width.
    const attribEl = map.getContainer().querySelector(".maplibregl-ctrl-attrib");
    const syncAttribBand = () => {
      const root = rootRef.current;
      // An empty notice is display:none: keep the stylesheet's default band until it appears.
      if (!root || !attribEl || !attribEl.getClientRects().length) return;
      const gap = map.getContainer().getBoundingClientRect().bottom - attribEl.getBoundingClientRect().top;
      if (gap > 0) root.style.setProperty("--attribBand", `${Math.min(Math.ceil(gap) + 6, 120)}px`);
    };
    syncAttribBand();
    const attribObserver = attribEl && typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(syncAttribBand) : null;
    attribObserver?.observe(attribEl);
    map.on("styledata", syncAttribBand);

    // ---- adaptive detail -------------------------------------------------
    // The map watches its own frame times while the camera is being moved, and hands the
    // decision to `createQualityGovernor` (pure, unit-tested). Sampling happens only inside a
    // gesture: the loop is started by the gesture that opens the window and stops itself once
    // the motion has been quiet for a moment, which is also when full detail comes back.
    const governor = createQualityGovernor({ onChange: applyQuality });
    let rafId = 0;
    const stepFrame = now => {
      rafId = 0;
      governor.sample(now);
      if (governor.settled(now)) { governor.release(); return; }
      rafId = requestAnimationFrame(stepFrame);
    };
    // Every gesture event arms the window; only the first one of a run starts the sampler.
    // MapLibre fires the matching *end* events too, but the quiet window covers those without
    // needing to pair them up (a pinch can be a zoom, a rotate and a pitch at once).
    const armQuality = () => {
      // A programmatic camera move is not a gesture. The drift ticks every frame and each tick
      // fires a rotate event, which would hold the measurement window open forever and leave a
      // slow machine pinned at reduced detail for as long as Auto-rotate was on.
      if (spinningRef.current) return;
      governor.arm(performance.now());
      if (!rafId) rafId = requestAnimationFrame(stepFrame);
    };
    for (const gesture of ["dragstart", "zoomstart", "rotatestart", "pitchstart"]) map.on(gesture, armQuality);

    map.on("style.load", hydrateLayers);
    map.on("load", () => {
      hydrateLayers();
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
      if (rafId) cancelAnimationFrame(rafId);
      governor.release();
      attribObserver?.disconnect();
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

  // Basemap switching. Inside the raster pair both sources are already in the style, so this is
  // a visibility flip and the tile caches stay warm; entering or leaving the vector basemap
  // means a whole new style document, and the overlays are re-hydrated once it loads.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return undefined;

    if (tiles === "vector") {
      if (styleKindRef.current === "vector") return undefined;
      let cancelled = false;
      setVectorErr(null);
      loadVectorStyle()
        .then(base => {
          if (cancelled) return;
          styleKindRef.current = "vector";
          map.setStyle(mergeOverlays(base));
        })
        .catch(() => {
          // Keep the console usable: report it on the button and land back on imagery, which
          // needs no third party beyond the Esri tiles already in the style.
          if (cancelled) return;
          setVectorErr("Vector basemap unavailable — retry, or stay on the imagery");
          onTilesChangeRef.current?.("sat");
        });
      return () => { cancelled = true; };
    }

    if (styleKindRef.current === "vector") {
      styleKindRef.current = "raster";
      map.setStyle(rasterStyle(tiles));
      return undefined;
    }
    if (map.getLayer("satellite-imagery")) map.setLayoutProperty("satellite-imagery", "visibility", tiles === "sat" ? "visible" : "none");
    if (map.getLayer("terrain-basemap")) map.setLayoutProperty("terrain-basemap", "visibility", tiles === "terrain" ? "visible" : "none");
    return undefined;
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

  // Opt-in orbital drift, one animation frame at a time. Slower on weak GPUs, and any gesture
  // stops it immediately so it can never fight the operator mid-drag. See autoRotate.js for why
  // the angle is accumulated from frame times instead of being stepped by a timer.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !spin) return undefined;
    const rate = spinRate(LOW_END);
    // Our own unwrapped bearing. MapLibre wraps whatever it is handed into (-180, 180] and
    // picks the nearest equivalent angle, so letting this grow keeps the globe turning the same
    // way across the ±180 seam.
    let frame = 0, angle = null, last = 0;
    const tick = now => {
      frame = requestAnimationFrame(tick);
      if (angle === null) {                       // first frame, or resuming after a hold
        angle = map.getBearing();
        last = now;
        return;
      }
      const elapsed = now - last;
      last = now;
      // Someone else owns the camera for the moment (a gesture, or Fly to AOI / Globe view /
      // Reset orbit / a dataset fly-to): hold, and pick the drift up from wherever their move
      // leaves it rather than dragging the bearing back to ours.
      if (spinHolds(map.isMoving())) { angle = null; return; }
      angle += spinStep(elapsed, rate);
      // The rotate events `setBearing` fires are synchronous, so this flag is exact: it keeps
      // the drift's own rotation from arming the adaptive-detail sampler every frame.
      spinningRef.current = true;
      map.setBearing(angle);
      spinningRef.current = false;
    };
    frame = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(frame); spinningRef.current = false; };
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

  return <div className="missionMap" ref={rootRef}>
    <div ref={containerRef} className="mapCanvas" aria-label="Interactive satellite map and 3D Earth globe" />
    <div className="chip tl mapLegend">
      <span className="viewBadge"><i className="viewOrb" />{BASEMAP_LABEL[tiles] || "Satellite"} · {view}</span>
      <span className="mapLegendItem"><i className="dot" style={{ background: "#e2635a" }} />MODIS</span>
      <span className="mapLegendItem"><i className="dot" style={{ background: "#f7b26a" }} />VIIRS</span>
      <span className="mapLegendItem"><i className="dot" style={{ background: "#ffe6b0" }} />Live</span>
      <span className="mapLegendItem"><i className="dot" style={{ background: "#d8e2df" }} />Clusters</span>
      <span className="hint mapGestureHint">Scroll to zoom · drag to rotate Earth</span>
    </div>
    <div className="scan" />
    {/* Bottom-left column: the day/hotspot readout first, then every view control beneath it.
        One bottom-anchored column means a wrapped row of buttons grows upward instead of
        colliding with the numbers, and its right margin keeps the compact corner free for the
        Esri attribution. The bottom offset is `--attribBand`, the notice height measured above. */}
    <div className="mapBottom">
      <div className="chip mapReadout">
        <span>{day || "—"}{span > 1 && <> → {end}</>}</span>
        <span>· {fmt(hotspotTotal)} hotspots · {fmt(clusters.length)} clusters · {fmt(totalFrp)} MW</span>
        {picking && <span className="mapPickHint">{firstCorner ? "Click the opposite corner" : "Click two corners to select an area"}</span>}
      </div>
      <div className="mapTools">
        <span className="mapLayerTools" role="group" aria-label="Basemap style">
          <button className={"btn sm" + (tiles === "sat" ? " on" : "")} onClick={() => onTilesChange("sat")}>Satellite</button>
          <button className={"btn sm" + (tiles === "terrain" ? " on" : "")} onClick={() => onTilesChange("terrain")}>Terrain</button>
          {/* Vector tiles: geometry and labels rather than pixels, so a deep zoom stays crisp
              and the planet costs a fraction of the bytes. The lightest choice on a slow link,
              which is why it is the opening basemap there. */}
          <button className={"btn sm" + (tiles === "vector" ? " on" : "")} onClick={() => onTilesChange("vector")}
            title={vectorErr || "Vector tiles: crisp coastlines and place names at any zoom, and the lightest basemap on a slow connection"}>Vector</button>
        </span>
        {SLOW_LINK && tiles === "vector" &&
          <span className="hint mapSlowLink" title="Chosen automatically: this connection is slow, and vector tiles are the lightest basemap">Slow link</span>}
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
    </div>
  </div>;
}
