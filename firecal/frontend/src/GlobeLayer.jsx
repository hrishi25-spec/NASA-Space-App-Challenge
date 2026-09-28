import { useEffect, useRef } from "react";
import createGlobe from "cobe";
import { fmt } from "./lib";

/**
 * Interactive 3D globe (cobe/WebGL) for the "zoomed out" mission view.
 *
 * NOTE: cobe 2.x has NO internal animation loop and NO `onRender` callback
 * (its README is stale) — it only exposes { update(partial), destroy() }.
 * So we drive it from our own requestAnimationFrame loop here.
 *
 * - drag to rotate (with inertia), auto-rotates when idle
 * - wheel zooms; zooming IN past a threshold hands control back to the 2D map
 * - markers: live-feed hotspots if pulled, else day-cluster centroids, else AOI center
 */
const DPR = Math.min(2, typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1);

function globeOptions(width, height, view, markers) {
  return {
    devicePixelRatio: DPR,
    width,
    height,
    phi: view.current.phi,
    theta: view.current.theta,
    dark: 1,
    diffuse: 1.7,
    mapSamples: 30000,
    mapBrightness: 6,
    baseColor: [0.85, 0.66, 0.4],   // warm land dots on a near-black ocean (night-earth look)
    markerColor: [1, 0.45, 0.12],   // fire hotspots
    glowColor: [0.1, 0.25, 0.55],   // cool atmosphere rim
    opacity: 1,
    scale: view.current.scale,
    markers,
  };
}

export default function GlobeLayer({ markers = [], center = [0, 0], onZoomIn }) {
  const canvasRef = useRef(null);
  const globeRef = useRef(null);
  const currentMarkers = useRef([]);
  const pointer = useRef({ down: false, lastX: 0, lastY: 0, moved: false });
  const vel = useRef({ phi: 0, theta: 0 });
  const view = useRef({ phi: Math.PI * 1.5 - (center[1] * Math.PI) / 180, theta: (center[0] * Math.PI) / 180, scale: 0.95 });
  const idle = useRef(0);
  const zoomInRef = useRef(onZoomIn);
  zoomInRef.current = onZoomIn;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let raf = 0;
    let alive = true;
    let lastW = 0, lastH = 0;

    const ensure = () => {
      if (globeRef.current) return true;
      const w = canvas.offsetWidth, h = canvas.offsetHeight;
      if (!w || !h) return false;                 // wait for layout
      lastW = w * 2; lastH = h * 2;
      globeRef.current = createGlobe(canvas, globeOptions(lastW, lastH, view, currentMarkers.current));
      return true;
    };

    const tick = () => {
      if (!alive) return;
      const g = ensure() ? globeRef.current : null;
      if (g) {
        // follow element size (layout can change without a window resize event)
        const w = canvas.offsetWidth * 2, h = canvas.offsetHeight * 2;
        if (w > 0 && h > 0 && (w !== lastW || h !== lastH)) {
          lastW = w; lastH = h;
          g.update({ width: w, height: h });
        }
        // inertia + idle auto-rotate
        const v = view.current;
        if (!pointer.current.down) {
          v.phi += vel.current.phi;
          vel.current.phi *= 0.94; vel.current.theta *= 0.94;
          idle.current += 1;
          if (idle.current > 90) {
            v.phi += 0.0016;
            v.theta += (0 - v.theta) * 0.005;      // ease back to equator view
          }
        } else idle.current = 0;
        v.theta = Math.max(-1.1, Math.min(1.1, v.theta));
        g.update({ phi: v.phi, theta: v.theta, scale: v.scale });
      }
      raf = requestAnimationFrame(tick);
    };

    const onDown = e => { pointer.current = { down: true, lastX: e.clientX, lastY: e.clientY, moved: false }; e.preventDefault(); };
    const onMove = e => {
      const p = pointer.current;
      if (!p.down) return;
      const dx = e.clientX - p.lastX, dy = e.clientY - p.lastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) p.moved = true;
      view.current.phi += dx * 0.005;
      view.current.theta += dy * 0.003;
      vel.current.phi = dx * 0.0012; vel.current.theta = dy * 0.0008;
      p.lastX = e.clientX; p.lastY = e.clientY;
      idle.current = 0;
    };
    const onUp = () => { pointer.current.down = false; };
    const onWheel = e => {
      e.preventDefault();
      const v = view.current;
      v.scale = Math.max(0.62, Math.min(1.65, v.scale * (e.deltaY > 0 ? 0.93 : 1.07)));
      idle.current = 0;
      if (e.deltaY < 0 && v.scale > 1.45) {
        if (zoomInRef.current) zoomInRef.current();   // hand back to the flat map
        v.scale = 0.95;
      }
    };

    canvas.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    raf = requestAnimationFrame(tick);

    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      canvas.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("wheel", onWheel);
      if (globeRef.current) { globeRef.current.destroy(); globeRef.current = null; }
    };
  }, []);

  // rebuild the marker set when it changes (no need to re-create the globe)
  useEffect(() => {
    currentMarkers.current = markers.slice(0, 200).map(m => ({
      location: [m.lat, m.lon],
      size: Math.min(0.04, 0.008 + (m.frp || 10) / 60000),
    }));
    if (globeRef.current) globeRef.current.update({ markers: currentMarkers.current });
  }, [markers]);

  return (
    <div className="globeStage">
      <canvas ref={canvasRef} className="globeCanvas" />
      <div className="chip tl">
        <span className="dot" style={{ background: "var(--acc)" }} />FIRE HOTSPOTS
        <span className="hint">drag to rotate · scroll in = flat map</span>
      </div>
      <div className="chip br">
        <b>{fmt(markers.length)}</b> hotspots · <b>{fmt(markers.reduce((s, m) => s + (m.frp || 0), 0))}</b> MW FRP
      </div>
      <div className="scan" />
    </div>
  );
}
