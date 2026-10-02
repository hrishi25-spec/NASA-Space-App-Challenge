import React, { useEffect, useState } from "react";
import { api, doyLabel, fmt } from "./lib";
import { Chart } from "./plot";

/**
 * Chart panels live in their own module on purpose: opening a chart tab downloads this
 * module, so the shell paints long before any charting code arrives.
 *
 * Both panels are a full-width chart with its key facts as a row of cards underneath, the way
 * the map keeps its readout under the canvas rather than beside it — a chart squeezed next to a
 * 220px sidebar is the thing that made these tabs read as a small box in the corner.
 *
 * Legend names are sentence case with acronyms in full caps ("MODIS raw", "Harmonized")
 * so the chart reads like the rest of the console.
 */

/* Colours mirror --acc / --acc2 in styles.css and the map's sensor legend. */
const C = {
  amber: "#f2a65a",   // the fire signal / median
  teal: "#7fd1c8",    // modelled or harmonized output
  modis: "#e2635a",   // MODIS — same coral as the map dots
  viirs: "#f7b26a",   // VIIRS — same amber as the map dots
  env: "#5a3524",     // envelope band (matches the heat ramp's mid brown)
  iqr: "#9a5327",
};

/** The rolling percentile window this app asks the API for; the chart caption names it, so the
    prose and the query can never describe different windows. */
const WINDOW = 15;

/**
 * Fetch for a panel, with a stale-response guard: a slow reply for an older AOI can
 * never overwrite the chart for the newer one, which would silently show the wrong
 * region. Clearing on refetch keeps the "Analyzing…" state honest.
 */
function useEndpoint(path, bbox, refreshKey, query = null) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  // A plain string key: passing the query object itself would refetch on every render.
  const q = query ? new URLSearchParams(query).toString() : "";
  useEffect(() => {
    let live = true;
    setData(null); setFailed(false);
    api(path, { bbox, ...query }).then(r => { if (live) setData(r); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [path, bbox, refreshKey, q]);
  return { data, failed };
}

/* ------------- 1. Multi-decadal DOY climatology + percentile envelope ------------- */
export function ClimatologyPanel({ bbox, refreshKey, embedded }) {
  const { data: c, failed } = useEndpoint("/climatology", bbox, refreshKey, { window: WINDOW });

  const body = () => {
    if (failed) return <span className="hint">Climatology unavailable — needs ≥ 60 days of data.</span>;
    if (!c) return <span className="hint">Analyzing…</span>;
    // A thin selection answers 200 with {summary: null, envelope: [], note} rather than
    // failing, so surface its note instead of spinning on "Analyzing…" forever.
    if (!c.summary) return <span className="hint">{c.note || "Not enough data over this selection."}</span>;
    // The percentile envelope is what makes this chart worth plotting; without it there is
    // nothing to draw, so say so rather than dereferencing into an empty response.
    if (!Array.isArray(c.envelope) || !c.envelope.length) return <span className="hint">Not enough years to build a percentile envelope over this selection.</span>;
    const season = c.summary.onset_doy
      ? `${doyLabel(c.summary.onset_doy)} → ${doyLabel(c.summary.cessation_doy)}` : "n/a";
    // The axis counts detections, but the hover readout is where a fractional median matters:
    // "52" hides the 51.73 that separates one day's signal from the next.
    const dec = v => (Math.round(v * 10) / 10).toLocaleString();
    return <div className="chartStack">
      {/* Sorted before drawing: the envelope path walks the edges in order. */}
      <Chart rows={[...c.envelope].sort((a, b) => a.doy - b.doy)} xKey="doy" xFmt={doyLabel}
        height={310} yLabel="Fire signal"
        description={`Percentile envelope and median fire day · rolling ${WINDOW}-day window`}
        ariaLabel="Day-of-year percentile envelope of harmonized daily detections"
        series={[
          { key: "p95", keyLow: "p10", keyHigh: "p95", type: "band", name: "10th–95th pct",
            color: C.env, opacity: 0.55, fmt: dec },
          { key: "p90", keyLow: "p50", keyHigh: "p90", type: "band", name: "50th–90th pct",
            color: C.iqr, opacity: 0.7, fmt: dec },
          { key: "p50", type: "line", name: "Median", color: C.amber, fmt: dec },
          { key: "p10", type: "line", name: "10th pct", color: C.teal, dash: true, width: 1.5, fmt: dec },
        ]} />
      <div className="chartStats">
        <Stat k="Peak day" v={c.summary.peak_doy ? doyLabel(c.summary.peak_doy) : "—"} tone="acc" />
        <Stat k="Fire season" v={season} />
        {/* years is a {year: series} map, not a list — and the backend already computed the
            exact peak, so read it rather than max() over the sampled envelope. */}
        <Stat k="Record" v={`${Object.keys(c.years || {}).length} yr`}
          note={`peak ${fmt(c.summary.peak_p95)} detections/day`} />
        <Stat k="Median day" v={fmt(c.summary.median_daily)} note="detections/day across the record" />
      </div>
      <div className="hint">
        Bands: the 10th–95th percentile envelope of daily detections (extreme fire days) with the
        50th–90th band inside it, over a centred {WINDOW}-day window across every year.
      </div>
    </div>;
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
    // bars stay put instead of collapsing to NaN.
    const rows = d.series.map(s => ({
      year: s.year,
      modis: (s.modis || 0) / 1000,
      viirs: (s.viirs || 0) / 1000,
      adjusted: (s.adjusted || 0) / 1000,
    }));
    // Bars are drawn in thousands so the axis stays short; the tooltip gives the exact count.
    const exact = v => Math.round(v * 1000).toLocaleString();
    const hasPre = d.pre_2012_days > 0;
    const cal = d.calibration;
    return <>
      <div className="chartStack">
        <Chart rows={rows} xKey="year" height={310} yLabel="Detections / year"
          yFmt={v => `${Math.round(v)}k`}
          description="Raw sensor counts per year against the comparable harmonized record"
          ariaLabel="Raw MODIS and VIIRS detections per year against the comparable harmonized record"
          series={[
            { key: "modis", type: "bar", name: "MODIS raw", color: C.modis, group: 0, fmt: exact },
            { key: "viirs", type: "bar", name: "VIIRS raw", color: C.viirs, group: 1, fmt: exact },
            { key: "adjusted", type: "line", name: "Harmonized", color: C.teal, width: 2.5, fmt: exact },
          ]} />
        <div className="chartStats">
          <Stat k="Observed post-2012 surge" v={d.observed_growth_pct == null ? "n/a (no pre-2012 era)" : `+${d.observed_growth_pct}%`} bad={d.observed_growth_pct > 100} />
          <Stat k="After harmonization" v={d.adjusted_growth_pct == null ? "—" : `+${d.adjusted_growth_pct}%`} />
          <Stat k="Artifact removed" v={d.artifact_pct == null ? "—" : `${d.artifact_pct} pp`} note="percentage points of the apparent trend" />
          <Stat k="VIIRS scaling factor" v={d.viirs_scaling ?? "—"} note="VIIRS detections per MODIS detection" />
        </div>
        {cal && cal.matched_fires != null && <div className="hint">
          Cross-calibration (2012–2015 overlap, {cal.matched_fires.toLocaleString()} matchups): daily-count R² = {cal.r2 ?? "—"},
          RMSE {cal.rmse_mw ?? "—"} MW, VIIRS/MODIS FRP ratio {cal.frp_ratio_viirs_to_modis ?? "—"},
          ESFP ratio {cal.esfp_ratio_viirs_to_modis ?? "—"}.
        </div>}
        {!hasPre && <div className="hint">
          {/* The endpoint says *why* in words, because a merged modern archive hits this every
              time and "n/a" alone reads like a bug rather than a question that was not asked. */}
          {d.note || "This dataset starts after 2012, so the illusion can't be measured."} Open an archive that reaches back past the sensor transition to see it.
        </div>}
      </div>
    </>;
  };
  if (embedded) return body();
  return <div className="panel wide"><h3>Sensor Transition Illusion</h3>{body()}</div>;
}

function Stat({ k, v, bad, note, tone }) {
  return <div className="stat">
    <div className="k">{k}</div>
    <div className={"v" + (bad ? " bad" : tone === "acc" ? " acc" : "")}>{v}</div>
    {note && <div className="s">{note}</div>}
  </div>;
}
