import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar,
  CartesianGrid, ReferenceArea, Legend
} from "recharts";
import { AreaChart, Area, ComposedChart } from "recharts";
import { api, doyLabel, errMsg, fmt } from "./lib";

/* ---------------- Hero stats (left rail telemetry) ---------------- */
export function HeroStats({ meta, diag }) {
  const items = [
    { k: "HFII", v: fmt(diag?.stats?.hfi ?? meta?.hfi), cls: "acc", s: "harmonized fire intensity" },
    { k: "ESFP", v: fmt(diag?.stats?.esfp ?? meta?.esfp), cls: "cyan", s: "equivalent std pixels" },
    { k: "Hotspots", v: fmt(meta?.n), cls: "", s: `${Object.keys(meta?.sensors || {}).length} sensor record(s)` },
    { k: "Span", v: meta?.start ?? "—", cls: "", s: meta?.end ? `→ ${meta.end}` : "upload CSVs" },
  ];
  return <div className="panel">
    <h3>Telemetry</h3>
    <div className="stats">
      {items.map(i => <div key={i.k} className="stat">
        <div className="k">{i.k}</div>
        <div className={"v " + i.cls}>{i.v}</div>
        <div className="s">{i.s}</div>
      </div>)}
    </div>
  </div>;
}

/* ------------- 1. Multi-decadal DOY climatology + percentile envelope ------------- */
export function ClimatologyPanel({ bbox, onPickDay, refreshKey, embedded }) {
  const [c, setC] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let dead = false;
    api("/climatology", { bbox }).then(r => { if (!dead) { setC(r); setErr(null); } })
      .catch(() => !dead && setErr("Climatology unavailable (need ≥60 days of data)."));
    return () => { dead = true; };
  }, [bbox, refreshKey]);
  const body = () => {
    if (err) return <span className="hint">{err}</span>;
    if (!c || !c.summary) return <span className="hint">Analyzing…</span>;
    const peak = c.summary.peak_doy;
    const chartData = c.envelope.map(e => ({ ...e, label: doyLabel(e.doy) }));
    return <>
      <div className="hint" style={{ marginBottom: 6 }}>
        peak <b style={{ color: "var(--acc)" }}>{peak ? doyLabel(peak) : "—"}</b> · onset {c.summary.onset_doy ? doyLabel(c.summary.onset_doy) : "—"} ·
        cessation {c.summary.cessation_doy ? doyLabel(c.summary.cessation_doy) : "—"} · 10th/50th/90th/95th percentiles, 15-day window
      </div>
      <div style={{ height: 250 }}>
        <ResponsiveContainer>
          <AreaChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
            <CartesianGrid stroke="#141c30" />
            <XAxis dataKey="doy" tickFormatter={doyLabel} minTickGap={30} />
            <YAxis />
            <Tooltip labelFormatter={d => "DOY " + d + " · " + doyLabel(d)} contentStyle={{ background: "#0a0f1aee", border: "1px solid #26334f" }} />
            <Legend />
            <Area type="monotone" dataKey="p95" stackId="env" stroke="none" fill="#3a1d10" fillOpacity={0.7} name="95th pct band" baseLine={0} />
            <Area type="monotone" dataKey="p90" stackId="env" stroke="none" fill="#57240f" fillOpacity={0.8} name="90th pct band" baseLine={0} />
            <Area type="monotone" dataKey="p50" stroke="#ff7a2f" fill="none" strokeWidth={2} name="median" dot={false} />
            <Area type="monotone" dataKey="p10" stroke="#37e5ff" fill="none" strokeDasharray="4 3" name="10th pct" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="hint" style={{ marginTop: 6 }}>
        Shaded band = {`\u226590th`} percentile envelope (extreme fire days).
        Fire season {c.summary.onset_doy ? `${doyLabel(c.summary.onset_doy)} \u2192 ${doyLabel(c.summary.cessation_doy)}` : "n/a"}.
      </div>
    </>;
  };
  if (embedded) return body();
  return <div className="panel wide"><h3>Seasonal climatology</h3>{body()}</div>;
}

/* ------------- 2. Sensor Transition Illusion diagnostic ------------- */
export function DiagnosticPanel({ bbox, refreshKey, embedded }) {
  const [d, setD] = useState(null);
  useEffect(() => { api("/diagnostic", { bbox }).then(setD).catch(() => setD({ series: [] })); }, [bbox, refreshKey]);
  const body = () => {
    if (!d || !d.series?.length) return <span className="hint">No data loaded.</span>;
    const data = d.series.map(s => ({ ...s, rawM: s.modis / 1000, viirsM: s.viirs / 1000, adjM: s.adjusted / 1000 }));
    const hasPre = d.pre_2012_days > 0;
    return <>
      <div style={{ height: 260 }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
            <CartesianGrid stroke="#141c30" />
            <XAxis dataKey="year" />
            <YAxis label={{ value: "detections (k)", angle: -90, position: "insideLeft", fill: "#5f6b85", fontSize: 10 }} />
            <Tooltip contentStyle={{ background: "#0a0f1aee", border: "1px solid #26334f" }} />
            <Legend />
            <Bar dataKey="modis" name="MODIS raw" fill="#37e5ff" fillOpacity={0.8} />
            <Bar dataKey="viirs" name="VIIRS raw" fill="#ff5c6c" fillOpacity={0.8} />
            <Line type="monotone" dataKey="adjusted" name="harmonized" stroke="#ff7a2f" strokeWidth={2.5} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8, marginTop: 10 }}>
        <Stat k="Observed post-2012 surge" v={d.observed_growth_pct == null ? "n/a (no pre-2012 era)" : `+${d.observed_growth_pct}%`} bad={d.observed_growth_pct > 100} />
        <Stat k="After harmonization" v={d.adjusted_growth_pct == null ? "—" : `+${d.adjusted_growth_pct}%`} bad={false} />
        <Stat k="Artifact removed" v={d.artifact_pct == null ? "—" : `${d.artifact_pct} pp`} />
        <Stat k="VIIRS scaling factor" v={d.viirs_scaling ?? "—"} />
      </div>
      {d.calibration && <div className="hint" style={{ marginTop: 8 }}>
        Cross-calibration (2012–2015 overlap, {d.calibration.matched_fires.toLocaleString()} matchups): daily-count R² = {d.calibration.r2 ?? "—"},
        RMSE {d.calibration.rmse_mw ?? "—"} MW, VIIRS/MODIS FRP ratio {d.calibration.frp_ratio_viirs_to_modis},
        ESFP ratio {d.calibration.esfp_ratio_viirs_to_modis}.
      </div>}
      {!hasPre && <div className="hint" style={{ marginTop: 6 }}>
        This dataset starts after 2012, so the illusion can't be measured. Load the transition demo (or 2002+ archives) to see it.
      </div>}
    </>;
  };
  if (embedded) return body();
  return <div className="panel wide"><h3>Sensor Transition Illusion</h3>{body()}</div>;
}

function Stat({ k, v, bad }) {
  return <div className="stat">
    <div className="k">{k}</div>
    <div style={{ fontWeight: 700, fontSize: 16, color: bad ? "#ff5c6c" : "#3dffb0" }}>{v}</div>
  </div>;
}

/* ------------- 3. Live FIRMS feed panel ------------- */
const REGIONS = ["Global", "South_East_Asia", "South_America", "North_and_Central_America",
  "Africa", "Europe", "Northern_and_Central_Australia", "South_Asia"];

export function LivePanel({ onLoaded, wide }) {
  const [region, setRegion] = useState("Global");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);

  async function pull() {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`/api/live?region=${region}`);
      if (!r.ok) throw new Error(await errMsg(r));
      const j = await r.json();
      setRes(j);
      if (onLoaded) onLoaded(j);
    } catch (e) { setErr("Live feed failed: " + e.message); }
    setBusy(false);
  }

  return <div className="panel" style={wide ? { gridColumn: "1/-1" } : null}>
    <h3>Live FIRMS 24h feed
      <span className="mut">MODIS C6.1 + VIIRS S-NPP/NOAA-20/NOAA-21 · on-the-fly harmonization + DBSCAN</span>
      <span className="tools">
        <select value={region} onChange={e => setRegion(e.target.value)}>
          {REGIONS.map(r => <option key={r}>{r}</option>)}
        </select>
        <button className={"btn sm" + (busy ? "" : " primary")} onClick={pull} disabled={busy}>
          {busy ? "Fetching feeds… (up to ~2 min for Global)" : "Pull live hotspots"}
        </button>
      </span>
    </h3>
    {busy && <div className="hint">Downloading 24h CSVs from FIRMS, harmonizing, clustering…</div>}
    {err && <div className="errbox">⚠ {err}</div>}
    {res && <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8, marginBottom: 8 }}>
        <div className="stat"><div className="k">Feeds OK</div><div style={{ fontWeight: 700, fontSize: 14, color: "#3dffb0" }}>{res.feeds.join(", ")}</div></div>
        <div className="stat"><div className="k">HFII (24h)</div><div className="v acc" style={{ fontSize: 18 }}>{fmt(res.hfi)}</div></div>
        <div className="stat"><div className="k">Fire clusters (DBSCAN)</div><div className="v cyan" style={{ fontSize: 18 }}>{res.clusters.length}</div></div>
        <div className="stat"><div className="k">Detections</div><div style={{ fontWeight: 700, fontSize: 18 }}>{res.n.toLocaleString()}</div>
          <div className="s">{Object.entries(res.sensors).map(([k, v]) => `${k}: ${fmt(v)}`).join(" · ")}</div></div>
      </div>
      {res.errors?.length > 0 && <div className="hint">Feed errors: {res.errors.join("; ")}</div>}
      <div className="hint">
        Top clusters: {res.clusters.slice(0, 3).map(c => `(${c.lat.toFixed(2)}, ${c.lon.toFixed(2)}) ×${c.n}`).join(" · ") || "none"}
      </div>
    </>}
  </div>;
}

/* ------------- 4. Incident Commander briefing ------------- */
export function BriefingPanel({ bbox, onPickDay, refreshKey, mini, detail }) {
  const [b, setB] = useState(null);
  const [note, setNote] = useState(null);
  const [copied, setCopied] = useState(false);
  const load = (fmt2, cb) => api("/briefing", { bbox, format: fmt2 }).then(cb).catch(() => setNote("Briefing needs ≥60 days of data."));
  useEffect(() => { setNote(null); load("json", setB); }, [bbox, refreshKey]);

  async function copyMd() {
    try {
      const r = await fetch(`/api/briefing?format=markdown${bbox ? `&bbox=${bbox}` : ""}`);
      if (!r.ok) throw new Error(await errMsg(r));
      const t = await r.text();
      await navigator.clipboard.writeText(t);
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    } catch { setNote("Could not fetch markdown."); }
  }

  if (note) return mini ? <div className="panel"><h3>IC Briefing</h3><span className="hint">{note}</span></div> : note;
  if (!b) return mini ? <div className="panel"><h3>IC Briefing</h3><span className="hint">Analyzing…</span></div> : null;
  const threatColor = b.threat.level === "Critical" ? "#ff5c6c" : b.threat.level === "Elevated" ? "#ffcf5c" : b.threat.level === "Watch" ? "#ff7a2f" : "#3dffb0";
  const recs = mini ? b.recommendations.slice(0, 2) : b.recommendations;
  const streaks = mini ? b.streaks.slice(0, 3) : b.streaks;

  const content = <>
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
      <div className="stat" style={{ flex: "0 0 auto", minWidth: 130 }}>
        <div className="k">Threat</div>
        <div style={{ fontWeight: 700, fontSize: 17, color: threatColor, textShadow: `0 0 14px ${threatColor}44` }}>{b.threat.level}</div>
        <div className="s">score {b.threat.score}</div>
      </div>
      <div className="hint">
        record {b.record.mean_daily}/day · {b.record.days}d<br />
        last 30d {b.recent.mean_daily}/day (peak {b.recent.max_daily})
      </div>
      <span className="tools" style={{ marginLeft: "auto" }}>
        <button className="btn sm" onClick={copyMd}>{copied ? "Copied ✓" : "Copy MD"}</button>
      </span>
    </div>
    <div className="hint" style={{ margin: "2px 0" }}>Critical streaks (Z ≥ 2σ):</div>
    <div className="list" style={{ maxHeight: mini ? 120 : 180 }}>
      {streaks.length === 0 && <div className="hint">None at this threshold.</div>}
      {streaks.map(s => <div key={s.start} className="row" onClick={() => onPickDay && onPickDay(s.start)}>
        <span>{s.start} → {s.end} ({s.days}d)</span><span className="mut">z {s.max_z} · {s.total}</span>
      </div>)}
    </div>
    {!mini && b.biomes.length > 0 && <div style={{ marginTop: 8 }}>
      <div className="hint">Dominant fuel biomes (K-means on location + FRP):</div>
      {b.biomes.slice(0, 4).map((x, i) => <div key={i} style={{ fontSize: 12 }}>
        <b style={{ color: "var(--acc2)" }}>{x.kind}</b> — {x.n} fires, mean FRP {x.mean_frp} MW, spread ~{x.spread_km} km
      </div>)}
    </div>}
    <div className="recs" style={{ marginTop: 8 }}>
      {recs.map((r, i) => <div key={i}>{r}</div>)}
    </div>
  </>;

  if (mini) return <div className="panel"><h3>IC Briefing <span className="mut">incident commander</span></h3>{content}</div>;
  if (detail) return content;
  return <div className="panel"><h3>IC Briefing</h3>{content}</div>;
}
