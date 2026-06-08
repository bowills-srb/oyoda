import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `base: "./"` keeps the built asset URLs relative so the bundle can be
// mounted at any path later (e.g. /static/dashboard-v3/dist/) without a rebuild.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173 },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
