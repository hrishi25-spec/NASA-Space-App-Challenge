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
    // Split the two big libraries into their own chunks: they then download in parallel
    // with the app code, cache independently, and the lazy ones (MapLibre, Recharts) are
    // only fetched when that part of the UI actually opens.
    rollupOptions: {
      output: {
        // Group by module path, not by package entry: the object form only captures the
        // package's entry file, which left React's real code inside the lazy charts
        // chunk -- and that pulled Recharts back into the first paint.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("maplibre-gl")) return "vendor-maplibre";
          if (/[\\/]node_modules[\\/](recharts|recharts-scale|react-smooth|react-resize-detector|victory-vendor|d3-[a-z]+|internmap|decimal\.js|fast-equals|es-toolkit)/.test(id)) return "vendor-charts";
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
