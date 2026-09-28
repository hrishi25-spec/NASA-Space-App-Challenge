import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar,
  CartesianGrid, ReferenceArea, Legend
} from "recharts";
import { AreaChart, Area, ComposedChart } from "recharts";
import { api, doyLabel, fmt } from "./lib";

const card = { marginBottom: 14 };

/* ---------------- Hero stats (poster header strip) ---------------- */
export function HeroStats({ meta, diag }) {
  const items = [
    { label: "Harmonized Fire Intensity (HFII)", value: fmt(diag?.stats?.hfi ?? meta?.hfi), sub: "Standardized radiative energy" },
    { label: "Equivalent Standard Pixels", value: fmt(diag?.stats?.esfp ?? meta?.esfp), sub: "Nadir-normalized footprints (ESFP)" },
    { label: "Hotspots harmonized", value: fmt(meta?.n), sub: `${Object.keys(meta?.sensors || {}).length} sensor record(s)` },
    { label: "Record span", value: meta?.start ? meta.start : "—", sub: meta?.end ? `→ ${meta.end}` : "upload CSVs to begin" },
  ];
  return <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 12, marginBottom: 14 }}>
    {items.map(i => <div key={i.label} className="card" style={{ margin: 0 }}>
      <div className="mut" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.6 }}>{i.label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: "var(--acc)", margin: "2px 0" }}>{i.value}</div>
      <div className="mut" style={{ fontSize: 12 }}>{i.sub}</div>
    </div>)}
  </div>;
}

/* ------------- 1. Multi-decadal DOY climatology + percentile envelope ------------- */
export function ClimatologyPanel({ bbox, onPickDay, refreshKey }) {
  const [c, setC] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let dead = false;
    api("/climatology", { bbox }).then(r => { if (!dead) { setC(r); setErr(null); } })
      .catch(() => !dead && setErr("Climatology unavailable (need ≥60 days of data)."));
    return () => { dead = true; };
  }, [bbox, refreshKey]);
  if (err) return <div className="card wide" style={card}><h3>Seasonal climatology</h3><span className="mut">{err}</span></div>;
  if (!c || !c.summary) return null;
  const peak = c.summary.peak_doy;
  const chartData = c.envelope.map(e => ({ ...e, label: doyLabel(e.doy) }));
  return <div className="card wide" style={card}>
    <h3>Seasonal climatology — day-of-year envelope
      <span className="mut"> · peak {peak ? doyLabel(peak) : "—"} ({peak}) · onset {c.summary.onset_doy ? doyLabel(c.summary.onset_doy) : "—"} ·
        cessation {c.summary.cessation_doy ? doyLabel(c.summary.cessation_doy) : "—"} · 10th/50th/90th/95th percentiles, 15-day window</span></h3>
    <div style={{ height: 240 }}>
      <ResponsiveContainer>
        <AreaChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
          <CartesianGrid stroke="#272b36" />
          <XAxis dataKey="doy" tickFormatter={doyLabel} minTickGap={30} />
          <YAxis />
          <Tooltip labelFormatter={d => "DOY " + d + " · " + doyLabel(d)} contentStyle={{ background: "#181b22", border: "1px solid #272b36" }} />
          <Legend />
          <Area type="monotone" dataKey="p95" stackId="env" stroke="none" fill="#3a1d10" fillOpacity={0.6} name="95th pct" />
          <Area type="monotone" dataKey="p90" stackId="env" stroke="none" fill="#57240f" fillOpacity={0.7} name="90th pct" />
          <Area type="monotone" dataKey="p50" stroke="#ffa04a" fill="none" strokeWidth={2} name="median" dot={false} />
          <Area type="monotone" dataKey="p10" stroke="#4a5164" fill="none" strokeDasharray="4 3" name="10th pct" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
    <div className="mut" style={{ fontSize: 12, marginTop: 6 }}>
      Shaded band = {`\u226590th`} percentile envelope (extreme fire days). Peak burning {peak ? `around ${doyLabel(peak)}` : ""};
      fire season {c.summary.onset_doy ? `${doyLabel(c.summary.onset_doy)} \u2192 ${doyLabel(c.summary.cessation_doy)}` : "n/a"}.
    </div>
  </div>;
}

/* ------------- 2. Sensor Transition Illusion diagnostic ------------- */
export function DiagnosticPanel({ bbox, refreshKey }) {
  const [d, setD] = useState(null);
  useEffect(() => { api("/diagnostic", { bbox }).then(setD).catch(() => setD({ series: [] })); }, [bbox, refreshKey]);
  if (!d || !d.series?.length) return null;
  const data = d.series.map(s => ({ ...s, rawM: s.modis / 1000, viirsM: s.viirs / 1000, adjM: s.adjusted / 1000 }));
  const hasPre = d.pre_2012_days > 0;
  return <div className="card wide" style={card}>
    <h3>Sensor Transition Illusion diagnostic
      <span className="mut"> · raw detections vs harmonized record · pre/post-2012 VIIRS deployment</span></h3>
    <div style={{ height: 250 }}>
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
          <CartesianGrid stroke="#272b36" />
          <XAxis dataKey="year" />
          <YAxis label={{ value: "detections (k)", angle: -90, position: "insideLeft", fill: "#8b90a0", fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "#181b22", border: "1px solid #272b36" }} />
          <Legend />
          <Bar dataKey="modis" name="MODIS raw" fill="#22d3ee" fillOpacity={0.85} />
          <Bar dataKey="viirs" name="VIIRS raw" fill="#ff4d4d" fillOpacity={0.85} />
          <Line type="monotone" dataKey="adjusted" name="harmonized" stroke="#ffa04a" strokeWidth={2.5} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginTop: 10 }}>
      <Stat label="Observed post-2012 surge" value={d.observed_growth_pct == null ? "n/a (no pre-2012 era)" : `+${d.observed_growth_pct}%`}
        bad={d.observed_growth_pct > 100} />
      <Stat label="After harmonization" value={d.adjusted_growth_pct == null ? "—" : `+${d.adjusted_growth_pct}%`}
        bad={false} />
      <Stat label="Artifact removed" value={d.artifact_pct == null ? "—" : `${d.artifact_pct} pp`} />
      <Stat label="VIIRS scaling factor" value={d.viirs_scaling ?? "—"} />
    </div>
    {d.calibration && <div className="mut" style={{ fontSize: 12, marginTop: 8 }}>
      Cross-calibration (2012–2015 overlap, {d.calibration.matched_fires.toLocaleString()} matchups): daily-count R² = {d.calibration.r2 ?? "—"},
      RMSE {d.calibration.rmse_mw ?? "—"} MW, VIIRS/MODIS FRP ratio {d.calibration.frp_ratio_viirs_to_modis},
      ESFP ratio {d.calibration.esfp_ratio_viirs_to_modis}, mean pixel {d.calibration.esfp_ratio_viirs_to_modis > 1 ? "smaller" : "larger"} for VIIRS.
    </div>}
    {!hasPre && <div className="mut" style={{ fontSize: 12, marginTop: 6 }}>
      Tip: this dataset starts after 2012, so the illusion can't be measured. Load the transition demo (or 2002+ archives) to see it.
    </div>}
  </div>;
}

function Stat({ label, value, bad }) {
  return <div style={{ background: "#1d212b", border: "1px solid var(--bd)", borderRadius: 8, padding: "8px 10px" }}>
    <div className="mut" style={{ fontSize: 11 }}>{label}</div>
    <div style={{ fontWeight: 700, fontSize: 17, color: bad ? "#ff6a6a" : "#9fe8b0" }}>{value}</div>
  </div>;
}

/* ------------- 3. Live FIRMS feed panel ------------- */
const REGIONS = ["Global", "South_East_Asia", "South_America", "North_and_Central_America",
  "Africa", "Europe", "Northern_and_Central_Australia", "South_Asia"];

export function LivePanel({ onLoaded }) {
  const [region, setRegion] = useState("Global");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);

  async function pull() {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`/api/live?region=${region}`);
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const j = await r.json();
      setRes(j);
      if (onLoaded) onLoaded(j);
    } catch (e) { setErr("Live feed failed: " + e.message); }
    setBusy(false);
  }

  return <div className="card wide" style={card}>
    <h3>Live NASA FIRMS 24h feed
      <span className="mut"> · MODIS C6.1 + VIIRS S-NPP/NOAA-20/NOAA-21 · on-the-fly harmonization + DBSCAN</span></h3>
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
      <select value={region} onChange={e => setRegion(e.target.value)} style={{ padding: "6px 8px" }}>
        {REGIONS.map(r => <option key={r}>{r}</option>)}
      </select>
      <button onClick={pull} disabled={busy}>{busy ? "Fetching feeds… (up to ~2 min for Global)" : "Pull live hotspots"}</button>
      {busy && <span className="mut">Downloading 24h CSVs from FIRMS, harmonizing, clustering…</span>}
      {res && <span className="mut">{res.n.toLocaleString()} detections · {Object.entries(res.sensors).map(([k, v]) => `${k}: ${v.toLocaleString()}`).join(" · ")}</span>}
    </div>
    {err && <div className="errbox" style={{ padding: "8px 10px", borderRadius: 6 }}>⚠ {err}</div>}
    {res && <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginBottom: 8 }}>
        <Stat label="Feeds OK" value={res.feeds.join(", ")} />
        <Stat label="HFII (24h)" value={fmt(res.hfi)} />
        <Stat label="Fire clusters (DBSCAN)" value={res.clusters.length} />
      </div>
      {res.errors?.length > 0 && <div className="mut" style={{ fontSize: 12 }}>Feed errors: {res.errors.join("; ")}</div>}
      <div className="mut" style={{ fontSize: 12 }}>
        Top clusters: {res.clusters.slice(0, 3).map(c => `(${c.lat.toFixed(2)}, ${c.lon.toFixed(2)}) ×${c.n}`).join(" · ") || "none"}
      </div>
    </>}
  </div>;
}

/* ------------- 4. Incident Commander briefing ------------- */
export function BriefingPanel({ bbox, onPickDay, refreshKey }) {
  const [b, setB] = useState(null);
  const [note, setNote] = useState(null);
  const [copied, setCopied] = useState(false);
  const load = (fmt2, cb) => api("/briefing", { bbox, format: fmt2 }).then(cb).catch(() => setNote("Briefing needs ≥60 days of data."));
  useEffect(() => { load("json", setB); }, [bbox, refreshKey]);

  async function copyMd() {
    try {
      const r = await fetch(`/api/briefing?format=markdown${bbox ? `&bbox=${bbox}` : ""}`);
      const t = await r.text();
      await navigator.clipboard.writeText(t);
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    } catch { setNote("Could not fetch markdown."); }
  }

  if (note) return <div className="card" style={card}><h3>Incident briefing</h3><span className="mut">{note}</span></div>;
  if (!b) return <div className="card" style={card}><h3>Incident briefing</h3><span className="mut">Analyzing…</span></div>;
  const threatColor = b.threat.level === "Critical" ? "#ff4d4d" : b.threat.level === "Elevated" ? "#ffa04a" : "#9fe8b0";
  return <div className="card" style={card}>
    <h3>Incident Commander briefing <span className="mut">· critical streaks, fuel biomes, actions</span></h3>
    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
      <div style={{ background: "#1d212b", border: `1px solid ${threatColor}`, borderRadius: 8, padding: "6px 12px" }}>
        <span className="mut" style={{ fontSize: 11 }}>THREAT </span>
        <b style={{ color: threatColor, fontSize: 16 }}>{b.threat.level}</b>
        <span className="mut"> · score {b.threat.score}</span>
      </div>
      <span className="mut">record mean {b.record.mean_daily}/day over {b.record.days} days · last 30d mean {b.recent.mean_daily}/day (peak {b.recent.max_daily})</span>
      <span style={{ flex: 1 }} />
      <button onClick={copyMd}>{copied ? "Copied ✓" : "Copy Markdown"}</button>
    </div>
    <div className="mut" style={{ fontSize: 12, margin: "4px 0" }}>Critical burning periods (consecutive days Z ≥ 2σ):</div>
    <div className="list" style={{ maxHeight: 130 }}>
      {b.streaks.length === 0 && <div className="mut">None at this threshold.</div>}
      {b.streaks.map(s => <div key={s.start} className="row" onClick={() => onPickDay && onPickDay(s.start)}>
        <span>{s.start} → {s.end} ({s.days}d)</span><span>peak z {s.max_z} · {s.total} fires</span>
      </div>)}
    </div>
    {b.biomes.length > 0 && <div style={{ marginTop: 8 }}>
      <div className="mut" style={{ fontSize: 12 }}>Dominant fuel biomes (K-means on location + FRP):</div>
      {b.biomes.slice(0, 4).map((x, i) => <div key={i} style={{ fontSize: 13 }}>
        <b>{x.kind}</b> — {x.n} fires, mean FRP {x.mean_frp} MW, spread ~{x.spread_km} km
      </div>)}
    </div>}
    <div style={{ marginTop: 8 }}>
      {b.recommendations.map((r, i) => <div key={i} style={{ fontSize: 13 }}>• {r}</div>)}
    </div>
  </div>;
}
