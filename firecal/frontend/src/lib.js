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

export const errMsg = async r => { try { const j = await r.json(); return j.detail || r.statusText; } catch { return r.statusText; } };

// Burning-intensity ramp, level 0 -> 5. Level 0 is the material itself so an idle
// day recedes into the panel; the rest climb through warm browns into the ember
// amber and finish on a pale sand, which keeps the scale soothing but ordered.
export const ramp = ["#1d262a", "#5a3524", "#9a5327", "#cf7239", "#eda15f", "#ffdca8"];

export const doyLabel = d => new Date(2001, 0, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export const fmt = n => n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n * 10) / 10);
