import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  FALLBACK_W, PAD, TIP_W, axisScale, nearestIndex, peak, plotHeight, plotWidth, runs,
  tickCount, tickValues, tooltipLeft, xAt, xTickIndices, yAt,
} from "./chartGeometry";

/* ---------------------------------------------------------------- SVG chart kit
   This console draws exactly three things: a percentile envelope with a median line, a grouped
   bar pair per year, and two line series over dates. Recharts covered that in a 404 kB chunk
   (108 kB gzipped) plus its transitive d3/victory packages — a whole dependency family for
   three charts. These ~220 lines replace it, and match the hand-rolled calendar heatmap that
   was already in App.jsx.

   The chart is laid out 1:1 with its container rather than scaled inside a fixed viewBox.
   `useWidth` measures the widget and the viewBox is set to that many units wide, so the plot
   fills the whole tab at any size, a 9px tick label stays 9px (scaling a 720-wide viewBox up to
   a 1,400px tab used to shrink the text and letterbox the plot), and a 1,400px gridline stays
   one device pixel thick. All the arithmetic lives in chartGeometry.js, which the prebuild
   guard can drive without a browser.

   Interaction is one hovered row index: a crosshair, a marker per series and a floating
   tooltip card. The pointer's exact x is deliberately *not* state — the tooltip snaps to the
   crosshair, so moving the mouse sideways inside a column does not re-render the chart.
*/

/** Container width in CSS px, re-measured whenever the tab, window or sidebar changes size. */
function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(Math.round(el.getBoundingClientRect().width));
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

const KEY_STEP = { ArrowRight: 1, ArrowLeft: -1, ArrowUp: 1, ArrowDown: -1, PageUp: 12, PageDown: -12 };

/**
 * @param rows      array of records, one per x position
 * @param xKey      key holding the x value (used for labels/tooltips)
 * @param series    [{key, type: "line"|"band"|"bar", name, color, dash, keyHigh, keyLow, group, fmt, opacity, width}]
 * @param yFmt/xFmt tick formatters; series.fmt overrides yFmt in the tooltip (e.g. exact counts
 *                  on an axis drawn in thousands)
 * @param yLabel    rotated axis title
 * @param onSelect  given, the plot becomes a brush: dragging reports the [i0, i1] row range
 */
export function Chart({
  rows, series, xKey, xFmt = String, yFmt = v => Math.round(v).toLocaleString(),
  height = 280, xTicks, yTicks, ariaLabel, tickFmt, yLabel, description,
  onSelect, selectHint = "Drag across the plot to zoom",
}) {
  const [wrapRef, measured] = useWidth();
  const width = measured || FALLBACK_W;
  const [hover, setHover] = useState(null);           // row index
  const [brush, setBrush] = useState(null);           // {a, b} while a selection is dragged
  const dragRef = useRef(null);

  const n = rows.length;
  const plotH = plotHeight(height);
  const axis = axisScale(peak(rows, series), yTicks ?? tickCount(plotH, 56, 6));
  const y = v => yAt(v, axis.top, height);
  const label = v => (tickFmt ? tickFmt(v) : xFmt(v));
  const xLabels = xTickIndices(n, xTicks ?? tickCount(plotWidth(width), 118, 12));
  const yLabels = tickValues(axis.top, axis.step).filter(t => t <= axis.top);

  const groups = series.filter(s => s.type === "bar");
  const groupCount = Math.max(1, new Set(groups.map(s => s.group ?? 0)).size);
  const rowUnit = plotWidth(width) / Math.max(1, n);
  // Bars are centred on their row, so the widest group overhangs the plot frame by half its
  // width — the outer bars used to be sliced off by the SVG edge. The rows move inward instead.
  const groupWidth = rowUnit * 0.62;
  const inset = groups.length ? groupWidth / 2 : 0;
  const x = i => xAt(i, n, width, inset);

  /** Pointer position in viewBox units, from a mouse or touch event. */
  const unitOf = event => {
    const clientX = event.touches?.[0]?.clientX ?? event.clientX;
    if (clientX == null) return null;
    const box = event.currentTarget.getBoundingClientRect();
    const px = Math.min(Math.max(clientX - box.left, 0), box.width);
    return (px / (box.width || 1)) * width;
  };

  const onMove = event => {
    const unit = unitOf(event);
    if (unit == null) return;
    const i = nearestIndex(unit, n, width, inset);
    setHover(prev => (prev === i ? prev : i));
    if (dragRef.current) {
      dragRef.current.b = i;
      setBrush({ a: dragRef.current.a, b: i });
    }
  };

  const onDown = event => {
    if (!onSelect || n < 2 || event.button > 0) return;
    const unit = unitOf(event);
    if (unit == null) return;
    const i = nearestIndex(unit, n, width, inset);
    dragRef.current = { a: i, b: i };
    setBrush({ a: i, b: i });
  };

  /* The release is caught on the window: a brush that ends outside the plot still zooms, and a
     drag that never left the chart is cleared either way. */
  useEffect(() => {
    const finish = () => {
      const d = dragRef.current;
      dragRef.current = null;
      setBrush(null);
      if (!d) return;
      const [i0, i1] = [d.a, d.b].sort((p, q) => p - q);
      if (i1 - i0 >= 2) onSelect(i0, i1);
    };
    window.addEventListener("mouseup", finish);
    window.addEventListener("touchend", finish);
    window.addEventListener("blur", finish);
    return () => {
      window.removeEventListener("mouseup", finish);
      window.removeEventListener("touchend", finish);
      window.removeEventListener("blur", finish);
    };
  }, [onSelect]);

  /* Keyboard walking, so the readout is not mouse-only. */
  const onKey = event => {
    if (!n) return;
    if (event.key === "Escape") { setHover(null); return; }
    const step = KEY_STEP[event.key];
    if (!step) return;
    const next = hover == null ? (step > 0 ? 0 : n - 1) : Math.max(0, Math.min(n - 1, hover + step));
    setHover(next);
    event.preventDefault();
  };

  const hoverRow = hover == null ? null : rows[hover];
  const tipValue = (s, row) => {
    const f = s.fmt || yFmt;
    if (s.type === "band") {
      const lo = row[s.keyLow], hi = row[s.keyHigh];
      return typeof lo === "number" && typeof hi === "number" ? `${f(lo)}–${f(hi)}` : null;
    }
    return typeof row[s.key] === "number" ? f(row[s.key]) : null;
  };
  const tip = hoverRow ? series.map(s => ({ s, v: tipValue(s, hoverRow) })).filter(it => it.v != null) : [];
  const swatch = s => s.type === "line"
    ? { background: "none", borderTop: `2px ${s.dash ? "dashed" : "solid"} ${s.color}` }
    : { background: s.color, opacity: s.opacity ?? 0.85 };

  return <div className="plot" ref={wrapRef}>
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img"
      tabIndex={0} aria-label={ariaLabel} onMouseMove={onMove} onMouseDown={onDown}
      onMouseLeave={() => { setHover(null); }} onKeyDown={onKey}
      onTouchStart={onMove} onTouchMove={onMove}>
      {/* gridlines + y axis */}
      {yLabels.map(t => <g key={t}>
        <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="#1e282d" />
        <text x={PAD.left - 8} y={y(t) + 3} fontSize="9" fill="#7b8c92" textAnchor="end">{yFmt(t)}</text>
      </g>)}
      {yLabel && <text className="plotAxisTitle" x="12" y={PAD.top + plotH / 2}
        textAnchor="middle" transform={`rotate(-90 12 ${PAD.top + plotH / 2})`}>{yLabel}</text>}
      {/* x axis labels */}
      {xLabels.map(i => <text key={i} x={x(i)} y={height - 8} fontSize="9"
        fill="#7b8c92" textAnchor="middle">{label(rows[i][xKey])}</text>)}

      {series.map(s => {
        if (s.type === "band") {
          /* Envelope drawn between its two edges. (An earlier version stacked two Areas, so the
             filled region summed p90 on top of p95 instead of covering the band between them.) */
          const segments = runs(n, i => typeof rows[i][s.keyLow] === "number" && typeof rows[i][s.keyHigh] === "number");
          return <g key={s.name}>{segments.map(seg => {
            const up = seg.map(i => `${i === seg[0] ? "M" : "L"}${x(i)},${y(rows[i][s.keyHigh])}`).join(" ");
            const down = [...seg].reverse().map(i => `L${x(i)},${y(rows[i][s.keyLow])}`).join(" ");
            return <path key={seg[0]} d={`${up} ${down} Z`} fill={s.color} fillOpacity={s.opacity ?? 0.35} />;
          })}</g>;
        }
        if (s.type === "bar") {
          const gi = [...new Set(groups.map(g => g.group ?? 0))].indexOf(s.group ?? 0);
          return <g key={s.name}>{rows.map((r, i) => {
            const left = x(i) - groupWidth / 2 + gi * (groupWidth / groupCount);
            const yy = y(r[s.key]);
            return <rect key={i} x={left} y={yy} width={Math.max(1, groupWidth / groupCount - 1)}
              height={Math.max(0, PAD.top + plotH - yy)} fill={s.color}
              fillOpacity={i === hover ? 1 : 0.8} />;
          })}</g>;
        }
        return <g key={s.name}>{runs(n, i => typeof rows[i][s.key] === "number").map(seg =>
          <path key={seg[0]} d={seg.map((i, k) => `${k ? "L" : "M"}${x(i)},${y(rows[i][s.key])}`).join(" ")}
            fill="none" stroke={s.color} strokeWidth={s.width ?? 2}
            strokeDasharray={s.dash ? "5 3" : undefined} strokeLinejoin="round" />)}</g>;
      })}

      {/* brush selection (only when the chart is zoomable) */}
      {brush && Math.abs(brush.b - brush.a) > 0 && <rect
        x={Math.min(x(brush.a), x(brush.b))} y={PAD.top}
        width={Math.abs(x(brush.b) - x(brush.a))} height={plotH}
        fill="#7fd1c8" fillOpacity="0.12" stroke="#7fd1c8" strokeOpacity="0.5" />}

      {/* hover guide: one crosshair and a marker per series, not a node per point */}
      {hover != null && <g>
        <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH}
          stroke="#7fd1c8" strokeOpacity="0.45" strokeDasharray="3 3" />
        {series.map(s => {
          const row = rows[hover];
          if (s.type === "band") {
            const lo = row[s.keyLow], hi = row[s.keyHigh];
            if (typeof lo !== "number" || typeof hi !== "number") return null;
            return <line key={s.name} x1={x(hover)} x2={x(hover)}
              y1={y(hi)} y2={y(lo)} stroke={s.color} strokeWidth="3" strokeOpacity="0.85" />;
          }
          if (typeof row[s.key] !== "number") return null;
          return <circle key={s.name} cx={x(hover)} cy={y(row[s.key])} r="3.4"
            fill={s.color} stroke="#0f1518" strokeWidth="1.5" />;
        })}
      </g>}
    </svg>

    {tip.length > 0 && <div className="plotTip" role="status"
      style={{ left: tooltipLeft(x(hover), width, TIP_W) }}>
      <div className="plotTipHead">{label(hoverRow[xKey])}</div>
      {tip.map(({ s, v }) => <div className="plotTipRow" key={s.name}>
        <i style={{ background: s.color, opacity: s.type === "band" ? (s.opacity ?? 0.55) : 1 }} />
        <span>{s.name}</span><b>{v}</b>
      </div>)}
    </div>}

    {/* The key sits under the plot, where a wide chart leaves room for it, with the caption on
        the left and the series on the right. */}
    <div className="plotLegend">
      {description && <span className="plotDesc">{description}</span>}
      <span className="plotKeys" role="list">
        {series.map(s => <span className="plotKey" role="listitem" key={s.name}>
          <i style={swatch(s)} />{s.name}
        </span>)}
      </span>
      {onSelect && <span className="plotHint">{selectHint}</span>}
    </div>
  </div>;
}

/* Components only above: a second, non-component export would stop React Fast Refresh
   from hot-swapping this module (Vite warns about exactly that). */
