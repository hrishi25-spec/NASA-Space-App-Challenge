// ------------------------------------------------------------------ API client
// One entry per distinct query, holding the in-flight promise (so concurrent
// identical requests collapse into one) and then the result. Revisiting a day, a
// span or an AOI is served from memory instead of re-hitting the API, which is what
// makes flipping around the map and the calendar feel instant on a slow machine.
const cache = new Map();
const CACHE_MAX = 200;

export function invalidateApiCache() { cache.clear(); }

export const api = (p, q = {}) => {
  const url = "/api" + p + "?" + new URLSearchParams(Object.entries(q).filter(([, v]) => v != null));
  const hit = cache.get(url);
  if (hit) return hit;
  const promise = fetch(url)
    .then(r => { if (!r.ok) throw new Error(r.status + " " + r.statusText); return r.json(); })
    .catch(e => { cache.delete(url); throw e; });   // a failure must never be cached
  cache.set(url, promise);
  if (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value);
  return promise;
};

// FastAPI's `detail` is a string for the errors this API raises deliberately, but a *list of
// objects* for a validation failure -- and `"…" + d` renders that as "[object Object]", which
// is exactly the case where the operator needs to read what was wrong with the request.
export const errMsg = async r => {
  try {
    const d = (await r.json())?.detail;
    if (typeof d === "string") return d;
    if (d != null) return JSON.stringify(d);
    return r.statusText;
  } catch { return r.statusText; }
};

// The only signal a browser gives us about the link itself (Network Information API; Firefox
// exposes none of it, which is why every read is optional). Both basemaps keep every feature,
// so this never changes what the console can do -- it only picks the basemap the console *opens*
// on. Raster tiles are a new download at every zoom step; vector tiles carry geometry that
// stays sharp when overzoomed, so the same pan costs a fraction of the bytes.
export const SLOW_LINK = (() => {
  if (typeof navigator === "undefined") return false;
  const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (!c) return false;
  if (c.saveData) return true;                                        // "reduce data usage" is a hard yes
  if (/^(slow-)?2g$|^3g$/.test(c.effectiveType || "")) return true;
  return typeof c.downlink === "number" && c.downlink > 0 && c.downlink < 1.5;   // Mbps
})();

// Burning-intensity ramp, level 0 -> 5. Level 0 is the material itself so an idle
// day recedes into the panel; the rest climb through warm browns into the ember
// amber and finish on a pale sand, which keeps the scale soothing but ordered.
export const ramp = ["#1d262a", "#5a3524", "#9a5327", "#cf7239", "#eda15f", "#ffdca8"];

export const doyLabel = d => new Date(2001, 0, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export const fmt = n => n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n * 10) / 10);
