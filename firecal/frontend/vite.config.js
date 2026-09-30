import { defineConfig } from "vite"; import react from "@vitejs/plugin-react";
// Bind the IPv4 loopback explicitly. On Node 17+ `localhost` can resolve to ::1 first,
// which would leave the dev server reachable on one stack only and the /api proxy
// pointing at an address uvicorn (bound to 127.0.0.1) never listens on.
export default defineConfig({
  plugins: [react()],
  build: {
    // NOTE: no lower `target` here. MapLibre's worker uses BigInt literals and the map
    // itself needs WebGL2, so anything old enough to miss ES2020 syntax can't run the
    // map at all -- downleveling would only slow the build and grow the bundle.
    // Split the one big library (MapLibre) into its own chunk: it then downloads in parallel
    // with the app code, caches independently, and is only fetched when the map opens.
    // Charts are hand-rolled SVG now (src/plot.jsx), so there is no charting vendor chunk.
    rollupOptions: {
      output: {
        // Group by module path, not by package entry: the object form only captures the
        // package's entry file, which left React's real code inside the lazy charts
        // chunk -- and that pulled Recharts back into the first paint.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("maplibre-gl")) return "vendor-maplibre";
          if (/[\\/]node_modules[\\/](react|react-dom|react-is|scheduler)[\\/]/.test(id)) return "vendor-react";
          return undefined;
        },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", rewrite: p => p.replace(/^\/api/, "") } },
  },
  preview: { host: "127.0.0.1", port: 4173 },
});
