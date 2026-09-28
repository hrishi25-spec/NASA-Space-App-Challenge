import { CircleMarker, Polygon, Tooltip as LTooltip } from "react-leaflet";
import { fmt } from "./lib";

/** Renders the live FIRMS feed points + clusters from /live on the main map. */
export default function LiveMapLayer({ live }) {
  if (!live) return null;
  const clusters = (live.clusters || []).slice(0, 80);
  return <>
    {clusters.map((c, i) => <Polygon key={"lc" + i} positions={c.hull}
      pathOptions={{ color: "#ffd166", weight: 1.5, fillOpacity: 0.12 }}>
      <LTooltip sticky>Live cluster · {c.n} hotspots · FRP {fmt(c.frp)} MW</LTooltip>
    </Polygon>)}
    {(live.rows || []).map((p, i) => <CircleMarker key={"lp" + i} center={[p.lat, p.lon]} radius={2}
      pathOptions={{ color: p.sensor === "VIIRS" ? "#ffe08a" : "#7dd3fc", weight: 1, fillOpacity: 0.9 }} />)}
  </>;
}
