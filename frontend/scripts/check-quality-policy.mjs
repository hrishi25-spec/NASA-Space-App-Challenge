// The adaptive-detail policy decides by itself when a moving map should drop its render ratio
// and its detection points, which makes it exactly the kind of code that breaks silently. This
// exercises it against simulated frame times — no browser, no network, no timing flakiness,
// because the policy only ever reads the timestamps it is handed.
//
// Runs as part of `prebuild` alongside the lazy-export guard.
import { createQualityGovernor } from "../src/adaptiveQuality.js";

const failures = [];
const check = (label, actual, expected) => {
  const pass = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${pass ? "ok  " : "FAIL"}  ${label}${pass ? "" : ` — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`}`);
  if (!pass) failures.push(label);
};

const FAST = 16.7;                                    // ≈60 fps
const SLOW = 50;                                      // ≈20 fps
const times = (count, ms) => Array(count).fill(ms);

// A drag emits an event per frame; this replays that, then keeps sampling after the last event
// until the quiet window closes, exactly as the map's sampler loop does.
function drag(governor, frameTimes) {
  let t = 1000;
  let degradedAtFrame = null;
  frameTimes.forEach((dt, i) => {
    t += dt;
    governor.arm(t);                                  // a pointermove on this frame
    governor.sample(t);
    if (governor.degraded && degradedAtFrame === null) degradedAtFrame = i;
  });
  return { at: t, degradedAtFrame };
}

function settle(governor, from) {
  let t = from;
  while (t - from < 700) {
    t += FAST;
    governor.sample(t);
    if (governor.settled(t)) return t;
  }
  return null;
}

const recorder = () => {
  const changes = [];
  return { changes, governor: createQualityGovernor({ onChange: r => changes.push(r) }) };
};

// 1. A drag that keeps up is never touched, and the window still closes.
{
  const { changes, governor } = recorder();
  const { at } = drag(governor, times(120, FAST));
  const settled = settle(governor, at);
  governor.release();
  check("60 fps drag never degrades", changes, []);
  check("60 fps drag settles after the gesture", settled !== null, true);
}

// 2. A sustained slow drag degrades once, and only after it has lasted long enough to judge.
{
  const { changes, governor } = recorder();
  const { degradedAtFrame } = drag(governor, times(100, SLOW));
  check("20 fps drag degrades once", changes, [true]);
  check("degradation waits for enough frames", degradedAtFrame !== null && degradedAtFrame >= 12, true);
  check("degradation waits for sustained motion, not one slow frame", degradedAtFrame * SLOW >= 400, true);
}

// 3. A three-frame stutter inside an otherwise fast drag is not a frame rate.
{
  const { changes, governor } = recorder();
  const { at } = drag(governor, [...times(20, FAST), 90, 90, 90, ...times(40, FAST)]);
  const settled = settle(governor, at);
  governor.release();
  check("a 3-frame stutter never degrades", changes, []);
  check("the stutter drag still settles", settled !== null, true);
}

// 4. Detail comes back when the motion stops — exactly once, and never when nothing was lost.
{
  const { changes, governor } = recorder();
  const { at } = drag(governor, times(40, SLOW));
  const settled = settle(governor, at);
  governor.release();
  governor.release();                                 // a second release must not fire again
  check("a slow drag degrades then restores", changes, [true, false]);
  check("restore happens after the gesture ends", settled !== null, true);
  check("release leaves the governor idle", governor.degraded, false);
}

// 5. Frames outside a gesture are ignored — an idle map is never judged, however slow it paints.
{
  const { changes, governor } = recorder();
  let t = 1000;
  for (let i = 0; i < 40; i++) { t += 200; governor.sample(t); }
  check("frames outside a gesture are ignored", changes, []);
  check("an unarmed governor never settles", governor.settled(t), false);
}

// 6. Quality does not flap mid-gesture: once reduced, an improvement waits for the gesture to end.
{
  const { changes, governor } = recorder();
  const { at } = drag(governor, [...times(30, SLOW), ...times(40, FAST)]);
  check("recovery mid-gesture is deferred", changes, [true]);
  check("the gesture is still running", governor.settled(at), false);
  const settled = settle(governor, at);
  governor.release();
  check("... and applied once it ends", changes, [true, false]);
  check("the recovered gesture settles", settled !== null, true);
}

// 7. A stall (a hidden tab, a long GC) is not mistaken for a low frame rate.
{
  const { changes, governor } = recorder();
  drag(governor, [FAST, FAST, FAST, 1200, ...times(20, FAST)]);
  check("a 1.2 s stall does not degrade", changes, []);
}

// 8. The thresholds are the knobs they claim to be.
{
  const { changes, governor } = recorder();
  drag(governor, times(40, FAST));
  check("the default floor tolerates a 60 fps drag", changes, []);
}
{
  const changes = [];
  const governor = createQualityGovernor({ floorMs: 10, onChange: r => changes.push(r) });
  drag(governor, times(40, FAST));
  check("floorMs 10 degrades a 60 fps drag", changes, [true]);
}
{
  const changes = [];
  const governor = createQualityGovernor({ minMotionMs: 5000, onChange: r => changes.push(r) });
  drag(governor, times(60, SLOW));
  check("a longer motion floor withholds judgement", changes, []);
}
{
  const changes = [];
  const governor = createQualityGovernor({ settleMs: 100, onChange: r => changes.push(r) });
  let t = 1000;
  governor.arm(t);
  governor.sample(t + FAST);
  check("a shorter settle window closes sooner", governor.settled(t + 150), true);
  governor.release();
  check("... without inventing a change", changes, []);
}

console.log(failures.length ? `\n${failures.length} FAILED` : "\nadaptive-detail policy: all checks passed");
process.exit(failures.length ? 1 : 0);
