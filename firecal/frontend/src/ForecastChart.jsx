import React from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from "recharts";

/* Colours mirror charts.jsx and the map legend: amber = observed fire signal,
   teal = modelled / harmonized output. */
const AMBER = "#f2a65a";
const TEAL = "#7fd1c8";

/** Lazy-loaded so Recharts isn't part of the first paint (see charts.jsx). */
export default function ForecastChart({ series, model }) {
  if (!series || !series.length)
    return <span className="hint">No calendar data yet — load a demo or upload FIRMS CSVs to fit a forecast.</span>;

  const observed = series.filter(d => d.actual != null).length;
  const lookahead = series.filter(d => d.forecast != null).length;

  return <>
    <div className="hint" style={{ marginBottom: 8 }}>
      {observed} observed days · {lookahead}-day forecast{model ? ` · method ${model}` : ""}
    </div>
    <div style={{ height: 240 }}>
      <ResponsiveContainer>
        <LineChart data={series} margin={{ top: 6, right: 12, bottom: 0, left: -10 }}>
          <CartesianGrid stroke="#1e282d" />
          <XAxis dataKey="date" minTickGap={40} />
          <YAxis />
          <Tooltip contentStyle={{ background: "#1a2226f2", border: 0 }} />
          <Legend />
          <Line dataKey="actual" name="Observed" stroke={AMBER} dot={false} strokeWidth={2} />
          <Line dataKey="forecast" name="Forecast" stroke={TEAL} strokeDasharray="5 3" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
    {lookahead === 0 && <div className="hint" style={{ marginTop: 6 }}>
      No forecast window available for this record — the model needs a longer daily series.
    </div>}
  </>;
}
