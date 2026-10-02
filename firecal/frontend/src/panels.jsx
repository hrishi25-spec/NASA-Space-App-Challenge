import React, { useEffect, useState } from "react";
import { api, errMsg, fmt } from "./lib";

/* Chart panels (climatology, illusion diagnostic) live in charts.jsx so the SVG chart kit
   is only fetched when a chart tab is opened. Everything here is chart-free. */

/* Letter-case rule for this file: micro-labels and prose go in sentence case and let
   CSS uppercase them (see the contract at the top of styles.css). Acronyms are always
   written in full caps -- HFII, ESFP, FRP, MODIS, VIIRS, DBSCAN, FIRMS, MW. */

/* ---------------- Hero stats (left rail telemetry) ---------------- */
export function HeroStats({ meta }) {
  const items = [
    { k: "HFII", v: fmt(meta?.hfi), cls: "acc", s: "harmonized fire intensity" },
    { k: "ESFP", v: fmt(meta?.esfp), cls: "cyan", s: "equivalent std pixels" },
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

/* ------------- Live FIRMS feed panel ------------- */
/* The region list is the server's (`/meta.live_regions`), not a second copy kept here: an
   allowlist that only one side knows about turns into a 400 the day somebody edits it. The
   one-entry fallback is for an API that predates the field, and is always a valid choice. */
const FALLBACK_REGIONS = ["Global"];

export function LivePanel({ onLoaded, wide, bbox, region: aoRegion, onDatasetChanged, liveRegions }) {
  const options = liveRegions?.length ? liveRegions : FALLBACK_REGIONS;
  const [wanted, setWanted] = useState("Global");
  // Derived rather than stored, so a region that disappears from the list can never be the
  // value of the <select> while `pull` sends something else.
  const region = options.includes(wanted) ? wanted : options[0];
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [pulled, setPulled] = useState(null);

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

  /* The open 24 h feeds are global: every AOI looks like a single day. The FIRMS area API
     serves real 1-5 day windows for the AOI instead, but it needs a free MAP_KEY, so this
     button reports that plainly rather than hiding the capability. */
  async function pullArchive() {
    setBusy(true); setErr(null); setPulled(null);
    try {
      const q = new URLSearchParams({ days: "3" });
      if (bbox) q.set("bbox", bbox);
      else if (aoRegion) q.set("region", aoRegion);
      const r = await fetch("/api/archive?" + q, { method: "POST" });
      if (!r.ok) throw new Error(await errMsg(r));
      const m = await r.json();
      setPulled(`Merged a real ${m.days}-day ${m.source} window — ${fmt(m.n)} rows now loaded.`);
      onDatasetChanged?.(m);
    } catch (e) { setErr("Real-window pull failed: " + e.message); }
    setBusy(false);
  }

  const clusters = res?.clusters || [];
  const feeds = res?.feeds || [];
  const sensors = Object.entries(res?.sensors || {});

  return <div className="panel" style={wide ? { gridColumn: "1/-1" } : null}>
    <h3>Live FIRMS 24 h feed
      <span className="mut">MODIS C6.1 + VIIRS S-NPP/NOAA-20/NOAA-21 · on-the-fly harmonization + DBSCAN</span>
      <span className="tools">
        <select value={region} onChange={e => setWanted(e.target.value)}>
          {options.map(r => <option key={r}>{r}</option>)}
        </select>
        <button className={"btn sm" + (busy ? "" : " primary")} onClick={pull} disabled={busy}>
          {busy ? "Fetching feeds… (up to ~2 min for Global)" : "Pull live hotspots"}
        </button>
        <button className="btn sm" onClick={pullArchive} disabled={busy || (!bbox && !aoRegion)}
          title={bbox || aoRegion
            ? "Load a real 1-5 day FIRMS window for this AOI (needs FIRMS_MAP_KEY in .env)"
            : "Select an area or a region preset first"}>Real 3-day pull</button>
      </span>
    </h3>
    {busy && <div className="hint">Downloading 24 h CSVs from FIRMS, harmonizing, clustering…</div>}
    {err && <div className="errbox">⚠ {err}</div>}
    {pulled && <div className="hint">{pulled}</div>}
    {!bbox && !aoRegion && <div className="hint">Real 3-day pull needs an AOI — pick a region or draw one.</div>}
    {res && <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8, marginBottom: 8 }}>
        <div className="stat"><div className="k">Feeds online</div>
          <div style={{ fontWeight: 700, fontSize: 14, color: "#8fd6a4" }}>{feeds.join(", ") || "none"}</div></div>
        <div className="stat"><div className="k">HFII (24 h)</div><div className="v acc" style={{ fontSize: 18 }}>{fmt(res.hfi)}</div></div>
        <div className="stat"><div className="k">Clusters (DBSCAN)</div><div className="v cyan" style={{ fontSize: 18 }}>{clusters.length}</div></div>
        <div className="stat"><div className="k">Detections</div><div style={{ fontWeight: 700, fontSize: 18 }}>{fmt(res.n)}</div>
          <div className="s">{sensors.map(([k, v]) => `${k}: ${fmt(v)}`).join(" · ")}</div></div>
      </div>
      {res.errors?.length > 0 && <div className="hint">Feed errors: {res.errors.join("; ")}</div>}
      <div className="hint">
        Top clusters: {clusters.slice(0, 3).map(c => `(${c.lat.toFixed(2)}, ${c.lon.toFixed(2)}) ×${c.n}`).join(" · ") || "none"}
      </div>
    </>}
  </div>;
}

/* ------------- Incident Commander briefing ------------- */

// Threat ladder -> colour. A lookup beats a nested ternary: adding a level later can't
// silently fall through to the wrong colour.
const THREAT_COLOR = { Critical: "#e88a8a", Elevated: "#e9c46a", Watch: "#f2a65a" };
const OK_COLOR = "#8fd6a4";

/** The four sections of the report, shown one at a time so a long briefing stays readable. */
const BRIEFING_TABS = [
  { id: "situation", label: "Situation" },
  { id: "streaks", label: "Critical streaks" },
  { id: "fuel", label: "Fuel types" },
  { id: "actions", label: "Actions" },
];

export function BriefingPanel({ bbox, onPickDay, refreshKey, mini, detail }) {
  const [b, setB] = useState(null);
  const [note, setNote] = useState(null);
  const [copied, setCopied] = useState(false);
  const [sub, setSub] = useState("situation");
  const load = (format, cb, onFail) => api("/briefing", { bbox, format }).then(cb).catch(onFail);
  // Guarded like the charts: `/briefing` is answered from a client-side cache, so a slow
  // response for the previous AOI can land after a faster one for the next and overwrite it.
  useEffect(() => {
    let live = true;
    setNote(null); setB(null);
    load("json", b => { if (live) setB(b); },
         () => { if (live) setNote("Briefing needs ≥ 60 days of data."); });
    return () => { live = false; };
  }, [bbox, refreshKey]);

  async function copyMd() {
    try {
      const r = await fetch(`/api/briefing?format=markdown${bbox ? `&bbox=${bbox}` : ""}`);
      if (!r.ok) throw new Error(await errMsg(r));
      const t = await r.text();
      await navigator.clipboard.writeText(t);
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    } catch { setNote("Could not fetch markdown."); }
  }

  const shell = body => mini
    ? <div className="panel"><h3>IC Briefing <span className="mut">incident commander</span></h3>{body}</div>
    : body;

  if (note) return shell(<span className="hint">{note}</span>);
  if (!b) return shell(<span className="hint">Analyzing the record…</span>);

  // A thin window returns {note, threat, streaks, biomes, recommendations} with no record
  // or recent block, so every optional block is read defensively.
  if (b.note) return shell(<span className="hint">{b.note} — load a longer record to brief on it.</span>);

  const level = b.threat?.level ?? "Unknown";
  const threatColor = THREAT_COLOR[level] || OK_COLOR;
  const recs = b.recommendations || [];
  const streaks = b.streaks || [];
  const biomes = b.biomes || [];

  const threatCard = <div className="stat" style={{ flex: "0 0 auto", minWidth: 130 }}>
    <div className="k">Threat</div>
    <div style={{ fontWeight: 700, fontSize: 17, color: threatColor, textShadow: `0 0 14px ${threatColor}44` }}>{level}</div>
    <div className="s">score {b.threat?.score ?? "—"}</div>
  </div>;

  const recordRows = <>
    <div className="kv"><span className="mut">Record mean</span><b>{b.record?.mean_daily ?? "—"}/day over {b.record?.days ?? "—"} d</b></div>
    <div className="kv"><span className="mut">Last 30 days</span><b>{b.recent?.mean_daily ?? "—"}/day · peak {b.recent?.max_daily ?? "—"}</b></div>
  </>;

  const streakList = (limit, height) => <div className="list" style={{ maxHeight: height }}>
    {streaks.length === 0 && <div className="hint">None detected at this threshold — routine monitoring is sufficient.</div>}
    {streaks.slice(0, limit).map(s => <div key={s.start} className="row" onClick={() => onPickDay?.(s.start)}
      title={`Jump the map to ${s.start}`}>
      <span>{s.start} → {s.end} · {s.days} d</span><span className="mut">peak z {s.max_z} · {s.total} fires</span>
    </div>)}
  </div>;

  const biomeList = <div className="list" style={{ maxHeight: 200 }}>
    {biomes.length === 0 && <div className="hint">Not enough clustered detections to stratify.</div>}
    {biomes.map((x, i) => <div key={i} className="row" style={{ cursor: "default" }}>
      <span><b style={{ color: "#7fd1c8" }}>{x.kind}</b> · {x.n.toLocaleString()} fires</span>
      <span className="mut">mean FRP {x.mean_frp} MW · spread ~{x.spread_km} km</span>
    </div>)}
  </div>;

  /* ---- compact rail version: the headline only, no sub-tabs ---- */
  if (mini) return shell(<>
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
      {threatCard}
      <div style={{ flex: "1 1 130px", minWidth: 0 }}>{recordRows}</div>
    </div>
    <div className="hint" style={{ margin: "2px 0" }}>Critical streaks (z ≥ 2σ)</div>
    {streakList(3, 120)}
    <div className="recs" style={{ marginTop: 8 }}>
      {recs.slice(0, 2).map((r, i) => <div key={i}>{r}</div>)}
    </div>
  </>);

  /* ---- drawer version: the whole report, split across sub-tabs ---- */
  const body = <div style={{ maxWidth: 900 }}>
    <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
      {threatCard}
      <div style={{ flex: "1 1 240px", minWidth: 0 }}>{recordRows}</div>
      <span className="tools" style={{ marginLeft: "auto" }}>
        <button className="btn sm" onClick={copyMd}>{copied ? "Copied ✓" : "Copy MD"}</button>
      </span>
    </div>

    <div className="tabs sub" role="tablist" aria-label="Briefing sections">
      {BRIEFING_TABS.map(t => {
        const n = t.id === "streaks" ? streaks.length : t.id === "fuel" ? biomes.length : t.id === "actions" ? recs.length : null;
        return <button key={t.id} role="tab" aria-selected={sub === t.id}
          className={"tab" + (sub === t.id ? " on" : "")} onClick={() => setSub(t.id)}>
          {t.label}{n !== null && <span className="count">{n}</span>}
        </button>;
      })}
    </div>

    {sub === "situation" && <div>
      <div className="hint" style={{ marginBottom: 9 }}>
        Threat is a blend of the strongest anomaly, how long burning conditions persisted, and how
        hard the last 30 days are running against the multi-year record.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
        <div className="stat"><div className="k">Strongest anomaly</div>
          <div className="v acc" style={{ fontSize: 18 }}>{streaks[0] ? `z ${streaks[0].max_z}` : "—"}</div></div>
        <div className="stat"><div className="k">Anomalous days</div>
          <div className="v" style={{ fontSize: 18 }}>{streaks.reduce((s, x) => s + x.days, 0)}</div></div>
        <div className="stat"><div className="k">Critical windows</div>
          <div className="v cyan" style={{ fontSize: 18 }}>{streaks.length}</div></div>
        <div className="stat"><div className="k">Recent vs record</div>
          <div className="v" style={{ fontSize: 18 }}>{ratioLabel(b.recent?.mean_daily, b.record?.mean_daily)}</div></div>
      </div>
      <div className="hint" style={{ marginTop: 9 }}>
        Record window {b.record?.days ?? "—"} d · mean {b.record?.mean_daily ?? "—"} fires/day ·
        last 30 d mean {b.recent?.mean_daily ?? "—"}/day, peak {b.recent?.max_daily ?? "—"}.
      </div>
    </div>}

    {sub === "streaks" && <>
      <div className="hint" style={{ marginBottom: 9 }}>
        Consecutive days where burning ran at z ≥ 2σ above the seasonal norm, longest gap 2 days. Click a window to jump the map to it.
      </div>
      {streakList(10, 260)}
    </>}

    {sub === "fuel" && <>
      <div className="hint" style={{ marginBottom: 9 }}>
        Dominant fuel biomes — K-means stratified on location and fire radiative power.
      </div>
      {biomeList}
    </>}

    {sub === "actions" && <>
      <div className="hint" style={{ marginBottom: 9 }}>Recommended actions, highest priority first.</div>
      <div className="recs">{recs.map((r, i) => <div key={i}>{r}</div>)}</div>
      {recs.length === 0 && <div className="hint">No actions flagged — conditions are within climatological norms.</div>}
    </>}
  </div>;

  return detail ? body : <div className="panel"><h3>IC Briefing</h3>{body}</div>;
}

/** Recent-vs-record mean, phrased as a percentage swing: "+41%", "−12%", or "—". */
function ratioLabel(recent, record) {
  if (!record || recent == null) return "—";
  const pct = Math.round((recent / record - 1) * 100);
  const arrow = pct > 0 ? "+" : "−";
  return `${arrow}${Math.abs(pct)}%`;
}
