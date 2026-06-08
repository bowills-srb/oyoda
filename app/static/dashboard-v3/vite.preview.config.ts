import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// A self-contained, single-file build used only for sharing a portable
// preview: JS, CSS, and fonts are inlined into one index.html that opens
// straight from the filesystem with no server and no sibling assets.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  base: "./",
  build: {
    outDir: "preview",
    emptyOutDir: true,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
  },
});
