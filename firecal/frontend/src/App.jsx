import React, { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Polygon, Rectangle, useMapEvents } from "react-leaflet";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, CartesianGrid } from "recharts";
import { api, errMsg, ramp, fmt } from "./lib";
import { HeroStats, ClimatologyPanel, DiagnosticPanel, LivePanel, BriefingPanel } from "./panels";
import LiveMapLayer from "./liveMapLayer";

function Picker({ on, onBox }) {
  const [a, setA] = useState(null);
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
    return <div key={y} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
      <b style={{ width: 36 }} className="mut">{y}</b>
      <svg width={Math.ceil((days.length + off) / 7) * 12 + 2} height={7 * 12}>
        {days.map((d, i) => { const k = i + off; return <rect key={d.date} x={Math.floor(k / 7) * 12} y={(k % 7) * 12} width="10" height="10" rx="2"
          fill={ramp[d.lvl]} stroke={d.date === focus ? "#fff" : "none"} onClick={() => onPick(d.date)}><title>{d.date}: {d.count} (raw {d.raw})</title></rect>; })}
      </svg></div>;
  })}</div>;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function YearView({ year, days, onPick, focus }) {
  const size = 15, pitch = 17, labelW = 24, top = 16;
  const max = Math.max(1, ...days.map(d => d.count));
  const off = new Date(Date.UTC(+year, 0, 1)).getUTCDay();
  // place every cell by its true day-of-year so months line up even if the
  // record starts/ends mid-year
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
    <div className="mut" style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center", marginBottom: 10, fontSize: 13 }}>
      <span><b style={{ color: "var(--fg)", fontSize: 15 }}>{year}</b> · {fmt(total)} detections</span>
      <span>peak day <b style={{ color: "var(--acc)" }}>{fmd(peak.date)}</b> ({peak.count})</span>
      <span>{active}/{days.length} active days</span>
      <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 3 }}>
        less {ramp.map((c, i) => <i key={i} style={{ width: 11, height: 11, background: c, borderRadius: 2, display: "inline-block" }} />)} more
      </span>
    </div>
    <div className="scroll">
      <svg width={W} height={H}>
        {mlabels.map(l => <text key={l.m} x={labelW + l.col * pitch} y={11} fontSize={10} fill="#8b90a0">{MONTHS[l.m]}</text>)}
        {["M", "W", "F"].map((w, i) => <text key={w} x={4} y={top + (i * 2 + 1) * pitch + 11} fontSize={9} fill="#8b90a0">{w}</text>)}
        {cells.map(d => <rect key={d.date} x={d.x} y={d.y} width={size} height={size} rx={3} fill={ramp[d.lvl]}
          stroke={d.date === focus ? "#fff" : "none"} strokeWidth={2} style={{ cursor: "pointer" }} onClick={() => onPick(d.date)}>
          <title>{d.date}: {d.count} (raw {d.raw} · FRP {d.frp})</title></rect>)}
      </svg>
    </div>
  </>;
}

export default function App() {
  const [meta, setMeta] = useState({ n: 0 }), [bbox, setBbox] = useState(null), [pick, setPick] = useState(false);
  const [cal, setCal] = useState([]), [pts, setPts] = useState([]), [cl, setCl] = useState([]), [an, setAn] = useState(null), [fc, setFc] = useState(null);
  const [day, setDay] = useState(null), [span, setSpan] = useState(1), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const [live, setLive] = useState(null), [diagKey, setDiagKey] = useState(0), [yearSel, setYearSel] = useState("all");
  const bb = bbox?.join(",");

  useEffect(() => { api("/meta").then(setMeta); }, []);
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
      setMeta(await (await fetch("/api/demo" + (mode === "transition" ? "?mode=transition" : ""), { method: "POST" })).json());
      setDiagKey(k => k + 1);
    } catch { setErr("Could not load demo data — is the backend running on :8000?"); }
    setBusy(false);
  }
  const end = day && new Date(new Date(day).getTime() + (span - 1) * 864e5).toISOString().slice(0, 10);
  useEffect(() => {
    if (!day) return;
    let dead = false;  // ignore stale responses when day/span/bbox change quickly
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
      else { setMeta(await r.json()); setDiagKey(k => k + 1); }
    } catch { setErr("Upload failed — could not reach the backend."); }
    setBusy(false); e.target.value = "";
  }
  const series = useMemo(() => cal.slice(-365).map(d => ({ date: d.date, actual: d.count })).concat((fc?.forecast || []).map(d => ({ date: d.date, forecast: d.count }))), [cal, fc]);
  const center = meta.bounds ? [(meta.bounds[0] + meta.bounds[2]) / 2, (meta.bounds[1] + meta.bounds[3]) / 2] : [0, 0];

  return <>
    <header><h1>🔥 Pyro-Harmony — Burning Activity Calendar</h1>
      <label className="filebtn"><input type="file" multiple accept=".csv,.txt" onChange={upload} style={{ display: "none" }} /><button onClick={e => { e.preventDefault(); e.currentTarget.parentElement.querySelector("input").click(); }} disabled={busy}>{busy ? "Loading…" : "Upload FIRMS CSVs"}</button></label>
      <button onClick={() => loadDemo()}>Load demo</button>
      <button onClick={() => loadDemo("transition")}>Load 2002–2024 demo</button>
      <span style={{ flex: 1 }} />
      {meta.n > 0 && <span className="mut">{meta.n.toLocaleString()} hotspots · {meta.start} → {meta.end} · {Object.entries(meta.sensors).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(", ")}</span>}
      <button className={pick ? "on" : ""} onClick={() => setPick(!pick)}>{pick ? "Click two corners…" : "Select area"}</button>
      {bbox && <button onClick={() => setBbox(null)}>Clear area</button>}
    </header>
    {err && <div className="card errbox" style={{ margin: "14px 20px" }}>⚠ {err}</div>}
    {!meta.n ? <div className="card" style={{ margin: 20 }}>
      <b>Pyro-Harmony</b> harmonizes MODIS + VIIRS active-fire records into one burning-activity calendar.
      <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button onClick={loadDemo}>{busy ? "Generating…" : "Try the 2020–2024 demo"}</button>
        <button onClick={() => loadDemo("transition")}>Try the 2002–2024 sensor-transition demo</button>
      </div>
      <div className="mut" style={{ marginTop: 10, maxWidth: 720 }}>
        Or upload NASA FIRMS archive CSVs (MODIS C6.1 / VIIRS S-NPP + NOAA-20/21). Sensors are harmonized automatically:
        confidence scales unified, low-confidence drops, per-sensor rescaling over the overlap period, ESFP footprint normalization.
      </div>
    </div> :
    <>
      <div style={{ padding: "14px 20px 0" }}><HeroStats meta={meta} /></div>
      <div className="grid">
        <div className="card wide"><h3 style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>Burning calendar
          <span className="mut" style={{ fontWeight: 400 }}>(harmonized daily detections · click a day)</span>
          <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <span className="mut">Year</span>
            <select value={yearSel} onChange={e => setYearSel(e.target.value)}>
              <option value="all">All years</option>
              {[...new Set(cal.map(d => d.date.slice(0, 4)))].reverse().map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </span>
        </h3>
          <Heatmap data={cal} onPick={setDay} focus={day} year={yearSel} /></div>
        <div className="card"><h3>Map · {day} {span > 1 && `→ ${end}`}</h3>
          <div style={{ marginBottom: 8 }}>{[1, 3, 7, 14].map(n => <button key={n} className={span === n ? "on" : ""} onClick={() => setSpan(n)} style={{ marginRight: 4 }}>{n}d</button>)}<span className="mut"> {cl.length} clusters (DBSCAN 550 m, ≥3 pts, 12 h)</span></div>
          <MapContainer key={center.join(",")} center={center} zoom={5} className="map" preferCanvas>
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap" />
            <Picker on={pick} onBox={b => { setBbox(b); setPick(false); }} />
            {bbox && <Rectangle bounds={[[bbox[0], bbox[1]], [bbox[2], bbox[3]]]} pathOptions={{ color: "#4af", fill: false }} />}
            {pts.map((p, i) => <CircleMarker key={i} center={[p.lat, p.lon]} radius={2} pathOptions={{ color: p.sensor === "VIIRS" ? "#ffb347" : "#ff4d4d", weight: 1 }} />)}
            {cl.map(c => <Polygon key={c.id} positions={c.hull} pathOptions={{ color: "#fff", weight: 1, fillOpacity: 0.25 }} />)}
            <LiveMapLayer live={live} />
          </MapContainer></div>
        <div className="card"><h3>Anomalies & critical periods</h3>
          {!an ? "Analyzing…" : an.note ? <span className="mut">{an.note}</span> : <>
            <div style={{ height: 110 }}><ResponsiveContainer><BarChart data={an.monthly}><XAxis dataKey="month" /><Tooltip /><Bar dataKey="avg" fill="#ff6a2b" /></BarChart></ResponsiveContainer></div>
            <p className="mut">Critical months (above avg + 1σ): {an.critical.map(c => c.month).join(", ") || "none"}</p>
            <div className="list">{an.anomalies.map(a => <div key={a.date} className="row" onClick={() => setDay(a.date)}><span>{a.date}</span><span>{a.count} vs {a.expected} exp · z={a.z}</span></div>)}</div></>}</div>
        <div className="card"><BriefingPanel bbox={bb} onPickDay={setDay} refreshKey={diagKey} /></div>
        <div className="card wide"><h3>Last year + 30-day forecast <span className="mut">{fc?.model ? `· ${fc.model}` : ""}</span></h3>
          <div style={{ height: 220 }}><ResponsiveContainer><LineChart data={series}><CartesianGrid stroke="#272b36" /><XAxis dataKey="date" minTickGap={40} /><YAxis /><Tooltip contentStyle={{ background: "#181b22" }} />
            <Line dataKey="actual" stroke="#ffa04a" dot={false} /><Line dataKey="forecast" stroke="#4af" strokeDasharray="5 3" dot={false} /></LineChart></ResponsiveContainer></div></div>
        <ClimatologyPanel bbox={bb} onPickDay={setDay} refreshKey={diagKey} />
        <DiagnosticPanel bbox={bb} refreshKey={diagKey} />
        <LivePanel onLoaded={setLive} />
      </div>
    </>}
  </>;
}
