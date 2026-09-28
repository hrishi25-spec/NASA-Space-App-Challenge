import React, { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Polygon, Rectangle, useMapEvents } from "react-leaflet";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { api, errMsg, ramp, fmt } from "./lib";
import { HeroStats, ClimatologyPanel, DiagnosticPanel, LivePanel, BriefingPanel } from "./panels";
import LiveMapLayer from "./liveMapLayer";
import GlobeLayer from "./GlobeLayer";

const TILES = {
  dark: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  sat: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
};
const TILE_ATTR = {
  dark: "© Esri Dark Gray Canvas",
  sat: "© Esri World Imagery",
};

function Picker({ on, onBox }) {
  const [a, setA] = useState(null);
  useEffect(() => { if (!on) setA(null); }, [on]);  // reset stale first corner when picker toggles off
  useMapEvents({ click(e) {
    if (!on) return;
    if (!a) return setA(e.latlng);
    onBox([Math.min(a.lat, e.latlng.lat), Math.min(a.lng, e.latlng.lng), Math.max(a.lat, e.latlng.lat), Math.max(a.lng, e.latlng.lng)]); setA(null);
  } });
  return null;
}

function Heatmap({ data, onPick, focus, year }) {
  const years = useMemo(() => {
    const max = Math.max(1, ...data.map(d => d.count)), by = {};
    data.forEach(d => { const y = d.date.slice(0, 4); (by[y] ||= []).push({ ...d, lvl: d.count <= 0 ? 0 : Math.min(5, 1 + Math.floor(Math.sqrt(d.count / max) * 4.99)) }); });
    return by;
  }, [data]);
  if (year && year !== "all" && years[year]) return <YearView year={year} days={years[year]} onPick={onPick} focus={focus} />;
  return <div className="scroll">{Object.entries(years).map(([y, days]) => {
    const off = new Date(y + "-01-01").getUTCDay();
    return <div key={y} style={{ display: "flex", gap: 10, marginBottom: 6, alignItems: "center" }}>
      <b style={{ width: 34 }} className="mut">{y}</b>
      <svg width={Math.ceil((days.length + off) / 7) * 12 + 2} height={7 * 12}>
        {days.map((d, i) => { const k = i + off; return <rect key={d.date} x={Math.floor(k / 7) * 12} y={(k % 7) * 12} width="10" height="10" rx="2"
          fill={ramp[d.lvl]} stroke={d.date === focus ? "#37e5ff" : "none"} onClick={() => onPick(d.date)}><title>{d.date}: {d.count} (raw {d.raw})</title></rect>; })}
      </svg></div>;
  })}</div>;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function YearView({ year, days, onPick, focus }) {
  const size = 15, pitch = 17, labelW = 24, top = 16;
  const max = Math.max(1, ...days.map(d => d.count));
  const off = new Date(Date.UTC(+year, 0, 1)).getUTCDay();
  const cells = days.map(d => {
    const doy = Math.round((Date.parse(d.date + "T00:00:00Z") - Date.UTC(+year, 0, 1)) / 864e5);
    const k = doy + off;
    return { ...d, x: labelW + Math.floor(k / 7) * pitch, y: top + (k % 7) * pitch,
             lvl: d.count <= 0 ? 0 : Math.min(5, 1 + Math.floor(Math.sqrt(d.count / max) * 4.99)) };
  });
  const weeks = Math.floor((cells[cells.length - 1].x - labelW) / pitch) + 1;
  const W = labelW + weeks * pitch + 6, H = top + 7 * pitch + 20;
  const mlabels = [];
  let lastCol = -1;
  for (let m = 0; m < 12; m++) {
    const col = Math.floor((Math.round((Date.UTC(+year, m, 1) - Date.UTC(+year, 0, 1)) / 864e5) + off) / 7);
    if (col > lastCol) { mlabels.push({ m, col }); lastCol = col; }
  }
  const total = days.reduce((s, d) => s + d.count, 0);
  const peak = days.reduce((a, b) => (b.count > a.count ? b : a), days[0]);
  const active = days.filter(d => d.count > 0).length;
  const fmd = t => new Date(t + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  return <>
    <div className="mut" style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", marginBottom: 10, fontSize: 12 }}>
      <span><b style={{ color: "var(--acc2)", fontSize: 14 }}>{year}</b> · {fmt(total)} detections</span>
      <span>peak <b style={{ color: "var(--acc)" }}>{fmd(peak.date)}</b> ({peak.count})</span>
      <span>{active}/{days.length} active days</span>
      <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 3 }}>
        less {ramp.map((c, i) => <i key={i} style={{ width: 10, height: 10, background: c, borderRadius: 2, display: "inline-block" }} />)} more
      </span>
    </div>
    <div className="scroll">
      <svg width={W} height={H}>
        {mlabels.map(l => <text key={l.m} x={labelW + l.col * pitch} y={11} fontSize={9} fill="#5f6b85" style={{ letterSpacing: 1 }}>{MONTHS[l.m].toUpperCase()}</text>)}
        {["M", "W", "F"].map((w, i) => <text key={w} x={4} y={top + (i * 2 + 1) * pitch + 11} fontSize={8} fill="#5f6b85">{w}</text>)}
        {cells.map(d => <rect key={d.date} x={d.x} y={d.y} width={size} height={size} rx={2} fill={ramp[d.lvl]}
          stroke={d.date === focus ? "#37e5ff" : "none"} strokeWidth={2} style={{ cursor: "pointer" }} onClick={() => onPick(d.date)}>
          <title>{d.date}: {d.count} (raw {d.raw} · FRP {d.frp})</title></rect>)}
      </svg>
    </div>
  </>;
}

const DRAWER_TABS = ["calendar", "forecast", "climatology", "diagnostic", "briefing"];

export default function App() {
  const [meta, setMeta] = useState({ n: 0 }), [bbox, setBbox] = useState(null), [pick, setPick] = useState(false);
  const [cal, setCal] = useState([]), [pts, setPts] = useState([]), [cl, setCl] = useState([]), [an, setAn] = useState(null), [fc, setFc] = useState(null);
  const [day, setDay] = useState(null), [span, setSpan] = useState(1), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const [live, setLive] = useState(null), [diagKey, setDiagKey] = useState(0), [yearSel, setYearSel] = useState("all");
  const [tiles, setTiles] = useState("dark"), [tab, setTab] = useState("calendar");
  const [globe, setGlobe] = useState(true);   // start on the globe; zooming in flips to the flat map
  const bb = bbox?.join(",");

  useEffect(() => { api("/meta").then(setMeta).catch(() => { /* intro card covers the down state */ }); }, []);
  useEffect(() => {
    if (!meta.n) return;
    api("/calendar", { bbox: bb })
      .then(c => { setCal(c); setDay(prev => prev ?? (c.length ? c.reduce((a, b) => b.count > a.count ? b : a).date : null)); })
      .catch(() => setErr("Could not load calendar data."));
    api("/anomalies", { bbox: bb }).then(setAn).catch(() => setAn({ anomalies: [], critical: [], note: "Anomaly analysis failed." }));
    setFc(null); api("/forecast", { bbox: bb }).then(setFc).catch(() => setFc(null));
    setYearSel("all");
    setDiagKey(k => k + 1);
  }, [meta.n, bb]);
  async function loadDemo(mode) {
    setBusy(true); setDay(null); setBbox(null); setErr(null);
    try {
      const r = await fetch("/api/demo" + (mode === "transition" ? "?mode=transition" : ""), { method: "POST" });
      if (!r.ok) {
        const msg = await errMsg(r);
        throw new Error(msg === "Method Not Allowed" ? "wrong HTTP method" : msg);
      }
      setMeta(await r.json());
      setDiagKey(k => k + 1);
    } catch (e) { setErr("Could not load demo data — " + (e && e.message && e.message !== "Failed to fetch" ? e.message : "the API server isn't reachable on :8000. Start it with start.bat / start.sh (backend: uvicorn main:app --port 8000), then try again.")); }
    setBusy(false);
  }
  const end = day && new Date(new Date(day).getTime() + (span - 1) * 864e5).toISOString().slice(0, 10);
  useEffect(() => {
    if (!day) return;
    let dead = false;
    Promise.all([api("/points", { bbox: bb, start: day, end }), api("/clusters", { bbox: bb, start: day, end })])
      .then(([p, c]) => { if (!dead) { setPts(p); setCl(c); } })
      .catch(() => { if (dead) return; setErr("Could not load map data for that day."); });
    return () => { dead = true; };
  }, [day, span, bb]);

  async function upload(e) {
    if (!e.target.files.length) return;
    const fd = new FormData(); [...e.target.files].forEach(f => fd.append("files", f)); setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/upload", { method: "POST", body: fd });
      if (!r.ok) setErr("Upload failed: " + await errMsg(r));
      else { setMeta(await r.json()); setDay(null); setDiagKey(k => k + 1); }
    } catch { setErr("Upload failed — could not reach the backend."); }
    setBusy(false); e.target.value = "";
  }
  const series = useMemo(() => cal.slice(-365).map(d => ({ date: d.date, actual: d.count })).concat((fc?.forecast || []).map(d => ({ date: d.date, forecast: d.count }))), [cal, fc]);
  const center = meta.bounds ? [(meta.bounds[0] + meta.bounds[2]) / 2, (meta.bounds[1] + meta.bounds[3]) / 2] : [0, 0];
  // globe markers: live feed if pulled, else the day's cluster centroids, else dataset centroid
  const globeMarkers = useMemo(() => {
    if (live?.rows?.length) return live.rows.map(p => ({ lat: p.lat, lon: p.lon, frp: p.frp }));
    if (cl.length) return cl.map(c => ({ lat: c.lat, lon: c.lon, frp: c.frp }));
    return meta.n ? [{ lat: center[0], lon: center[1], frp: meta.hfi }] : [];
  }, [live, cl, meta.n, center[0], center[1]]);

  return <>
    <header className="cmd">
      <span className={"sig" + (meta.n ? "" : " down")} title={meta.n ? "link nominal" : "no data link"} />
      <div className="logo">
        <b>Pyro-Harmony</b>
        <span className="sub">fire intelligence · mission console</span>
      </div>
      <div className="spacer" />
      {meta.n > 0 && <div className="readout">
        <span>HOTSPOTS <b>{meta.n.toLocaleString()}</b></span>
        <span>WINDOW <b>{meta.start} → {meta.end}</b></span>
        <span>SENSORS <b>{Object.entries(meta.sensors).map(([k, v]) => `${k} ${fmt(v)}`).join(" · ")}</b></span>
      </div>}
      <label className="filebtn">
        <input type="file" multiple accept=".csv,.txt" onChange={upload} />
        <button className="btn primary" disabled={busy}>{busy ? "SYNCING…" : "Upload CSVs"}</button>
      </label>
      <button className="btn" onClick={() => loadDemo()} disabled={busy}>Load demo</button>
      <button className="btn" onClick={() => loadDemo("transition")} disabled={busy}>2002–2024</button>
      <button className={"btn" + (pick ? " on" : "")} onClick={() => setPick(!pick)}>{pick ? "Pick 2 corners…" : "Select area"}</button>
      {bbox && <button className="btn" onClick={() => setBbox(null)}>Clear</button>}
    </header>

    {err && <div className="banner">⚠ {err}</div>}

    {!meta.n ? <div className="panel" style={{ margin: 18, maxWidth: 760 }}>
      <h3>Standby — no data link</h3>
      <p style={{ margin: "4px 0 10px" }}>Pyro-Harmony harmonizes MODIS + VIIRS active-fire records into one burning-activity calendar: climatology, the Sensor Transition Illusion diagnostic, live FIRMS clustering, and an Incident Commander briefing.</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn primary" onClick={loadDemo} disabled={busy}>{busy ? "Generating…" : "Load 2020–2024 demo"}</button>
        <button className="btn" onClick={() => loadDemo("transition")} disabled={busy}>Load 2002–2024 transition demo</button>
      </div>
      <div className="hint" style={{ marginTop: 10 }}>
        Or upload NASA FIRMS archive CSVs (MODIS C6.1 / VIIRS S-NPP + NOAA-20/21). Confidence scales unified, low-confidence drops,
        per-sensor rescaling over the overlap period, ESFP footprint normalization.
      </div>
    </div> :
    <>
      <div className="deck">
        {/* ------- left rail: telemetry ------- */}
        <div className="rail">
          <HeroStats meta={meta} />
          <div className="panel">
            <h3>Selection</h3>
            <div className="kv"><span className="mut">AOI</span><b>{bbox ? `${bbox[0].toFixed(2)}, ${bbox[1].toFixed(2)} → ${bbox[2].toFixed(2)}, ${bbox[3].toFixed(2)}` : "global"}</b></div>
            <div className="kv"><span className="mut">Cursor day</span><b>{day || "—"}</b>{span > 1 && <b>→ {end}</b>}</div>
            <div style={{ display: "flex", gap: 4, marginTop: 8 }}>
              {[1, 3, 7, 14].map(n => <button key={n} className={"btn sm" + (span === n ? " on" : "")} onClick={() => setSpan(n)}>{n}d</button>)}
            </div>
          </div>
          <div className="panel">
            <h3>Clustering <span className="mut">DBSCAN</span></h3>
            <div className="kv"><span className="mut">Clusters</span><b>{cl.length}</b></div>
            <div className="kv"><span className="mut">Params</span><b>550 m · ≥3 pts · 12 h</b></div>
            <div className="kv"><span className="mut">Live feed</span><b>{live ? `${fmt(live.n)} pts` : "idle"}</b></div>
          </div>
        </div>

        {/* ------- center: globe <-> map stage ------- */}
        <div className="stage">
          {globe ? <GlobeLayer markers={globeMarkers} center={center} onZoomIn={() => setGlobe(false)} /> : <>
            <div className="zoomOutHint" style={{ position: "absolute", top: 10, right: 10, zIndex: 3 }}>
              <button className="btn sm" onClick={() => setGlobe(true)}>⤢ Globe view</button>
            </div>
          <div className="chip tl">
            <span className="dot" style={{ background: "#ff4d4d" }} />MODIS
            <span className="dot" style={{ background: "#ffb347" }} />VIIRS
            <span className="dot" style={{ background: "#ffd166" }} />LIVE
            <span className="dot" style={{ background: "#fff" }} />CLUSTER
          </div>
          <MapContainer key={center.join(",") + tiles} center={center} zoom={5} className="map" preferCanvas>
            <TileLayer url={TILES[tiles]} attribution={TILE_ATTR[tiles]} />
            <Picker on={pick} onBox={b => { setBbox(b); setPick(false); }} />
            {bbox && <Rectangle bounds={[[bbox[0], bbox[1]], [bbox[2], bbox[3]]]} pathOptions={{ color: "#37e5ff", weight: 1.5, fill: false, dashArray: "4 4" }} />}
            {pts.map((p, i) => <CircleMarker key={i} center={[p.lat, p.lon]} radius={2} pathOptions={{ color: p.sensor === "VIIRS" ? "#ffb347" : "#ff4d4d", weight: 1, fillOpacity: 0.85 }} />)}
            {cl.map(c => <Polygon key={c.id} positions={c.hull} pathOptions={{ color: "#e8e6e3", weight: 1, fillOpacity: 0.18 }} />)}
            <LiveMapLayer live={live} />
          </MapContainer>
          <div className="scan" />
          <div className="chip br">
            <b>{day || "—"}</b>{span > 1 && <>→ <b>{end}</b></>}
            <span>· {fmt(pts.length)} pts · {cl.length} clusters</span>
            <span className="tools" style={{ marginLeft: 6 }}>
              <button className={"btn sm" + (tiles === "dark" ? " on" : "")} onClick={() => setTiles("dark")}>Dark</button>
              <button className={"btn sm" + (tiles === "sat" ? " on" : "")} onClick={() => setTiles("sat")}>Sat</button>
            </span>
          </div>
          </>
          }
        </div>

        {/* ------- right rail: conditions ------- */}
        <div className="rail">
          <BriefingPanel bbox={bb} onPickDay={setDay} refreshKey={diagKey} mini />
          <div className="panel">
            <h3>Anomalies <span className="mut">critical periods</span></h3>
            {!an ? <span className="hint">Analyzing…</span> : an.note ? <span className="hint">{an.note}</span> : <>
              <div className="list" style={{ maxHeight: 180 }}>
                {an.anomalies.map(a => <div key={a.date} className="row" onClick={() => setDay(a.date)}>
                  <span>{a.date}</span><span className="mut">{a.count} vs {a.expected} · z={a.z}</span>
                </div>)}
                {!an.anomalies.length && <span className="hint">No anomalous days at this threshold.</span>}
              </div>
              <div className="hint" style={{ marginTop: 6 }}>
                Critical months (avg + 1σ): {an.critical.map(c => c.month).join(", ") || "none"}
              </div>
            </>}
          </div>
        </div>

        {/* ------- drawer: analytics tabs ------- */}
        <div className="drawer panel">
          <div className="tabs">
            {DRAWER_TABS.map(t => <button key={t} className={"tab" + (tab === t ? " on" : "")} onClick={() => setTab(t)}>
              {t === "calendar" ? "Burning calendar" : t === "climatology" ? "Climatology" : t === "diagnostic" ? "Illusion diagnostic" : t === "briefing" ? "Briefing detail" : "Forecast"}
            </button>)}
            {tab === "calendar" && <span className="tools" style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
              <span className="hint">Year</span>
              <select value={yearSel} onChange={e => setYearSel(e.target.value)}>
                <option value="all">All years</option>
                {[...new Set(cal.map(d => d.date.slice(0, 4)))].reverse().map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </span>}
          </div>
          {tab === "calendar" && <Heatmap data={cal} onPick={setDay} focus={day} year={yearSel} />}
          {tab === "forecast" && <>
            <div className="hint" style={{ marginBottom: 6 }}>Last year + 30-day forecast {fc?.model ? `· ${fc.model}` : ""}</div>
            <div style={{ height: 240 }}><ResponsiveContainer><LineChart data={series}>
              <CartesianGrid stroke="#141c30" /><XAxis dataKey="date" minTickGap={40} /><YAxis />
              <Tooltip contentStyle={{ background: "#0a0f1aee", border: "1px solid #26334f" }} />
              <Line dataKey="actual" stroke="#ff7a2f" dot={false} strokeWidth={2} />
              <Line dataKey="forecast" stroke="#37e5ff" strokeDasharray="5 3" dot={false} strokeWidth={2} />
            </LineChart></ResponsiveContainer></div>
          </>}
          {tab === "climatology" && <ClimatologyPanel bbox={bb} onPickDay={setDay} refreshKey={diagKey} embedded />}
          {tab === "diagnostic" && <DiagnosticPanel bbox={bb} refreshKey={diagKey} embedded />}
          {tab === "briefing" && <BriefingPanel bbox={bb} onPickDay={setDay} refreshKey={diagKey} detail />}
        </div>

        <LivePanel onLoaded={setLive} wide />
      </div>
    </>}
  </>;
}
