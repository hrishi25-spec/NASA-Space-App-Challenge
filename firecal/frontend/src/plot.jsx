import React, { useState } from "react";

/* ---------------------------------------------------------------- SVG chart kit
   This console draws exactly three things: a percentile envelope with a median line, a
   grouped bar pair per year, and two line series over dates. Recharts covered that in a
   404 kB chunk (108 kB gzipped) plus its transitive d3/victory packages — a whole
   dependency family for three charts. These ~130 lines replace it, and match the
   hand-rolled calendar heatmap that was already in App.jsx.

   Deliberately not general-purpose: no scales library, no animation, no responsive
   container. A fixed viewBox scales to the container (`preserveAspectRatio` keeps text
   undistorted), and hover state is one index — enough for a tooltip readout.
*/

/**
 * Axis step and top for a maximum, both multiples of a readable step (1/2/2.5/5 × 10^n).
 * Dividing the top into equal parts instead produced ticks like 0 / 1 / 3 / 4 / 5k, because
 * a 5k top with four parts is 1.25k per gridline and the labels have to round.
 */
function axisScale(max, ticks) {
  if (!(max > 0)) return { step: 1, top: 1 };
  const raw = max / Math.max(1, ticks);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = mag * ([1, 2, 2.5, 5, 10].find(s => raw / mag <= s) ?? 10);
  return { step, top: step * Math.ceil(max / step) };
}

const VB_W = 720;          // viewBox width: scales with the container
const PAD_L = 46, PAD_R = 12, PAD_T = 12, PAD_B = 26;

/**
 * @param rows      array of records, one per x position
 * @param xKey      key holding the x value (used for labels/tooltips)
 * @param series    [{key, type: "line"|"band"|"bar", name, color, dash, keyHigh, keyLow, group}]
 * @param yFmt/xFmt tick formatters
 */
export function Chart({
  rows, series, xKey, xFmt = String, yFmt = v => Math.round(v),
  height = 250, xTicks = 7, yTicks = 4, ariaLabel, tickFmt,
}) {
  const [hover, setHover] = useState(null);
  const n = rows.length;
  const plotH = height - PAD_T - PAD_B, plotW = VB_W - PAD_L - PAD_R;

  // Axis top covers every drawn value, including both edges of a band.
  let peak = 0;
  for (const row of rows) {
    for (const s of series) {
      for (const v of [row[s.key], s.type === "band" ? row[s.keyHigh] : null]) {
        if (typeof v === "number" && v > peak) peak = v;
      }
    }
  }
  const { step, top: yMax } = axisScale(peak, yTicks);
  const xAt = i => PAD_L + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
  const yAt = v => PAD_T + plotH - (Math.max(0, Math.min(typeof v === "number" ? v : 0, yMax)) / yMax) * plotH;

  const yTicksAt = Array.from({ length: Math.round(yMax / step) + 1 }, (_, k) => k * step);
  const xStep = Math.max(1, Math.round((n - 1) / Math.max(1, xTicks - 1)));
  const xTickIdx = [];
  for (let i = 0; i < n; i += xStep) xTickIdx.push(i);
  if (xTickIdx.length > 1 && xTickIdx.at(-1) !== n - 1) xTickIdx.push(n - 1);

  const groups = series.filter(s => s.type === "bar");
  const groupCount = Math.max(1, new Set(groups.map(s => s.group ?? 0)).size);
  const barW = Math.max(1.5, (plotW / Math.max(1, n)) * 0.62 / groupCount);

  const onMove = event => {
    const box = event.currentTarget.getBoundingClientRect();
    const frac = (event.clientX - box.left) / box.width;
    const i = Math.round(((frac * VB_W - PAD_L) / plotW) * (n - 1));
    setHover(i >= 0 && i < n ? i : null);
  };
  const h = hover == null ? null : rows[hover];
  const label = v => (tickFmt ? tickFmt(v) : xFmt(v));

  return <div className="plot" style={{ position: "relative" }}>
    <div className="plotLegend" role="list">
      {series.map(s => <span className="plotKey" role="listitem" key={s.name}>
        <i style={{ background: s.type === "line" ? "none" : s.color,
                    borderTop: s.type === "line" ? `2px ${s.dash ? "dashed" : "solid"} ${s.color}` : "none" }} />
        {s.name}
      </span>)}
      {h && <span className="plotReadout">
        <b>{label(h[xKey])}</b>
        {series.map(s => s.type === "band"
          ? <span key={s.name}>{s.name} {yFmt(h[s.keyLow])}–{yFmt(h[s.keyHigh])}</span>
          : <span key={s.name}>{s.name} {yFmt(h[s.key])}</span>)}
      </span>}
    </div>
    <svg viewBox={`0 0 ${VB_W} ${height}`} width="100%" height={height} role="img"
      aria-label={ariaLabel} preserveAspectRatio="xMidYMid meet"
      onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      {/* gridlines + y axis */}
      {yTicksAt.map((t, k) => <g key={k}>
        <line x1={PAD_L} x2={VB_W - PAD_R} y1={yAt(t)} y2={yAt(t)} stroke="#1e282d" />
        <text x={PAD_L - 6} y={yAt(t) + 3} fontSize="9" fill="#7b8c92" textAnchor="end">{yFmt(t)}</text>
      </g>)}
      {/* x axis labels */}
      {xTickIdx.map(i => <text key={i} x={xAt(i)} y={height - 8} fontSize="9" fill="#7b8c92"
        textAnchor="middle">{label(rows[i][xKey])}</text>)}

      {series.map(s => {
        if (s.type === "band") {
          // Envelope drawn between its two edges. (The previous Recharts version stacked
          // the two Areas, so the filled region summed p90 on top of p95 instead of
          // covering the band between them.)
          const up = rows.map((r, i) => `${i ? "L" : "M"}${xAt(i)},${yAt(r[s.keyHigh])}`).join(" ");
          const down = rows.map((r, i) => `L${xAt(n - 1 - i)},${yAt(rows[n - 1 - i][s.keyLow])}`).join(" ");
          return <path key={s.name} d={`${up} ${down} Z`} fill={s.color} fillOpacity={s.opacity ?? 0.35} />;
        }
        if (s.type === "bar") {
          const gi = [...new Set(groups.map(g => g.group ?? 0))].indexOf(s.group ?? 0);
          const w = plotW / Math.max(1, n);
          const groupWidth = w * 0.62;
          return <g key={s.name}>{rows.map((r, i) => {
            const x = xAt(i) - groupWidth / 2 + gi * (groupWidth / groupCount);
            const y = yAt(r[s.key]);
            return <rect key={i} x={x} y={y} width={Math.max(1, groupWidth / groupCount - 1)}
              height={Math.max(0, PAD_T + plotH - y)} fill={s.color} fillOpacity={0.85}>
              <title>{`${label(r[xKey])} · ${s.name} ${yFmt(r[s.key])}`}</title>
            </rect>;
          })}</g>;
        }
        return <path key={s.name} d={rows.map((r, i) => `${i ? "L" : "M"}${xAt(i)},${yAt(r[s.key])}`).join(" ")}
          fill="none" stroke={s.color} strokeWidth={s.width ?? 2}
          strokeDasharray={s.dash ? "5 3" : undefined} strokeLinejoin="round" />;
      })}

      {/* hover guide: one vertical line and a marker per series, not a node per point */}
      {hover != null && <line x1={xAt(hover)} x2={xAt(hover)} y1={PAD_T} y2={PAD_T + plotH}
        stroke="#7fd1c8" strokeOpacity="0.5" strokeDasharray="3 3" />}
    </svg>
  </div>;
}

/* Components only above: a second, non-component export would stop React Fast Refresh
   from hot-swapping this module (Vite warns about exactly that). */
