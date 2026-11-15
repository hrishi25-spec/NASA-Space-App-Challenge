/**
 * Guards the orbital drift, which failed silently in a way no test could feel: a fixed 0.12°
 * step on a 140 ms timer turned the globe at 0.86°/s — a full revolution every seven minutes,
 * which reads as a globe that is not moving — and it arrived in 7–14 discrete jumps a second.
 * Every one of those properties is arithmetic over time, so src/autoRotate.js holds it and this
 * script drives it with simulated frame cadences.
 *
 * Also checks the two wiring mistakes that made Auto-rotate fight the rest of the console: a
 * timer instead of animation frames, and its rotate events arming the adaptive-detail sampler.
 *
 * Runs in `prebuild` alongside the lazy-export, adaptive-detail and chart-layout guards.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { AXIAL_TILT_DEG, MAX_FRAME_MS, SPIN_DEG_PER_SEC, SPIN_DEG_PER_SEC_LOW_END, spinHolds, spinRate, spinStep } from "../src/autoRotate.js";

const here = dirname(fileURLToPath(import.meta.url));
const failures = [];
const check = (label, actual, expected) => {
  const pass = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${pass ? "ok  " : "FAIL"}  ${label}${pass ? "" : ` — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`}`);
  if (!pass) failures.push(label);
};

/** MapLibre's own wrap (`wrap(bearing, -180, 180)`), applied to every bearing it is handed. */
const wrap = n => n - Math.floor((n + 180) / 360) * 360;
/** The rotation actually applied between two wrapped readings: the shortest path. */
const applied = (from, to) => {
  const d = (to - from) % 360;
  return d > 180 ? d - 360 : d < -180 ? d + 360 : d;
};

// 1. The rate is a real speed you can see, and a weak machine is slower — not stopped.
check("the drift turns a full circle in a minute", SPIN_DEG_PER_SEC, 6);
check("a low-end machine turns one in two", SPIN_DEG_PER_SEC_LOW_END, 3);
check("neither rate is a globe that looks frozen", Math.min(SPIN_DEG_PER_SEC, SPIN_DEG_PER_SEC_LOW_END) >= 2, true);
check("the weak-machine rate is the slower of the two", spinRate(true) < spinRate(false), true);

// 2. The angle depends on elapsed time, not on how often the frames arrive: a second of drift is
//    a second of drift at 60 fps, 30 fps and 10 fps, which is what a fixed step per tick cannot
//    manage. (The whole-second frame below is clamped on purpose — see 3.)
const travelled = (cadenceMs, rate) => {
  let degrees = 0, t = 0;
  while (t + cadenceMs <= 1000) { t += cadenceMs; degrees += spinStep(cadenceMs, rate); }
  return degrees;
};
const round = n => Math.round(n * 1000) / 1000;
check("a second of drift is 6° at 100 fps", round(travelled(10, SPIN_DEG_PER_SEC)), 6);
check("…the same at 50 fps", round(travelled(20, SPIN_DEG_PER_SEC)), 6);
check("…the same at 20 fps", round(travelled(50, SPIN_DEG_PER_SEC)), 6);
check("…and the same at 10 fps", round(travelled(100, SPIN_DEG_PER_SEC)), 6);
check("a second of drift is 3° on a weak machine, whatever the frame rate", round(travelled(50, SPIN_DEG_PER_SEC_LOW_END)), 3);
// A real 60 fps cadence does not divide a second evenly; what matters is the speed it implies.
check("an awkward frame clock still implies the rate", round(travelled(16.7, SPIN_DEG_PER_SEC) / (59 * 16.7 / 1000)), 6);

// 3. A frame that took far too long — a hidden tab, a long GC — must not teleport the globe.
//    Any frame rate at or above 4 fps still runs at the full rate; below that it slows down.
check("a five-second frame advances one clamped slice, not thirty degrees", round(spinStep(5000, SPIN_DEG_PER_SEC)), 1.5);
check("…which keeps the full rate down to 4 fps", round(travelled(250, SPIN_DEG_PER_SEC)), 6);
check("a negative frame time cannot rewind the globe", spinStep(-50, SPIN_DEG_PER_SEC), 0);
check("the clamp is a quarter of a second", MAX_FRAME_MS, 250);

// 3. What the old timer did, for contrast: a fixed 0.12° per tick on a 140 ms interval was
//    0.86°/s, and the *machine* decided the speed — the same policy ran 3.7× faster when the
//    interval was 70 ms. That is the failure this policy replaces.
{
  const oldSpeed = cadenceMs => (Math.floor(1000 / cadenceMs) * 0.12 / (Math.floor(1000 / cadenceMs) * cadenceMs)) * 1000;
  check("the old step per tick was a crawl", round(oldSpeed(140)) < 1, true);
  check("…and its speed was set by the machine, not the clock", oldSpeed(70) / oldSpeed(140) > 1.9, true);
  check("the new rate does not depend on the machine", round(travelled(20, SPIN_DEG_PER_SEC)) === round(travelled(250, SPIN_DEG_PER_SEC)), true);
}

// 4. Forward only. The target is an unwrapped angle, and MapLibre wraps it into (-180, 180];
//    across that seam the applied rotation must stay a small forward step, never a full turn
//    backwards, at any starting bearing and with a jittery frame clock.
{
  let worst = { size: 0, backwards: null };
  for (const rate of [SPIN_DEG_PER_SEC, SPIN_DEG_PER_SEC_LOW_END]) {
    for (const start of [-179, -90, 0, 91, 179]) {
      let angle = start, from = wrap(start);
      for (let i = 0; i < 600; i++) {                          // ~3 revolutions of ~10 s
        angle += spinStep(8 + (i % 7), rate);                  // irregular 8–14 ms frames
        const to = wrap(angle);
        const step = Math.abs(applied(from, to));
        if (step > worst.size) worst.size = step;
        if (applied(from, to) <= 0) worst.backwards = { start, rate, i, from, to };
        from = to;
      }
    }
  }
  check("the globe never turns backwards at the seam", worst.backwards, null);
  check("and no frame jumps more than a fraction of a degree", worst.size < 0.2, true);
}

// 5. The hold rule: the drift yields whenever a gesture or one of the console's own camera
//    moves owns the map, and steps only when nothing else is moving it.
check("an idle map is stepped", spinHolds(false), false);
check("a gesture, or an animated camera move, is not fought", spinHolds(true), true);

// 6. The axis. A bearing set with the camera level turns the globe about a vertical line — a
//    spinning top — so the drift pitches the camera to Earth's own obliquity for as long as it
//    runs, and levels it again when it stops. Pinned as a range rather than a number: the point
//    is that it is Earth's axial tilt and not someone's idea of a jaunty angle.
check("the drift turns the globe on its real axis", AXIAL_TILT_DEG >= 22 && AXIAL_TILT_DEG <= 25, true);
check("…which is the planet's 23.4° of obliquity", Math.abs(AXIAL_TILT_DEG - 23.44) < 0.01, true);
check("and it is not so steep that it reads as a camera move", AXIAL_TILT_DEG < 30, true);

// 7. Wiring. The drift has to run on animation frames — a timer cannot be a speed — and it has
//    to mark its own rotation so the frame-rate sampler does not treat it as a gesture.
{
  const src = readFileSync(join(here, "..", "src", "MissionMap.jsx"), "utf8");
  check("the drift is driven by animation frames", /requestAnimationFrame/.test(src), true);
  check("it is not a timer", /setInterval/.test(src), false);
  check("it accumulates the angle from frame times", /angle \+= spinStep\(elapsed, rate\)/.test(src), true);
  check("and takes that frame time from the frame clock", /const elapsed = now - last/.test(src), true);
  check("it holds while another move owns the camera", /spinHolds\(map\.isMoving\(\)\)/.test(src), true);
  // Map.isEasing() exists on MapLibre's internal Camera, not on the public Map: calling it
  // throws inside the frame callback and the globe simply stops turning.
  check("it does not call an API the public Map does not have", /isEasing/.test(src), false);
  check("its own rotation does not arm the sampler", /if \(spinningRef\.current\) return;/.test(src), true);
  check("the tilt is applied to the camera, not to the data", /easeTo\(\{ pitch: AXIAL_TILT_DEG/.test(src), true);
  check("and the camera is levelled again when the drift stops", /getPitch\(\) - AXIAL_TILT_DEG/.test(src), true);
}

console.log(failures.length ? `\n${failures.length} FAILED` : "\norbital drift: all checks passed");
process.exit(failures.length ? 1 : 0);
