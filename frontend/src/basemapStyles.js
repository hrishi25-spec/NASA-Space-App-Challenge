// The map's basemap style documents, kept out of the component so they can be built, inspected
// and validated without a browser. Nothing here touches React, the DOM or MapLibre.
//
// Three basemaps, in two deliberately different shapes:
//   * Esri raster imagery -- satellite and colour terrain. Both sources live in ONE style, so
//     switching between them is a layer-visibility flip that keeps both tile caches warm.
//   * CARTO Dark Matter vector tiles -- geometry and labels, so a deep zoom stays sharp instead
//     of dragging upscaled imagery around, and a continent costs a fraction of the bytes. It
//     arrives as a complete third-party style document, which `mergeOverlays` grafts our own
//     sources and layers onto.

// The single source of truth for the globe <-> flat morph. These drive BOTH the style's
// projection expression and the view badge, so the readout can never disagree with what's drawn.
export const GLOBE_ZOOM = 3.7;   // at/below this zoom the Earth is a fully 3D globe
export const FLAT_ZOOM = 5.2;    // at/above this zoom the map is fully flat (mercator)
export const START_ZOOM = 1.65;  // the "zoomed out" opening view
export const MAX_TILE_ZOOM = 16; // past this Esri tiles are upscaled: far fewer fetches, no visible loss at fire scale

const PROJECTION = {
  // Continuous morph: a globe that keeps its curvature below GLOBE_ZOOM
  // ("vertical-perspective") and has blended into mercator by FLAT_ZOOM —
  // interpolating the projection type is what makes the hand-off smooth instead of a snap.
  type: ["interpolate", ["linear"], ["zoom"], GLOBE_ZOOM, "vertical-perspective", FLAT_ZOOM, "mercator"],
};

export const IMAGERY_ATTRIBUTION = "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community";
export const TERRAIN_ATTRIBUTION = "Tiles © Esri — Esri, USGS, NOAA, HERE, Garmin, FAO, METI/NASA";

// Keyless and accountless, and the tiles' own TileJSON carries the CARTO + OpenStreetMap
// credit that has to be shown. Dark, because a pale basemap under amber fire dots fights the
// console's palette — and because on a phone tether a dark vector map is the cheapest legible
// thing we can draw. Verified against MapLibre's own style spec: 0 validation errors.
export const VECTOR_STYLE_URL = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
// Stated here as well as in the TileJSON so the source stays self-describing when the merged
// style is built locally.
export const VECTOR_ATTRIBUTION = "© OpenStreetMap contributors © CARTO";

const EMPTY = { type: "FeatureCollection", features: [] };

const RASTER_SOURCES = {
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
};

// Detections, cluster extents and the drawn box: identical on every basemap, so they are
// defined once and appended to whichever basemap style is in play.
export const OVERLAY_SOURCES = {
  fires: { type: "geojson", data: EMPTY },
  clusters: { type: "geojson", data: EMPTY },
  selection: { type: "geojson", data: EMPTY },
};

export const OVERLAY_LAYERS = [
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
];

// The two Esri rasters and our overlays as one self-contained style, so the raster pair can be
// entered, left and switched between without ever re-fetching a style document.
export function rasterStyle(tiles) {
  return {
    version: 8,
    name: "Pyro-Harmony satellite mission view",
    projection: PROJECTION,
    sources: { ...RASTER_SOURCES, ...OVERLAY_SOURCES },
    layers: [
      // raster-fade-duration 0: loading a tile no longer triggers a fade animation,
      // which is a per-frame cost on weak GPUs every time you pan or zoom.
      { id: "satellite-imagery", type: "raster", source: "imagery", layout: { visibility: tiles === "sat" ? "visible" : "none" }, paint: { "raster-opacity": 1, "raster-fade-duration": 0 } },
      { id: "terrain-basemap", type: "raster", source: "terrain", layout: { visibility: tiles === "terrain" ? "visible" : "none" }, paint: { "raster-opacity": 1, "raster-fade-duration": 0 } },
      ...OVERLAY_LAYERS,
    ],
  };
}

// Take a complete basemap style (the fetched vector document, or an empty base while it is
// still arriving) and add the mission layers on top. The overlay layers go last so detections
// and the drawn box are never hidden by a basemap label, and the projection expression is
// ours, not the provider's: the globe morph has to match the badge on every basemap.
export function mergeOverlays(base) {
  return {
    ...base,
    projection: PROJECTION,
    sources: { ...base.sources, ...OVERLAY_SOURCES },
    layers: [...base.layers, ...OVERLAY_LAYERS],
  };
}
