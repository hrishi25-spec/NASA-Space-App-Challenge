/* ------------------------------------------------------------ orbital-drift policy
   Auto-rotate used to advance a *fixed angle* on a timer: 0.12° every 140 ms on a weak
   machine, which is 0.86°/s — a full turn every seven minutes, indistinguishable from a globe
   that is not moving at all — and 0.22° every 70 ms (3.1°/s) elsewhere. The motion also arrived
   in 7–14 discrete jumps a second, so it read as juddering, and how fast the globe turned was a
   property of the machine's timer rather than of time.

   The angle is now accumulated from the elapsed time at a real rate, one animation frame at a
   time, so the drift is the same speed whether the frame rate is 60 fps or 30. Kept pure
   (numbers in, number out) so scripts/check-spin-policy.mjs can assert it without a browser.
*/

/** Earth's axial tilt, in degrees: the angle between the planet's rotation axis and the plane
    of its orbit, 23.44° (NASA's own figure; the obliquity varies by ±0.0025° over 40,000 years,
    which is not a thing a screen shows).

    Auto-rotate turns the globe with `setBearing`, and a bearing set with the camera level turns
    the planet about a *vertical* axis -- which is what a spinning top does, not what Earth does.
    The camera is pitched to this angle for as long as the drift runs, so the axis the globe
    turns about is the real one and the north pole traces the same small circle it does from
    orbit. Pinned by check-spin-policy.mjs against the range Earth's tilt actually occupies. */
export const AXIAL_TILT_DEG = 23.44;

/** Degrees per second: a full revolution every 60 s, or every 120 s where frames are costly.
    Fast enough that the globe obviously turns, slow enough to read a coastline while it does. */
export const SPIN_DEG_PER_SEC = 6;
export const SPIN_DEG_PER_SEC_LOW_END = 3;

export const spinRate = lowEnd => (lowEnd ? SPIN_DEG_PER_SEC_LOW_END : SPIN_DEG_PER_SEC);

/**
 * The longest slice of time one frame may be paid for. A frame is normally 16 ms, but a hidden
 * tab, a long GC or a sleeping machine can report seconds — and at 6°/s an unclamped gap would
 * teleport the globe, which is exactly the jump a viewer notices. Any frame rate at or above
 * 4 fps still runs at the full rate; slower than that the drift slows down instead of jumping.
 */
export const MAX_FRAME_MS = 250;

/** How far to advance the bearing for a frame that took `elapsedMs`. */
export const spinStep = (elapsedMs, rate, maxMs = MAX_FRAME_MS) =>
  (Math.min(Math.max(elapsedMs, 0), maxMs) / 1000) * rate;

/**
 * True while something else owns the camera: a pointer gesture, or one of the console's own
 * animated moves (Fly to AOI, Globe view, Reset orbit, a dataset fly-to).
 *
 * `map.isMoving()` covers both — it is the camera's own ease flag or a live handler — and it
 * stays false for the drift's own bearing sets, which go through `jumpTo` (a jump, not an
 * ease). That last part is what makes it safe to ask: `jumpTo` calls `stop()` first, so
 * stepping the drift during someone else's animation would cancel it a frame after it started
 * and leave those controls apparently dead while Auto-rotate was on.
 *
 * (`Map.isEasing()` looks like the sharper test and is not one: it exists on MapLibre's
 * internal Camera, not on the public Map, so calling it throws inside the frame callback and
 * kills the drift. scripts/check-spin-policy.mjs pins that.)
 */
export const spinHolds = moving => Boolean(moving);
