import React, { useEffect, useMemo, useRef, useState, Suspense, lazy } from "react";
import { api, errMsg, ramp, fmt, invalidateApiCache } from "./lib";
import { HeroStats, LivePanel, BriefingPanel } from "./panels";

// Code-split the heavy optional pieces so a low-end machine can paint the console
// before it downloads a map engine or a charting library. MissionMap drags in
// MapLibre (~450 KB gzipped), charts/ForecastChart drag in Recharts — none of them
// are needed to show the shell, and Recharts is not needed until a chart tab opens.
const MissionMap = lazy(() => import("./MissionMap"));
// charts.jsx exposes NAMED exports only, and React.lazy resolves `module.default`.
// Wrapping a multi-export module directly yields `undefined` as a component type,
// which throws inside <Suspense> and (without a boundary) blanks the whole console.
const ClimatologyPanel = lazy(() => import("./charts").then(m => ({ default: m.ClimatologyPanel })));
const DiagnosticPanel = lazy(() => import("./charts").then(m => ({ default: m.DiagnosticPanel })));
const ForecastChart = lazy(() => import("./ForecastChart"));

/**
 * Keeps a single failing tab from taking the entire mission console down with it:
 * a render error in one lazy chart shows an inline message instead of a blank page.
 */
class PanelBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error) { console.error("[panel]", this.props.name, error); }
  componentDidUpdate(prev) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return <div className="hint">
      This panel hit an error and was contained so the rest of the console keeps working.
      <div className="mut" style={{ marginTop: 4 }}>{String(this.state.error && this.state.error.message || this.state.error)}</div>
    </div>;
  }
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
    return <div key={y} style={{ display: "flex", gap: 10, marginBottom: 6, alignItems: "center" }}>          <b style={{ width: 34 }} className="mut">{y}</b>
      <svg width={Math.ceil((days.length + off) / 7) * 12 + 2} height={7 * 12}>
        {days.map((d, i) => { const k = i + off; return <rect key={d.date} x={Math.floor(k / 7) * 12} y={(k % 7) * 12} width="10" height="10" rx="2"
          fill={ramp[d.lvl]} stroke={d.date === focus ? "#7fd1c8" : "none"} onClick={() => onPick(d.date)}><title>{d.date}: {d.count} (raw {d.raw})</title></rect>; })}
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
        {mlabels.map(l => <text key={l.m} x={labelW + l.col * pitch} y={11} fontSize={9} fill="#7b8c92" style={{ letterSpacing: 1 }}>{MONTHS[l.m].toUpperCase()}</text>)}
        {["M", "W", "F"].map((w, i) => <text key={w} x={4} y={top + (i * 2 + 1) * pitch + 11} fontSize={8} fill="#7b8c92">{w}</text>)}
        {cells.map(d => <rect key={d.date} x={d.x} y={d.y} width={size} height={size} rx={2} fill={ramp[d.lvl]}
          stroke={d.date === focus ? "#7fd1c8" : "none"} strokeWidth={2} style={{ cursor: "pointer" }} onClick={() => onPick(d.date)}>
          <title>{d.date}: {d.count} (raw {d.raw} · FRP {d.frp})</title></rect>)}
      </svg>
    </div>
  </>;
}

// Tab id + source-case label in one place, so the casing pass can never miss one of them
// (styles.css uppercases .tab). The expensive chart chunks are also warmed on hover/focus:
// opening a cold tab otherwise means downloading Recharts (~108 kB gzipped) before anything
// appears, and the module registry makes a repeated prefetch free.
const DRAWER_TABS = [
  { id: "calendar", label: "Burning calendar" },
  { id: "forecast", label: "Forecast", prefetch: () => import("./ForecastChart") },
  { id: "climatology", label: "Climatology", prefetch: () => import("./charts") },
  { id: "diagnostic", label: "Illusion diagnostic", prefetch: () => import("./charts") },
  { id: "briefing", label: "Briefing detail" },
];

export default function App() {
  const [meta, setMeta] = useState({ n: 0 }), [bbox, setBbox] = useState(null), [pick, setPick] = useState(false);
  const [cal, setCal] = useState([]), [pts, setPts] = useState([]), [cl, setCl] = useState([]), [an, setAn] = useState(null), [fc, setFc] = useState(null);
  const [day, setDay] = useState(null), [span, setSpan] = useState(1), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const [live, setLive] = useState(null), [diagKey, setDiagKey] = useState(0), [yearSel, setYearSel] = useState("all");
  // Bumped whenever the dataset itself is replaced. The reload effect keyed on meta.n alone
  // would not re-run when you load a demo with the same hotspot count, leaving the cursor day
  // null and the calendar empty, so the dataset gets its own version counter.
  const [dataKey, setDataKey] = useState(0);
  const [tiles, setTiles] = useState("sat"), [tab, setTab] = useState("calendar");
  // Curated AOI presets: the picker sets the bbox filter and flies the camera. `fly` carries
  // a nonce so picking the same region twice still re-flies.
  const [regions, setRegions] = useState([]), [presetKey, setPresetKey] = useState(null), [fly, setFly] = useState(null);
  const flyNonce = useRef(0);
  const bb = bbox?.join(",");

  useEffect(() => { api("/meta").then(setMeta).catch(() => { /* intro card covers the down state */ }); }, []);
  useEffect(() => { api("/regions").then(setRegions).catch(() => setRegions([])); }, []);

  // The picked preset, or whichever preset the current bbox matches: a hand-picked box that
  // happens to line up with a preset gets that region's facts too, so the panel describes
  // the AOI rather than the click that created it.
  const preset = useMemo(() => regions.find(r => r.key === presetKey)
    || regions.find(r => bbox && r.bbox.join() === bbox.join()), [regions, presetKey, bb]);

  function gotoRegion(key) {
    const region = regions.find(r => r.key === key);
    setDay(null); setPick(false);                            // the day cursor belongs to the old AOI
    if (!region) {                                           // "Fly to…" / Clear: back to the global view
      setPresetKey(null); setBbox(null);
      setFly({ center: [0, 0], nonce: ++flyNonce.current });
      return;
    }
    setPresetKey(region.key); setBbox(region.bbox);
    setFly({ center: region.center, zoom: region.zoom, nonce: ++flyNonce.current });
  }
  useEffect(() => {
    if (!meta.n) return;
    api("/calendar", { bbox: bb })
      .then(c => { setCal(c); setDay(prev => prev ?? (c.length ? c.reduce((a, b) => b.count > a.count ? b : a).date : null)); })
      .catch(() => setErr("Could not load calendar data."));
    api("/anomalies", { bbox: bb }).then(setAn).catch(() => setAn({ anomalies: [], critical: [], note: "Anomaly analysis failed." }));
    setFc(null); api("/forecast", { bbox: bb }).then(setFc).catch(() => setFc(null));
    setYearSel("all");
    setDiagKey(k => k + 1);
  }, [meta.n, dataKey, bb]);
  async function loadDemo(mode, region) {
    // Follow the selected AOI: clicking "Load demo" while a region is active must put the
    // demo inside that region instead of back in the default box, which would look empty.
    const target = region ?? preset?.key ?? null;
    setBusy(true); setDay(null); setErr(null);
    if (!target) setBbox(null);
    try {
      const q = new URLSearchParams();
      if (mode === "transition") q.set("mode", "transition");
      if (target) q.set("region", target);
      const r = await fetch("/api/demo" + (q.toString() ? "?" + q : ""), { method: "POST" });
      if (!r.ok) {
        const msg = await errMsg(r);
        throw new Error(msg === "Method Not Allowed" ? "wrong HTTP method" : msg);
      }
      datasetChanged(await r.json());
    } catch (e) { setErr("Could not load demo data — " + (e && e.message && e.message !== "Failed to fetch" ? e.message : "the API server isn't reachable on :8000. Start it with start.bat / start.sh (backend: uvicorn main:app --port 8000), then try again.")); }
    setBusy(false);
  }
  // Any loader that changes the dataset (upload, demo, real FIRMS window) lands here, so the
  // memoized queries are dropped and the panels refetch against the new record.
  function datasetChanged(m) {
    setMeta(m); invalidateApiCache(); setDay(null); setDataKey(k => k + 1); setDiagKey(k => k + 1);
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
      else datasetChanged(await r.json());
    } catch { setErr("Upload failed — could not reach the backend."); }
    setBusy(false); e.target.value = "";
  }
  const series = useMemo(() => cal.slice(-365).map(d => ({ date: d.date, actual: d.count })).concat((fc?.forecast || []).map(d => ({ date: d.date, forecast: d.count }))), [cal, fc]);
  const center = meta.bounds ? [(meta.bounds[0] + meta.bounds[2]) / 2, (meta.bounds[1] + meta.bounds[3]) / 2] : [0, 0];

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
      {regions.length > 0 && <select value={preset?.key || ""} onChange={e => gotoRegion(e.target.value)}
        title="Fly the map to a curated fire region">
        <option value="">Fly to…</option>
        {regions.map(r => <option key={r.key} value={r.key}>{r.name}</option>)}
      </select>}
      <button className={"btn" + (pick ? " on" : "")} onClick={() => setPick(!pick)}>{pick ? "Pick 2 corners…" : "Select area"}</button>
      {bbox && <button className="btn" onClick={() => gotoRegion("")}>Clear</button>}
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
            {preset && <>
              <div className="kv"><span className="mut">Region</span><b>{preset.name} · {preset.subtitle}</b></div>
              <div className="kv"><span className="mut">Fuel</span><b>{preset.biome}</b></div>
              <div className="kv"><span className="mut">Peak season</span><b>{preset.peak_months.map(m => MONTHS[m - 1]).join(" · ")}</b></div>
              <div className="kv"><span className="mut">Noted fires</span><b>{preset.events.map(ev => `${ev.year} ${ev.note}`).join(" · ")}</b></div>
            </>}
            <div style={{ display: "flex", gap: 4, marginTop: 8 }}>
              {[1, 3, 7, 14].map(n => <button key={n} className={"btn sm" + (span === n ? " on" : "")} onClick={() => setSpan(n)}>{n}d</button>)}
            </div>
            {preset && !cal.length && <div className="hint" style={{ marginTop: 9 }}>
              No detections in this AOI yet.
              <button className="btn sm" style={{ marginTop: 6, width: "100%" }} disabled={busy}
                onClick={() => loadDemo("standard", preset.key)}>Load demo for {preset.name}</button>
            </div>}
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
          <Suspense fallback={<div className="mapFallback"><span className="hint">starting the map engine…</span></div>}>
            <MissionMap
              center={center}
              points={pts}
              clusters={cl}
              live={live}
              bbox={bbox}
              picking={pick}
              onSelectBounds={bounds => { setBbox(bounds); setPick(false); }}
              tiles={tiles}
              onTilesChange={setTiles}
              day={day}
              span={span}
              end={end}
              fly={fly}
            />
          </Suspense>
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
                {/* The API reports months as 1-12; spell them or the line reads "3" instead of "Mar". */}
                Critical months (avg + 1σ): {an.critical.map(c => MONTHS[c.month - 1] ?? c.month).join(", ") || "none"}
              </div>
            </>}
          </div>
        </div>

        {/* ------- drawer: analytics tabs ------- */}
        <div className="drawer panel">
          <div className="tabs">
            {DRAWER_TABS.map(t => <button key={t.id} role="tab" aria-selected={tab === t.id}
              className={"tab" + (tab === t.id ? " on" : "")} onClick={() => setTab(t.id)}
              onMouseEnter={() => t.prefetch?.()} onFocus={() => t.prefetch?.()}>
              {t.label}
            </button>)}
            {tab === "calendar" && <span className="tools" style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
              <span className="hint">Year</span>
              <select value={yearSel} onChange={e => setYearSel(e.target.value)}>
                <option value="all">All years</option>
                {[...new Set(cal.map(d => d.date.slice(0, 4)))].reverse().map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </span>}
          </div>
          {tab === "calendar" && <PanelBoundary name="calendar" resetKey={tab}><Heatmap data={cal} onPick={setDay} focus={day} year={yearSel} /></PanelBoundary>}
          {tab === "forecast" && <PanelBoundary name="forecast" resetKey={tab}><Suspense fallback={<span className="hint">Loading chart…</span>}>
            <ForecastChart series={series} model={fc?.model} />
          </Suspense></PanelBoundary>}
          {tab === "climatology" && <PanelBoundary name="climatology" resetKey={tab}><Suspense fallback={<span className="hint">Loading chart…</span>}>
            <ClimatologyPanel bbox={bb} refreshKey={diagKey} embedded />
          </Suspense></PanelBoundary>}
          {tab === "diagnostic" && <PanelBoundary name="diagnostic" resetKey={tab}><Suspense fallback={<span className="hint">Loading chart…</span>}>
            <DiagnosticPanel bbox={bb} refreshKey={diagKey} embedded />
          </Suspense></PanelBoundary>}
          {tab === "briefing" && <BriefingPanel bbox={bb} onPickDay={setDay} refreshKey={diagKey} detail />}
        </div>

        <LivePanel onLoaded={setLive} wide bbox={bb} region={preset?.key} onDatasetChanged={datasetChanged} />
      </div>
    </>}
  </>;
}
