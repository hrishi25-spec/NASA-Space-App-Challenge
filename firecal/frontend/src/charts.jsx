import React, { useEffect, useState } from "react";
import { api, doyLabel, fmt } from "./lib";
import { Chart } from "./plot";
import { monthRows, seasonRows, seasonVerdict } from "./chartGeometry";

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
export function ClimatologyPanel({ bbox, refreshKey, monthSel, embedded }) {
  const query = monthSel ? { window: WINDOW, month: `${monthSel.month}-${monthSel.year}` } : { window: WINDOW };
  const { data: c, failed } = useEndpoint("/climatology", bbox, refreshKey, query);

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

/* ------------- 3. Monthly anomaly views ------------- */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * One year's months against the band they are normal for.
 *
 * This is the view the pooled profile cannot give: every bar is that year's own mean daily
 * count for a calendar month, and the band is the mean ±1σ of the same month in the *other*
 * years — the judged year is left out of its own normal, so a record season cannot widen the
 * band it is being measured against. A month the record only partly covers has no bar (the
 * backend sends no mean for it), which is why a download that starts and ends mid-month draws
 * ten or eleven bars and the caption says so.
 */
function SeasonAgainstNormal({ seasons, year, onYear, selected, onPick }) {
  const chosen = seasons.find(s => s.year === Number(year)) || seasons[seasons.length - 1];
  const rows = seasonRows(chosen.months);
  const withValue = rows.filter(r => r.avg != null);
  const band = rows.some(r => r.low != null && r.high != null);
  const peak = withValue.length ? withValue.reduce((b, r) => (r.avg > b.avg ? r : b), withValue[0]) : null;
  const monthsWhere = verdict => rows.filter(r => seasonVerdict(r) === verdict).map(r => MONTHS[r.month - 1]);
  const above = monthsWhere("high"), below = monthsWhere("low");
  const odd = withValue.filter(r => r.z != null)
    .reduce((b, r) => (b == null || Math.abs(r.z) > Math.abs(b.z) ? r : b), null);
  const n = rows.find(r => r.n)?.n ?? 0;
  const dec = v => (Math.round(v * 10) / 10).toLocaleString();
  return <>
    <div className="chartControls">
      <span className="kv"><span className="mut">Year</span><b>{chosen.year}</b></span>
      <span className="kv"><span className="mut">Normal from</span>
        <b>{n ? `${n} other year${n === 1 ? "" : "s"}` : "not enough years"}</b></span>
      {selected && selected.year === chosen.year && <span className="kv">
        <span className="mut">Filtered to</span><b>{MONTHS[selected.month - 1]} {chosen.year}</b></span>}
      <select value={chosen.year}
        onChange={e => { onYear(Number(e.target.value)); onPick?.(null); }}
        aria-label="Year to judge against its normal band">
        {seasons.map(s => <option key={s.year} value={s.year}>{s.year}</option>)}
      </select>
    </div>
    {!withValue.length
      ? <span className="hint">No fully covered month in {chosen.year} for this selection.</span>
      : <>
        <Chart rows={rows} xKey="month" xFmt={m => MONTHS[m - 1]} height={310}
          yLabel="Mean detections / day"
          onPick={onPick ? i => onPick({ year: chosen.year, month: i + 1 }) : undefined}
          pickHint="Click a month to filter the calendar, map and anomaly list · Enter picks the hovered month"
          description={`${chosen.year} by month, against the same month in the other years`}
          ariaLabel={`${chosen.year} monthly mean daily detections against the normal band built from the other years`}
          series={[
            // Normal ±1σ band (std-based) when we have 2+ other years
            ...(band && !rows.some(r => r.normal_mad != null)
              ? [{ key: "high", keyLow: "low", keyHigh: "high", type: "band",
                  name: "Normal ±1σ", color: C.env, opacity: 0.6, fmt: dec }]
              : [],
            // MAD-based normal band (robust alternative for single-year std)
            ...(band && rows.some(r => r.normal_mad != null)
              ? [{ key: "high_mad", keyLow: "low_mad", keyHigh: "high_mad", type: "band",
                  name: "Normal ±1σ (MAD)", color: C.env, opacity: 0.3, fmt: dec }]
              : [],
            { key: "avg", type: "bar", name: String(chosen.year), color: C.amber, fmt: dec },
            ...(band && !rows.some(r => r.normal_mad != null)
              ? [{ key: "normal", type: "line", name: "Normal", color: C.teal,
                  dash: true, width: 2, fmt: dec }]
              : (band && rows.some(r => r.normal_mad != null)
                  ? [{ key: "normal_mad", type: "line", name: "Normal (MAD)", color: C.teal,
                      dash: true, width: 2, fmt: dec }]
                  : []),
          ]} />
        <div className="chartStats">
          <Stat k="Peak month" v={peak ? MONTHS[peak.month - 1] : "—"} tone="acc"
            note={peak ? `${dec(peak.avg)} detections/day in ${chosen.year}` : undefined} />
          <Stat k="Above normal" v={above.length ? above.join(" · ") : "None"}
            tone={above.length ? "acc" : undefined} note="months above the band" />
          <Stat k="Below normal" v={below.length ? below.join(" · ") : "None"}
            note="months below the band" />
          <Stat k="Most unusual" v={odd ? MONTHS[odd.month - 1] : "—"}
            note={odd ? `z = ${odd.z} against the other years` : "band needs two other years"} />
        </div>
      </>}
    <div className="hint">
      Bars are {chosen.year}'s own monthly means. The band is the mean ±1σ of the same calendar
      month in the other years, with the judged year left out — a record year inside its own band
      would widen it toward itself and hide the very anomaly this view exists for. Months the
      record only partly covers are left blank rather than drawn at zero, and a month averaging
      under five detections a day keeps its bar and band but is not called unusual: its spread
      across years is near zero, so a z-score from it would be arithmetic, not evidence.
      {onPick && <> Click a month to filter the calendar, the map and the anomalous-day list to
      it; click it again to clear.</>}
    </div>
  </>;
}

/**
 * The `monthly[]` series `/anomalies` has always returned, drawn for the first time: one bar per
 * calendar month, pooled across every year in the record, with the critical-month threshold
 * (`mean + 1σ`) as a line. The old panel showed only the day list and the names of the critical
 * months; the shape behind those names was invisible.
 *
 * It is a seasonal profile, not a month-by-month time series — the API groups by month number,
 * so every January is one bar — and the caption says so rather than letting "monthly" imply a
 * timeline. The threshold comes from the response, so the line and the `critical[]` list can
 * never disagree about where the cut is.
 *
 * Above it sits the per-year view: the same twelve months for one selected year, each against
 * the band its own year was excluded from. The profile answers "what is this region's season";
 * the per-year chart answers "was this season unusual", which pooling every year cannot.
 */
export function AnomalyPanel({ bbox, refreshKey, embedded, selected, onPickMonth }) {
  const { data: a, failed } = useEndpoint("/anomalies", bbox, refreshKey);
  // Which year the per-year chart judges. null means "the latest year the response carries",
  // so a new bbox that does not reach an older pick falls back instead of drawing nothing.
  const [year, setYear] = useState(null);
  const seasons = Array.isArray(a?.seasons) ? a.seasons : [];

  const body = () => {
    if (failed) return <span className="hint">Anomaly profile unavailable for this selection.</span>;
    if (!a) return <span className="hint">Analyzing…</span>;
    // A thin selection answers 200 with a note instead of a series; surface it rather than
    // drawing twelve empty bars as though the record had no season.
    if (!Array.isArray(a.monthly) || !a.monthly.length)
      return <span className="hint">{a.note || "Not enough data to build a monthly profile."}</span>;
    const rows = monthRows(a.monthly, a.threshold);
    const peak = rows.reduce((best, r) => (r.avg > best.avg ? r : best), rows[0]);
    const critical = (a.critical || []).map(c => MONTHS[c.month - 1] ?? c.month);
    const dec = v => (Math.round(v * 10) / 10).toLocaleString();
    return <div className="chartStack">
      {seasons.length > 1 && <>
        <div className="chartSub">The selected year</div>
        <SeasonAgainstNormal seasons={seasons} year={year} onYear={setYear}
          selected={selected} onPick={onPickMonth} />
      </>}
      <div className="chartSub">Seasonal profile</div>
      <Chart rows={rows} xKey="month" xFmt={m => MONTHS[m - 1]} height={310}
        yLabel="Mean detections / day"
        description="Mean daily detections by calendar month, with the critical-month threshold"
        ariaLabel="Mean daily detections in each calendar month against the critical-month threshold"
        series={[
          { key: "avg", type: "bar", name: "Monthly mean", color: C.amber, fmt: dec },
          { key: "threshold", type: "line", name: "Critical threshold (mean + 1σ)",
            color: C.teal, dash: true, width: 2, fmt: dec },
        ]} />
      <div className="chartStats">
        <Stat k="Peak month" v={MONTHS[peak.month - 1]} tone="acc"
          note={`${dec(peak.avg)} detections/day on average`} />
        <Stat k="Critical months" v={critical.length ? critical.join(" · ") : "None"}
          note="monthly means above mean + 1σ" />
        <Stat k="Threshold" v={a.threshold ?? "—"} note="mean + 1σ of the twelve monthly means" />
      </div>
      <div className="hint">
        Each bar pools that calendar month across every year in the record — a seasonal profile,
        not a month-by-month time series. Months above the dashed line are the critical months.
      </div>
    </div>;
  };
  if (embedded) return body();
  return <div className="panel wide"><h3>Monthly anomaly profile</h3>{body()}</div>;
}

/*** Year × month anomaly heatmap.
 *
 * The `/anomalies` endpoint already returns per-year, per-month z-scores in its
 * `seasons` block — this component renders them as a compact grid so every season
 * in the record can be compared at a glance, rather than teasing out one year at a
 * time with the per-year view.
 *
 * Calendar months run left → right (Jan → Dec). Years stack top → bottom, newest at the
 * top. Each cell shows avg daily detections with a color band indicating z-score.
 ***/

function AnomalyHeatmap({ seasons, year }) {
  // seasons is [{year, months:[{month, avg, days, normal, low, high, z, n}]}]
  if (!seasons || !seasons.length) return <span className="hint">No seasonal anomaly data.</span>;
  const yr = seasons.find(s => s.year === year) || seasons[seasons.length - 1];
  const months = yr.months || [];
  if (!months.length) return <span className="hint">No fully covered months in {yr.year}</span>;

  const monthMap = new Map(months.map(m => [m.month, m]));
  const hasZ = months.some(m => m.z != null);
  const dec = v => (Math.round(v * 10) / 10).toLocaleString();

  // Determine color based on z-score
  const zToColor = z => {
    if (z == null) return "#e0e0e0";
    if (z > 2) return "#d7191c"; // very high
    if (z > 1) return "#fdae61";  // high
    if (z > 0) return "#abd9e9";  // low positive
    if (z < -2) return "#7f0000"; // very low
    if (z < 0) return "#2b8cbe";  // low negative
    return "#ffffbf";            // near normal
  };

  const rowHeight = 28;
  const colWidth = 26;
  const margin = 4;
  const rows = months.length;
  const cols = 12; // Jan → Dec

  return <>
    <Chart rows={rows} xKey="doy" height={rows * rowHeight + 40} width={cols * colWidth + 40}
      yLabel="Year × Month anomaly heatmap"
      ariaLabel={`Anomaly heatmap for ${yr.year}: z-scores of mean daily detections per month against other years`}
      series={[
        { key: "cell", type: "rect", name: "Cell", color: (d, i) => {
          const m = i % 12 + 1; // month 1-12
          const mon = monthMap.get(m);
          if (!mon) return "#e0e0e0";
          const z = mon.z;
          return zToColor(z);
        } }
      ]} />
    <div style={{ position: "absolute", left: 20, top: rows * rowHeight + 20, fontSize: 10, color: "#666" }}>
      {MONTHS.map((m, i) => <div key={i} style={{ transform: `translateX(${i * colWidth}px)` }}>{m}</div>)}
    </div>
    <div style={{ position: "absolute", left: 10, top: 20, transform: `rotate(-90) translateY(-100%)`, fontSize: 10, color: "#666" }}>
      {seasons.map((s, i) => <div key={i} style={{ transform: `translateY(${i * rowHeight}px)` }}>{s.year}</div>)}
    </div>
  </>;
}

function Stat({ k, v, bad, note, tone }) {
  return <div className="stat">
    <div className="k">{k}</div>
    <div className={"v" + (bad ? " bad" : tone === "acc" ? " acc" : "")}>{v}</div>
    {note && <div className="s">{note}</div>}
  </div>;
}
