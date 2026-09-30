import React from "react";
import { Chart } from "./plot";

/* Colours mirror charts.jsx and the map legend: amber = observed fire signal,
   teal = modelled / harmonized output. */
const AMBER = "#f2a65a";
const TEAL = "#7fd1c8";

/** Lazy-loaded so no charting code is part of the first paint (see charts.jsx). */
export default function ForecastChart({ series, model }) {
  if (!series || !series.length)
    return <span className="hint">No calendar data yet — load a demo or upload FIRMS CSVs to fit a forecast.</span>;

  const observed = series.filter(d => d.actual != null).length;
  const lookahead = series.filter(d => d.forecast != null).length;

  return <>
    <div className="hint" style={{ marginBottom: 8 }}>
      {observed} observed days · {lookahead}-day forecast{model ? ` · method ${model}` : ""}
    </div>
    <Chart rows={series} xKey="date" height={240} xTicks={7}
      xFmt={d => String(d).slice(5)} ariaLabel="Observed daily detections with the forecast appended"
      series={[
        { key: "actual", type: "line", name: "Observed", color: AMBER },
        { key: "forecast", type: "line", name: "Forecast", color: TEAL, dash: true },
      ]} />
    {lookahead === 0 && <div className="hint" style={{ marginTop: 6 }}>
      No forecast window available for this record — the model needs a longer daily series.
    </div>}
  </>;
}
