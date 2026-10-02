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

/** Lazy-loaded so no charting code is part of the first paint (see charts.jsx). */
export default function ForecastChart({ series, model }) {
  // Row range into `series`: null means the whole record. Held in absolute indices so a second,
  // tighter drag inside a zoomed view composes instead of re-zooming from the full series.
  const [zoom, setZoom] = useState(null);
  if (!series || !series.length)
    return <span className="hint">No calendar data yet — load a demo or upload FIRMS CSVs to fit a forecast.</span>;

  const observed = series.filter(d => d.actual != null).length;
  const lookahead = series.filter(d => d.forecast != null).length;
  const rows = zoom ? series.slice(zoom[0], zoom[1] + 1) : series;

  const pickWindow = value =>
    value === "all" || Number(value) >= series.length
      ? setZoom(null)
      : setZoom([series.length - Number(value), series.length - 1]);

  return <>
    <div className="chartControls">
      <span className="kv"><span className="mut">Model</span><b>{model || "Seasonal climatology"}</b></span>
      <span className="kv"><span className="mut">Record</span>
        <b>{observed} observed · {lookahead}-day forecast</b></span>
      {zoom && <span className="kv"><span className="mut">Showing</span>
        <b>{rows[0].date} → {rows[rows.length - 1].date}</b></span>}
    </div>
    <Chart rows={rows} xKey="date" height={280} xFmt={d => String(d).slice(5)}
      yLabel="Detections / day" onSelect={(a, b) => setZoom(z => [z ? z[0] + a : a, z ? z[0] + b : b])}
      ariaLabel="Observed daily detections with the forecast appended"
      series={[
        { key: "actual", type: "line", name: "Observed", color: AMBER },
        { key: "forecast", type: "line", name: "Forecast", color: TEAL, dash: true },
      ]} />
    <div className="chartControls end">
      <span className="hint">Window</span>
      <select value={zoom ? "custom" : "all"} onChange={e => pickWindow(e.target.value)}>
        <option value="all">All {series.length} days</option>
        {WINDOWS.map(w => <option key={w.value} value={w.value}>{w.label}</option>)}
        {zoom && <option value="custom">Custom selection</option>}
      </select>
      {zoom && <button className="btn sm" onClick={() => setZoom(null)}>Reset zoom</button>}
    </div>
    {lookahead === 0 && <div className="hint" style={{ marginTop: 6 }}>
      No forecast window available for this record — the model needs a longer daily series.
    </div>}
  </>;
}
