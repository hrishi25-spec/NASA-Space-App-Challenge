export const api = (p, q = {}) => fetch("/api" + p + "?" + new URLSearchParams(Object.entries(q).filter(([, v]) => v != null)))
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });

export const errMsg = async r => { try { const j = await r.json(); return j.detail || r.statusText; } catch { return r.statusText; } };

export const ramp = ["#22262f", "#5a2a1a", "#a3401c", "#e0601f", "#ffa04a", "#fff0a0"];

export const doyLabel = d => new Date(2001, 0, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export const fmt = n => n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n * 10) / 10);
