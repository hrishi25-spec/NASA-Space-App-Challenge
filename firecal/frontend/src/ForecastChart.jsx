import React, { useState } from "react";
import { Chart } from "./plot";

/* Colours mirror charts.jsx and the map legend: amber = observed fire signal,
   teal = modelled / harmonized output. */
const AMBER = "#f2a65a";
const TEAL = "#7fd1c8";

/** Quick windows for the selector; the brush on the plot picks anything in between. */
const WINDOWS = [
  { value: "365", label: "Last 365 days" },
  { value: "180", label: "Last 180 days" },
  { value: "90", label: "Last 90 days" },
];

const pct = v => `${Math.round(v * 100)}%`;

/** Lazy-loaded so no charting code is part of the first paint (see charts.jsx). */
export default function ForecastChart({ series, model, coverage, checkpoint, model_reason, monthSel }) {
  // Row range into `series`: null means the whole record. Held in absolute indices so a second,
  // tighter drag inside a zoomed view composes instead of re-zooming from the full series.
  const [zoom, setZoom] = useState(null);
  // Filter series to the selected month if a month is chosen
  let workSeries = series;
  if (monthSel) {
    const monthStart = new Date(monthSel.year, monthSel.month - 1, 1);
    const monthEnd = new Date(monthSel.year, monthSel.month, 0);
    workSeries = series.filter(d => {
      const dDate = new Date(d.date);
      return dDate >= monthStart && dDate <= monthEnd;
    });
  }
  if (!workSeries || !workSeries.length)
    return <span className="hint">No calendar data yet — open a local archive or upload FIRMS CSVs to fit a forecast.</span>;

  const observed = workSeries.filter(d => d.actual != null).length;
  const lookahead = workSeries.filter(d => d.forecast != null || d.prior != null).length;
  // The archive model serves only the days its stored backtest earned; the rest is the
  // seasonal prior. The two are drawn as separate series so the switch is visible rather
  // than one dashed line implying a single method drew the whole window.
  const hasModel = workSeries.some(d => d.forecast != null);
  const hasPrior = workSeries.some(d => d.prior != null);
  const rows = zoom ? workSeries.slice(zoom[0], zoom[1] + 1) : workSeries;

  /* The interval is only drawn when the payload actually carries it. The archive model emits
     `lower`/`upper` per day once it was conformally calibrated; the seasonal-prior fallback
     emits neither, so no band appears rather than a band that was never measured. */
  const hasBand = workSeries.some(d => typeof d.lower === "number" && typeof d.upper === "number");
  const nominal = coverage?.nominal;
  const emp = coverage?.empirical
    ? Object.values(coverage.empirical).filter(v => typeof v === "number") : [];
  const bandName = nominal != null ? `${pct(nominal)} interval` : "Interval";

  const pickWindow = value =>
    value === "all" || Number(value) >= workSeries.length
      ? setZoom(null)
      : setZoom([workSeries.length - Number(value), workSeries.length - 1]);

  const scored_on = checkpoint?.scored_on || "global";
  const regionMASE = checkpoint?.metrics?.backtest?.by_region?.[scored_on]
    ? checkpoint.metrics.backtest.by_region[scored_on]
    : {};

  return <>
    <div className="chartControls">
      <span className="kv"><span className="mut">Model</span><b>{model || "Seasonal climatology"}</b></span>
      <span className="kv"><span className="mut">Record</span>
        <b>{observed} observed · {lookahead}-day forecast</b></span>
      {hasBand && nominal != null && <span className="kv"><span className="mut">Interval</span>
        <b>{pct(nominal)}{emp.length ? ` · measured ${pct(Math.min(...emp))}–${pct(Math.max(...emp))}` : ""}</b></span>}
      {zoom && <span className="kv"><span className="mut">Showing</span>
        <b>{rows[0].date} → {rows[rows.length - 1].date}</b></span>}
      {scored_on && scored_on !== "global" && <div className="hint" style={{ marginTop: 6, background: "var(--sh-lite)", padding: 6 }}>          <b>Scope:</b> {scored_on}{model_reason && <span className="hint"> {model_reason}</span>}</div>}
    </div>
    <Chart rows={rows} xKey="date" height={280} xFmt={d => String(d).slice(5)}
      yLabel="Detections / day" onSelect={(a, b) => setZoom(z => [z ? z[0] + a : a, z ? z[0] + b : b])}
      ariaLabel="Observed daily detections with the forecast appended and its calibrated interval"
      series={[
        ...(hasBand ? [{ key: "upper", keyLow: "lower", keyHigh: "upper", type: "band",
                         name: bandName, color: TEAL, opacity: 0.3 }] : []),
        { key: "actual", type: "line", name: "Observed", color: AMBER },
        ...(hasModel ? [{ key: "forecast", type: "line",
                          name: hasPrior ? "Forecast — archive model" : "Forecast",
                          color: TEAL, dash: true }] : []),
        ...(hasPrior ? [{ key: "prior", type: "line",
                          name: hasModel ? "Forecast — seasonal prior" : "Forecast",
                          color: TEAL, dash: true, width: 1.5 }] : []),
      ]} />
    <div className="chartControls end">
      <span className="hint">Window</span>
      <select value={zoom ? "custom" : "all"} onChange={e => pickWindow(e.target.value)}>
        <option value="all">All {workSeries.length} days</option>
        {WINDOWS.map(w => <option key={w.value} value={w.value}>{w.label}</option>)}
        {zoom && <option value="custom">Custom selection</option>}
      </select>
      {zoom && <button className="btn sm" onClick={() => setZoom(null)}>Reset zoom</button>}
    </div>
    {hasBand && coverage?.within_tolerance === false && <div className="hint" style={{ marginTop: 6 }}>
      The nominal {pct(nominal)} band measured {pct(Math.min(...emp))}–{pct(Math.max(...emp))} coverage on the
      held-out block it was scored against — more than a few points off, so read it as indicative
      rather than exactly calibrated.
    </div>}
    {hasModel && hasPrior && <div className="hint" style={{ marginTop: 6 }}>
      The archive model drew only the days its own backtest beat the seasonal prior at; the rest
      is the prior. Hover a day to see which series it came from.
    </div>}
    {regionMASE && <div className="hint" style={{ marginTop: 6, fontSize: 11 }}>
      <b>Regional MASE:</b> {json.stringify(regionMASE)}
    </div>}
    {lookahead === 0 && <div className="hint" style={{ marginTop: 6 }}>
      No forecast window available for this record — the model needs a longer daily series.
    </div>}
  </>;
}
