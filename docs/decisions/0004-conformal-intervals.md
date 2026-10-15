# 0004 — Split conformal intervals, implemented in-repo, on the log1p relative error

- **Date:** 2026-10-11
- **Status:** Accepted

## Context

The LightGBM forecast ([ADR 0003](0003-lightgbm-forecast.md)) is a point forecast. A number
without an uncertainty is the wrong shape for an incident commander: 40 detections a day means
something different when the plausible range is 30–55 than when it is 5–200, and the two are
indistinguishable in the current payload.

Two things had to be decided. **Which method** — parametric (a Gaussian or Tweedie residual
model), quantile regression, or conformal — and **whether to reach for a library** (MAPIE is
the usual one). And **what the interval is an interval *for***: the served quantity is an AOI
*aggregate* over many cells, and a hand-drawn AOI may be a quarter of a curated region or four
times one, so an interval measured in absolute detections for one region does not transfer.

## Decision

- **Split (inductive) conformal**, not parametric and not quantile regression. It makes no
  distributional assumption, which matters for a zero-inflated, over-dispersed count series,
  and it needs one pass over a held-out block rather than a second model or a new objective.
- **In-repo, not MAPIE.** The whole method is one order statistic: the
  `ceil((n+1)(1−α))`-th smallest absolute held-out residual. Pulling in MAPIE (and the typing
  and sklearn surface it brings) for that would be a heavier dependency for no more
  correctness, and every lazy-import and start-up rule in this repo would then have to be
  re-justified for it. `train_forecast._split_conformal_quantile` is that one line, and
  `test_smoke.py` tests it directly against a known answer.
- **Calibrated on a block strictly later than training.** The record is cut into three
  consecutive blocks — train, calibration, test — and the model is fitted on `train` alone,
  the quantiles come from `calibration` alone, and the reported coverage is measured on `test`
  alone. The number the docs quote was not fitted for. Time-ordered blocks are an
  approximation (conformal exchangeability is only approximately true for a series), which is
  stated rather than assumed away.
- **The interval is relative, in log1p space:** residuals are `log1p(actual) − log1p(pred)`
  and the band is `expm1(log1p(ŷ) ± q_h)`. That scales with the level, so one calibration
  table transfers from a curated region to an AOI of any size, and it can never go negative.
  Per-horizon quantiles, because the served forecast is recursive and its error grows with the
  horizon; a horizon past the calibrated window reuses the widest calibrated width instead of
  extrapolating one.
- **The band is additive and honest.** `/forecast` adds `lower`/`upper` per day and a
  `coverage` block only when the checkpoint was calibrated — the prior fallback emits neither
  rather than a band that was never measured for it. `coverage.within_tolerance` is `false`
  when the measured coverage is more than 5 points from nominal, and the chart labels the band
  *indicative* in that case.

## Consequences

- **The measured coverage is below nominal.** On the repository's synthetic fixture the
  nominal 90 % band measured 79–87 % coverage (five-region variant 75–83 %), so
  `within_tolerance` is `false` and the UI says the band is indicative. That is reported as
  the result rather than tuned until it looks calibrated — the honest alternative to a band
  that quietly overstates its precision.
- **No new dependency, no new lazy-import rule.** The band is pure NumPy on the serving side
  and one order statistic on the training side, so start-up is untouched.
- **The panel must draw the band only when the payload carries it.** The chart reads
  `lower`/`upper` for presence and `coverage` for the label; the seasonal-prior path has
  neither and shows none.
