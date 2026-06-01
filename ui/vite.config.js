import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite builds the React UI once into the Python package's ui/web/ tree;
// the pywebview shell (src/emc_assistant/ui/app.py) then loads that
// static bundle. No CDN / network at runtime — the bundle is self-contained.
export default defineConfig({
  root: ".",
  // Relative asset paths so the built index.html works under `file://`
  // (pywebview loads the bundle from disk; an absolute `/assets/…` path
  // would resolve to the filesystem root instead of the bundle directory).
  base: "./",
  plugins: [react()],
  esbuild: {
    // Allow .js files to contain JSX (the prototype source uses .jsx, but
    // be permissive — every file in the prototype is JSX-friendly).
    loader: "jsx",
    include: /src\/.*\.jsx?$/,
    exclude: [],
  },
  build: {
    outDir: "../src/emc_assistant/ui/web",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },
  server: {
    strictPort: false,
  },
});
