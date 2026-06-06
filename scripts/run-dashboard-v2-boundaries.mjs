import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { build } from "esbuild";

const repoRoot = process.cwd();
const entryPoint = path.join(
  repoRoot,
  "app/static/dashboard-v2/src/routes/Today/lifecycleBoundaries.test.ts",
);

const tempDir = mkdtempSync(path.join(os.tmpdir(), "oyvoda-dashboard-v2-boundaries-"));
const outfile = path.join(tempDir, "lifecycleBoundaries.test.mjs");

try {
  await build({
    entryPoints: [entryPoint],
    outfile,
    bundle: true,
    platform: "node",
    format: "esm",
    sourcemap: "inline",
    target: "node25",
    logLevel: "silent",
  });

  const result = spawnSync(process.execPath, ["--test", outfile], {
    stdio: "inherit",
  });

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
