import React, { useEffect, useState } from "react";
import {
  AreaChart, Area, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, CartesianGrid
} from "recharts";
import { api, doyLabel } from "./lib";

/**
 * Chart panels live in their own module on purpose: Recharts is the second-heaviest
 * dependency after MapLibre, and splitting it here means a low-end machine only
 * downloads and parses it when a chart tab is actually opened.
 *
 * Legend names are sentence case with acronyms in full caps ("MODIS raw",
 * "Harmonized") so the chart reads like the rest of the console.
 */

/** Colours mirror --acc / --acc2 in styles.css and the map's sensor legend. */
const C = {
  grid: "#1e282d",
  axis: "#7b8c92",
  tooltip: "#1a2226f2",
  amber: "#f2a65a",   // the fire signal / median
  teal: "#7fd1c8",    // modelled or harmonized output
  modis: "#e2635a",   // MODIS — same coral as the map dots
  viirs: "#f7b26a",   // VIIRS — same amber as the map dots
  band: ["#3a2418", "#57331d"],
  ok: "#8fd6a4",
  bad: "#e88a8a",
};

/**
 * Fetch for a panel, with a stale-response guard: a slow reply for an older AOI can
 * never overwrite the chart for the newer one, which would silently show the wrong
 * region. Clearing on refetch keeps the "Analyzing…" state honest.
 */
function useEndpoint(path, bbox, refreshKey) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    setData(null); setFailed(false);
    api(path, { bbox }).then(r => { if (live) setData(r); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [path, bbox, refreshKey]);
  return { data, failed };
}

/* ------------- 1. Multi-decadal DOY climatology + percentile envelope ------------- */
export function ClimatologyPanel({ bbox, refreshKey, embedded }) {
  const { data: c, failed } = useEndpoint("/climatology", bbox, refreshKey);

  const body = () => {
    if (failed) return <span className="hint">Climatology unavailable — needs ≥ 60 days of data.</span>;
    if (!c) return <span className="hint">Analyzing…</span>;
    // A thin selection answers 200 with {summary: null, envelope: [], note} rather than
    // failing, so surface its note instead of spinning on "Analyzing…" forever.
    if (!c.summary) return <span className="hint">{c.note || "Not enough data over this selection."}</span>;
    // The percentile envelope is what makes this chart worth plotting; without it there is
    // nothing to draw, so say so rather than dereferencing into an empty response.
    if (!Array.isArray(c.envelope) || !c.envelope.length) return <span className="hint">Not enough years to build a percentile envelope over this selection.</span>;
    const peak = c.summary.peak_doy;
    const chartData = c.envelope.map(e => ({ ...e, label: doyLabel(e.doy) }));
    const season = c.summary.onset_doy
      ? `${doyLabel(c.summary.onset_doy)} → ${doyLabel(c.summary.cessation_doy)}` : "n/a";
    return <>
      <div className="kv" style={{ marginBottom: 6 }}>
        <span className="mut">Peak day</span>
        <b style={{ color: C.amber }}>{peak ? doyLabel(peak) : "—"}</b>
      </div>
      <div className="kv" style={{ marginBottom: 8 }}>
        <span className="mut">Fire season</span><b>{season}</b>
      </div>
      <div style={{ height: 250 }}>
        <ResponsiveContainer>
          <AreaChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
            <CartesianGrid stroke={C.grid} />
            <XAxis dataKey="doy" tickFormatter={doyLabel} minTickGap={30} />
            <YAxis />
            <Tooltip labelFormatter={d => "DOY " + d + " · " + doyLabel(d)}
              contentStyle={{ background: C.tooltip, border: 0 }} />
            <Legend />
            <Area type="monotone" dataKey="p95" stackId="env" stroke="none" fill={C.band[0]} fillOpacity={0.7} name="95th pct band" baseLine={0} />
            <Area type="monotone" dataKey="p90" stackId="env" stroke="none" fill={C.band[1]} fillOpacity={0.8} name="90th pct band" baseLine={0} />
            <Area type="monotone" dataKey="p50" stroke={C.amber} fill="none" strokeWidth={2} name="Median" dot={false} />
            <Area type="monotone" dataKey="p10" stroke={C.teal} fill="none" strokeDasharray="4 3" name="10th pct" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="hint" style={{ marginTop: 6 }}>
        Shaded band = ≥ 90th percentile envelope (extreme fire days), percentiles over a 15-day window.
      </div>
    </>;
  };
  if (embedded) return body();
  return <div className="panel wide"><h3>Seasonal climatology</h3>{body()}</div>;
}

/* ------------- 2. Sensor Transition Illusion diagnostic ------------- */
export function DiagnosticPanel({ bbox, refreshKey, embedded }) {
  const { data: d, failed } = useEndpoint("/diagnostic", bbox, refreshKey);

  const body = () => {
    if (failed) return <span className="hint">Diagnostic unavailable for this selection.</span>;
    if (!d) return <span className="hint">Analyzing…</span>;
    if (!Array.isArray(d.series) || !d.series.length) return <span className="hint">{d.note || "No data loaded."}</span>;
    // A year with no detections of one sensor arrives without that key; default to 0 so the
    // bars stack to the truth instead of collapsing to NaN.
    const data = d.series.map(s => ({
      year: s.year,
      modis: (s.modis || 0) / 1000,
      viirs: (s.viirs || 0) / 1000,
      adjusted: (s.adjusted || 0) / 1000,
    }));
    const hasPre = d.pre_2012_days > 0;
    const cal = d.calibration;
    return <>
      <div style={{ height: 260 }}>
        <ResponsiveContainer>
          {/* left: 0 (not -10) so the rotated "Detections (k)" axis label has room and isn't clipped */}
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={C.grid} />
            <XAxis dataKey="year" />
            <YAxis label={{ value: "Detections (k)", angle: -90, position: "insideLeft", fill: C.axis, fontSize: 10 }} />
            <Tooltip contentStyle={{ background: C.tooltip, border: 0 }} />
            <Legend />
            <Bar dataKey="modis" name="MODIS raw" fill={C.modis} fillOpacity={0.85} />
            <Bar dataKey="viirs" name="VIIRS raw" fill={C.viirs} fillOpacity={0.85} />
            <Line type="monotone" dataKey="adjusted" name="Harmonized" stroke={C.teal} strokeWidth={2.5} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8, marginTop: 10 }}>
        <Stat k="Observed post-2012 surge" v={d.observed_growth_pct == null ? "n/a (no pre-2012 era)" : `+${d.observed_growth_pct}%`} bad={d.observed_growth_pct > 100} />
        <Stat k="After harmonization" v={d.adjusted_growth_pct == null ? "—" : `+${d.adjusted_growth_pct}%`} bad={false} />
        <Stat k="Artifact removed" v={d.artifact_pct == null ? "—" : `${d.artifact_pct} pp`} />
        <Stat k="VIIRS scaling factor" v={d.viirs_scaling ?? "—"} />
      </div>
      {cal && cal.matched_fires != null && <div className="hint" style={{ marginTop: 8 }}>
        Cross-calibration (2012–2015 overlap, {cal.matched_fires.toLocaleString()} matchups): daily-count R² = {cal.r2 ?? "—"},
        RMSE {cal.rmse_mw ?? "—"} MW, VIIRS/MODIS FRP ratio {cal.frp_ratio_viirs_to_modis ?? "—"},
        ESFP ratio {cal.esfp_ratio_viirs_to_modis ?? "—"}.
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
    <div style={{ fontWeight: 700, fontSize: 16, color: bad ? C.bad : C.ok }}>{v}</div>
  </div>;
}
