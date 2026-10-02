/* ---------------------------------------------------------- chart geometry (pure)
   Every coordinate the SVG chart kit draws is a function of the widget's measured width, its
   height and the number of rows. Nothing here touches React or the DOM, which is what makes the
   layout checkable outside a browser: scripts/check-chart-fill.mjs drives these functions
   directly and asserts the properties the console relies on — the plot fills its container, a
   tick lands inside the frame, a tooltip never leaves the card, an axis can never clip a band
   edge, and a missing value breaks a line instead of dropping it to zero.
*/

/* Left gutter is wide: a 9px tick label like "5,246" plus the rotated axis title. */
export const PAD = { left: 58, right: 16, top: 16, bottom: 30 };

/** Width used for the single frame before the container has been measured. */
export const FALLBACK_W = 720;

/** Tooltip card width, in px. plot.jsx clamps with this and styles.css sizes `.plotTip` to it;
    scripts/check-chart-fill.mjs fails the build if the two drift apart. */
export const TIP_W = 210;

export const plotWidth = width => Math.max(80, width - PAD.left - PAD.right);
export const plotHeight = height => Math.max(60, height - PAD.top - PAD.bottom);

/** x of row `i` of `n`, in viewBox units. plot.jsx sets the viewBox to the measured container
    width, so one viewBox unit is one CSS pixel and a gridline stays hairline-thin at any size.
    `inset` pulls the rows inward, so a bar centred on x still fits inside the frame. */
export const xAt = (i, n, width, inset = 0) => {
  const w = plotWidth(width) - 2 * inset;
  const left = PAD.left + inset;
  return left + (n > 1 ? (i / (n - 1)) * w : w / 2);
};

/** y of value `v` on an axis whose top is `top`. Values outside the axis clamp to the frame. */
export const yAt = (v, top, height) => {
  const h = plotHeight(height);
  const safe = typeof v === "number" && Number.isFinite(v) ? Math.max(0, Math.min(v, top)) : 0;
  return PAD.top + h - (safe / top) * h;
};

/**
 * Axis step and top for a maximum, both multiples of a readable step (1/2/2.5/5 × 10^n).
 * Dividing the top into equal parts instead produced ticks like 0 / 1 / 3 / 4 / 5k, because
 * a 5k top with four parts is 1.25k per gridline and the labels have to round.
 */
export function axisScale(max, ticks = 4) {
  if (!(max > 0)) return { step: 1, top: 1 };
  const raw = max / Math.max(1, ticks);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = mag * ([1, 2, 2.5, 5, 10].find(s => raw / mag <= s) ?? 10);
  return { step, top: step * Math.ceil(max / step) };
}

/** Every gridline value from 0 to `top` on `step`. */
export const tickValues = (top, step) =>
  Array.from({ length: Math.round(top / step) + 1 }, (_, k) => k * step);

/** How many ticks fit in `span` px at roughly `target` px each. A wide chart gets more
    gridlines instead of the same seven labels strung far apart. */
export const tickCount = (span, target, max) =>
  Math.max(2, Math.min(max, Math.round(span / target)));

/** Row indices to label: the first and last are always labelled, so the axis spans the data. */
export function xTickIndices(n, count) {
  if (n <= 0) return [];
  const step = Math.max(1, Math.round((n - 1) / Math.max(1, count - 1)));
  const out = [];
  for (let i = 0; i < n; i += step) out.push(i);
  if (out[out.length - 1] !== n - 1) {
    // The step can leave the last label crowding the one before it (74 rows, 7 labels: 60 and
    // 72 sit one row either side of 73). The last row is the one that has to be labelled, so
    // the crowded neighbour is the one that goes.
    if (out.length > 1 && n - 1 - out[out.length - 1] < step * 0.7) out.pop();
    out.push(n - 1);
  }
  return out;
}

/** The row nearest `px` (px from the widget's left edge). Clamps outside the plot to an end.
    `inset` must match the inset the rows were drawn with (see xAt). */
export function nearestIndex(px, n, width, inset = 0) {
  if (!n) return null;
  if (n < 2) return 0;
  const i = Math.round(((px - PAD.left - inset) / (plotWidth(width) - 2 * inset)) * (n - 1));
  return Math.max(0, Math.min(n - 1, i));
}

/** Left offset (px) for a tooltip `tipW` wide: beside the crosshair, flipped when it would
    cross the right edge, and never outside the card. */
export function tooltipLeft(px, width, tipW, gap = 14) {
  const right = Math.max(gap, width - tipW - gap);
  const left = px + gap + tipW > width - gap ? px - gap - tipW : px + gap;
  return Math.max(gap, Math.min(left, right));
}

/** Highest value any series draws, band edges included, so the axis can never clip a band. */
export function peak(rows, series) {
  let max = 0;
  for (const row of rows) {
    for (const s of series) {
      const hi = s.type === "band" ? row[s.keyHigh] : null;
      for (const v of [row[s.key], hi]) if (typeof v === "number" && v > max) max = v;
    }
  }
  return max;
}

/**
 * Contiguous runs of drawn values, as lists of row indices. A missing value *breaks* a series
 * instead of being plotted as zero: the forecast series is null on every observed day, and a
 * path through those nulls used to plunge the dashed line to the axis floor.
 */
export function runs(length, drawn) {
  const out = [];
  let cur = null;
  for (let i = 0; i < length; i++) {
    if (drawn(i)) { if (!cur) { cur = []; out.push(cur); } cur.push(i); }
    else cur = null;
  }
  return out;
}
