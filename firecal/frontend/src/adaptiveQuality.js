// Decides when a moving map is too slow to keep its full detail, and when it may have it back.
//
// A slow map is nearly always slow at one thing: shading the canvas while the camera moves. So
// the rule here is about motion, not about the machine. While a gesture is in flight we keep the
// last `window` frame times; once there are enough of them AND the motion has lasted
// `minMotionMs`, a mean frame time above `floorMs` means the map is not keeping up. Degrading is
// then sticky until the motion stops — a quality switch that flaps is worse than a steady lower
// one — and it is released only after `settleMs` of quiet, so a still map is always the
// full-detail map.
//
// Pure arithmetic over timestamps: no MapLibre, no DOM, no timers of its own, so the policy can
// be exercised from Node (`scripts/check-quality-policy.mjs`).
export function createQualityGovernor({
  floorMs = 30,       // mean frame time above this is not keeping up (≈33 fps)
  window = 24,        // frame times kept for that mean
  minSamples = 12,    // ... and this many are needed before judging anything
  minMotionMs = 400,  // a shorter burst of motion is never judged: too little evidence
  settleMs = 450,     // motion quiet for this long has ended
  onChange = () => {},
} = {}) {
  let active = false;
  let degraded = false;
  let previous = null;
  let startedAt = 0;
  let lastActivity = 0;
  const samples = [];

  const meanFrameMs = () => samples.reduce((sum, dt) => sum + dt, 0) / samples.length;

  return {
    get degraded() { return degraded; },

    // The camera is moving: the operator started a gesture, or a camera flight began. Called on
    // every gesture event — only the first one of a run opens a new measurement window.
    arm(now) {
      lastActivity = now;
      if (active) return;
      active = true;
      previous = null;
      startedAt = now;
      samples.length = 0;
    },

    // One rendered frame. Frames outside an armed window are ignored, which is what keeps an
    // idle map (and a hidden tab, where no frames arrive at all) from ever being judged.
    sample(now) {
      if (!active) return;
      if (previous === null) { previous = now; return; }
      const dt = now - previous;
      previous = now;
      if (dt <= 0 || dt > 1000) return;   // a stall is not a frame rate
      samples.push(dt);
      if (samples.length > window) samples.shift();
      if (degraded || samples.length < minSamples) return;
      if (now - startedAt < minMotionMs) return;
      if (meanFrameMs() <= floorMs) return;
      degraded = true;
      onChange(true);
    },

    // True once the motion has been quiet long enough: stop sampling, and hand the detail back.
    settled(now) { return active && now - lastActivity >= settleMs; },

    // End the window. Restores detail if this window had degraded.
    release() {
      if (!active) return;
      active = false;
      previous = null;
      samples.length = 0;
      if (!degraded) return;
      degraded = false;
      onChange(false);
    },
  };
}
