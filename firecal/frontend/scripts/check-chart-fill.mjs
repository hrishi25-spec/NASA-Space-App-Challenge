/**
 * Guards the chart layout, which is otherwise only visible by looking at it.
 *
 * Two failure modes are silent from the outside: a chart that regresses to a fixed viewBox and
 * is scaled (it letterboxes, shrinks its own labels, and no test feels it), and an axis, tooltip
 * or line that mishandles a value at the edge (a clipped band edge, a hover card off the card, a
 * forecast line dropping to zero across its nulls). src/chartGeometry.js holds every one of those
 * calculations as a pure function, so this drives them directly — no browser, no rendering, no
 * timing.
 *
 * Runs in `prebuild` alongside the lazy-export and adaptive-detail guards.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  FALLBACK_W, PAD, TIP_W, axisScale, nearestIndex, peak, plotHeight, plotWidth, runs,
  tickCount, tickValues, tooltipLeft, xAt, xTickIndices, yAt,
} from "../src/chartGeometry.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = name => readFileSync(join(here, "..", "src", name), "utf8");

const failures = [];
const check = (label, actual, expected) => {
  const pass = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${pass ? "ok  " : "FAIL"}  ${label}${pass ? "" : ` — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`}`);
  if (!pass) failures.push(label);
};

const checkClose = (label, actual, expected, eps = 1e-9) => {
  const pass = Math.abs(actual - expected) < eps;
  console.log(`${pass ? "ok  " : "FAIL"}  ${label}${pass ? "" : ` — expected ≈${expected}, got ${actual}`}`);
  if (!pass) failures.push(label);
};

const WIDE = 1400, NARROW = 420, H = 310, N = 74;

// 1. The plot fills the tab. This is the whole point: the old fixed 720-unit viewBox, scaled to
//    `width: 100%`, left the plot ~half the width of a desktop tab and shrank its own text.
check("a wide tab plots its full width, minus the axis gutters", plotWidth(WIDE), WIDE - PAD.left - PAD.right);
check("the first row sits on the left frame", xAt(0, N, WIDE), PAD.left);
check("the last row sits on the right frame", xAt(N - 1, N, WIDE), WIDE - PAD.right);
check("a wide chart is more than twice the old fixed one", plotWidth(WIDE) > 2 * plotWidth(FALLBACK_W), true);
check("a narrow chart still has a positive plot", plotWidth(NARROW) > 0, true);
check("a silly-narrow chart clamps instead of inverting", plotWidth(60), 80);
check("a single row is centred, not divided by zero", xAt(0, 1, WIDE), PAD.left + plotWidth(WIDE) / 2);
checkClose("rows are evenly spaced across the plot", xAt(10, N, WIDE) - xAt(9, N, WIDE), plotWidth(WIDE) / (N - 1));

// 2. The axis spans the frame and cannot clip a value.
check("the axis top is the frame top", yAt(6000, 6000, H), PAD.top);
check("zero is the frame floor", yAt(0, 6000, H), PAD.top + plotHeight(H));
check("a value above the axis clamps to the frame", yAt(99999, 6000, H), PAD.top);
check("a negative value clamps to the floor", yAt(-5, 6000, H), PAD.top + plotHeight(H));
check("a missing value is not plotted as a spike", yAt(undefined, 6000, H), PAD.top + plotHeight(H));

// 3. The axis covers both edges of every band, and ignores keys the series does not draw.
check("a band's upper edge sets the peak", peak([{ p50: 4, p95: 91 }], [{ key: "p50", type: "line", keyHigh: "p95" }]), 4);
check("a band series raises the peak with its high edge", peak([{ p50: 4, p10: 1, p95: 91 }],
  [{ key: "p50", type: "band", keyLow: "p10", keyHigh: "p95" }]), 91);
check("no rows means no peak", peak([], [{ key: "a", type: "line" }]), 0);
check("nulls do not become a peak", peak([{ a: null }], [{ key: "a", type: "line" }]), 0);

// 4. Ticks are readable round numbers, and the top is always a whole number of steps.
check("5,246 over 4 ticks lands on 0/2000/4000/6000", axisScale(5246, 4), { step: 2000, top: 6000 });
check("9.6 over 4 ticks lands on 10", axisScale(9.6, 4), { step: 2.5, top: 10 });
check("an empty series still has a usable axis", axisScale(0, 4), { step: 1, top: 1 });
check("gridlines run from zero to the top", tickValues(6000, 2000), [0, 2000, 4000, 6000]);
{
  let bad = null;
  for (let max = 1; max <= 20000; max = Math.ceil(max * 1.7)) {
    const { step, top } = axisScale(max, 4);
    const mantissa = step / 10 ** Math.floor(Math.log10(step));
    if (top < max || Math.abs(top / step - Math.round(top / step)) > 1e-9 || ![1, 2, 2.5, 5, 10].includes(mantissa)) bad = { max, step, top };
  }
  check("every axis is a readable step and covers its data", bad, null);
}

// 5. A wide chart gets more gridlines instead of the same handful strung far apart.
check("a wide plot asks for a label roughly every 118px", tickCount(plotWidth(WIDE), 118, 12), 11);
check("a narrow plot asks for fewer", tickCount(plotWidth(NARROW), 118, 12), 3);
check("never fewer than two labels", tickCount(10, 118, 12), 2);
check("the first and last row are always labelled", (() => {
  const idx = xTickIndices(N, 10);
  return [idx[0], idx[idx.length - 1]];
})(), [0, N - 1]);
check("label indices are unique and inside the data", (() => {
  const idx = xTickIndices(9, 4);
  return [new Set(idx).size === idx.length, idx.every(i => i >= 0 && i < 9)];
})(), [true, true]);
check("an empty series has no labels", xTickIndices(0, 7), []);
check("a label beside the last one is dropped, not overlapped", xTickIndices(74, 7), [0, 12, 24, 36, 48, 60, 73]);
check("labels never crowd each other", (() => {
  let worst = Infinity;
  for (let n = 2; n <= 400; n += 7) {
    for (let count = 2; count <= 12; count++) {
      const idx = xTickIndices(n, count);
      const step = Math.max(1, Math.round((n - 1) / (count - 1)));
      for (let k = 1; k < idx.length; k++) worst = Math.min(worst, (idx[k] - idx[k - 1]) / step);
    }
  }
  return worst >= 0.69;
})(), true);

// 6. A bar chart insets its rows by half a column, so the outer bars are not sliced off by the
//    SVG edge — they used to start left of the axis and end past the right frame.
check("the first column starts inside the frame", xAt(0, N, WIDE, 40) - 40, PAD.left);
check("the last column ends inside the frame", xAt(N - 1, N, WIDE, 40) + 40, WIDE - PAD.right);
check("an inset row still hovers its own column", nearestIndex(xAt(3, N, WIDE, 40), N, WIDE, 40), 3);

// 7. Hover snaps to the nearest row and clamps at the edges.
check("the left gutter hovers the first row", nearestIndex(2, N, WIDE), 0);
check("the right frame hovers the last row", nearestIndex(WIDE, N, WIDE), N - 1);
check("the middle of a wide plot hovers its middle row", nearestIndex(xAt(36, N, WIDE), N, WIDE), 36);
check("one row is a valid hover target", nearestIndex(500, 1, WIDE), 0);
check("no rows means nothing to hover", nearestIndex(500, 0, WIDE), null);

// 8. The hover card stays inside the chart, flipped rather than clipped.
check("a mid-plot card sits to the right of the crosshair", tooltipLeft(400, WIDE, TIP_W), 414);
check("a card near the right edge flips to the left", tooltipLeft(WIDE - 20, WIDE, TIP_W), WIDE - 20 - 14 - TIP_W);
check("a flipped card is still inside the chart", tooltipLeft(WIDE - 20, WIDE, TIP_W) + TIP_W < WIDE, true);
check("a card pinned to the left edge stays there", tooltipLeft(0, WIDE, TIP_W), 14);
check("a chart narrower than the card still keeps it on screen", tooltipLeft(100, 120, TIP_W), 14);

// 9. A missing value breaks a line instead of plotting it as zero. The forecast series is null
//    on every observed day, so a path through those nulls used to plunge to the axis floor.
check("nulls split a series into runs", runs(7, i => i !== 2 && i !== 3), [[0, 1], [4, 5, 6]]);
check("a fully drawn series is one run", runs(3, () => true), [[0, 1, 2]]);
check("a fully missing series draws nothing", runs(3, () => false), []);

// 10. Source-level guard: the plot must measure its container and must not go back to a scaled,
//    letterboxing viewBox; and the CSS card must be exactly the width the clamp assumes.
{
  const plot = read("plot.jsx");
  check("the chart re-measures its container", /ResizeObserver/.test(plot), true);
  check("the chart lays out in container pixels (no aspect-ratio scaling)", /preserveAspectRatio/.test(plot), false);
  check("the chart sets its viewBox from the measured width", /viewBox=\{`0 0 \$\{width\}/.test(plot), true);
  const tipRule = (read("styles.css").match(/\.plotTip\{[^}]*\}/) || [""])[0];
  check("the hover card's CSS width matches the clamp in JS", tipRule.includes(`width:${TIP_W}px`), true);
}

console.log(failures.length ? `\n${failures.length} FAILED` : "\nchart layout: all checks passed");
process.exit(failures.length ? 1 : 0);
