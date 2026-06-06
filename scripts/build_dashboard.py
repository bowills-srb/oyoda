#!/usr/bin/env python3
"""
build_dashboard.py

Compiles oyvoda-v10.jsx → Python module containing the full dashboard HTML.
Run this whenever the dashboard JSX changes.

Usage:
    python3 scripts/build_dashboard.py

Output:
    app/api/v1/endpoints/_dashboard_bundle.py
    (imported by operator_dashboard.py — no file I/O at request time)

Requirements:
    node, npm (for @babel/core compilation)
    OR set SKIP_BABEL=1 to use pre-compiled JS from app/static/dashboard/
"""

import os
import sys
import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
JSX_SOURCE = ROOT / "frontend" / "dashboard" / "oyvoda-v10.jsx"
STATIC_JS = ROOT / "app" / "static" / "dashboard" / "oyvoda-dashboard.js"
OUTPUT_MODULE = ROOT / "app" / "api" / "v1" / "endpoints" / "_dashboard_bundle.py"

BABEL_CONFIG = {
    "presets": [
        ["@babel/preset-react", {"runtime": "classic"}],
        ["@babel/preset-env", {"targets": "last 2 Chrome versions", "modules": False}]
    ]
}

AUTO_MOUNT = """
// Auto-mount Oyvoda dashboard to #root
(function() {
  var rootEl = document.getElementById('root');
  if (!rootEl || typeof ReactDOM === 'undefined') return;
  try {
    var root = ReactDOM.createRoot(rootEl);
    root.render(React.createElement(App));
    var loader = document.getElementById('loading');
    if (loader) loader.style.display = 'none';
  } catch(e) {
    var loader = document.getElementById('loading');
    if (loader) loader.innerHTML =
      '<div style="color:#ef4444;font-family:monospace;padding:40px;font-size:13px">' +
      'Dashboard error: ' + e.message + '</div>';
    console.error('Oyvoda mount error:', e);
  }
})();
"""

HTML_SHELL = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Oyvoda — Operator Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body, #root {{ height: 100%; background: #08090f; color: #f4f6fa; font-family: 'DM Sans', sans-serif; }}
  #loading {{ display: flex; flex-direction: column; align-items: center; justify-content: center;
    height: 100vh; gap: 18px; background: #08090f; color: #5a7090; }}
  .logo {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 38px; font-weight: 500;
    color: #f0ebe3; letter-spacing: -0.02em; }}
  .dots {{ display: flex; gap: 6px; }}
  .dot {{ width: 7px; height: 7px; border-radius: 50%; background: #c87832;
    animation: pulse 1.4s ease-in-out infinite; }}
  .dot:nth-child(2) {{ animation-delay: .2s; }}
  .dot:nth-child(3) {{ animation-delay: .4s; }}
  .loading-label {{ font-size: 11px; letter-spacing: .08em; text-transform: uppercase; opacity: .5; }}
  @keyframes pulse {{ 0%,60%,100%{{opacity:.25}} 30%{{opacity:1}} }}
</style>
</head>
<body>
<div id="loading">
  <div class="logo">oyvoda</div>
  <div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
  <div class="loading-label">Loading dashboard</div>
</div>
<div id="root"></div>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/prop-types/15.8.1/prop-types.min.js"></script>
<script>
  window.React = React;
  window.ReactDOM = ReactDOM;
  window.PropTypes = PropTypes;
</script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/recharts/2.5.0/Recharts.min.js"></script>
<script>
  var _r = Recharts;
  var LineChart=_r.LineChart,Line=_r.Line,BarChart=_r.BarChart,Bar=_r.Bar,
      XAxis=_r.XAxis,YAxis=_r.YAxis,CartesianGrid=_r.CartesianGrid,
      Tooltip=_r.Tooltip,Legend=_r.Legend,ResponsiveContainer=_r.ResponsiveContainer,
      PieChart=_r.PieChart,Pie=_r.Pie,Cell=_r.Cell,AreaChart=_r.AreaChart,
      Area=_r.Area,RadarChart=_r.RadarChart,Radar=_r.Radar,PolarGrid=_r.PolarGrid,
      PolarAngleAxis=_r.PolarAngleAxis,ComposedChart=_r.ComposedChart;
</script>
<script>
{js_content}
</script>
</body>
</html>\
"""


def compile_jsx(jsx_path: Path) -> str:
    """Compile JSX to vanilla JS using Babel."""
    print(f"Compiling {jsx_path.name}...")

    # Set up Babel in a temp dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # Write babel config
        (tmp / "babel.config.json").write_text(json.dumps(BABEL_CONFIG))

        # Install babel if needed
        pkg_json = {"dependencies": {
            "@babel/core": "^7.23.0",
            "@babel/cli": "^7.23.0",
            "@babel/preset-react": "^7.23.0",
            "@babel/preset-env": "^7.23.0"
        }}
        (tmp / "package.json").write_text(json.dumps(pkg_json))

        print("  Installing Babel (first run only)...")
        result = subprocess.run(
            ["npm", "install", "--silent"],
            cwd=tmp, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"npm install failed: {result.stderr}")

        out_file = tmp / "output.js"
        result = subprocess.run(
            [str(tmp / "node_modules" / ".bin" / "babel"),
             str(jsx_path),
             "--config-file", str(tmp / "babel.config.json"),
             "--out-file", str(out_file)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Babel compilation failed:\n{result.stderr}")

        js = out_file.read_text()
        print(f"  Compiled: {len(js):,} bytes")
        return js


def process_js(js: str) -> str:
    """Strip ESM exports, add auto-mount block."""
    js = js.replace('export default function App()', 'function App()')
    js = js.replace('export function ', 'function ')
    js = js.replace('export const ', 'const ')
    js += AUTO_MOUNT
    return js


def write_static_js(js: str, output: Path) -> None:
    """Write compiled JS to app/static/dashboard/oyvoda-dashboard.js.
    The HTML shell (app/static/dashboard/shell.html) loads it via <script src>.
    No Python string escaping. No baking JS into Python files.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(js, encoding="utf-8")
    print(f"  Written: {output} ({len(js):,} bytes)")
    print(f"  Served at: /static/dashboard/oyvoda-dashboard.js")


def main():
    skip_babel = os.getenv("SKIP_BABEL") == "1"

    if skip_babel and STATIC_JS.exists():
        print(f"SKIP_BABEL=1 — skipping recompile, {STATIC_JS} unchanged")
        print("\n✅ Nothing to do.")
        return
    elif JSX_SOURCE.exists():
        js = compile_jsx(JSX_SOURCE)
    elif STATIC_JS.exists():
        print(f"JSX source not found, {STATIC_JS} already exists — nothing to do")
        return
    else:
        print("ERROR: No JSX source found.")
        print(f"  Expected: {JSX_SOURCE}")
        sys.exit(1)

    js = process_js(js)
    write_static_js(js, STATIC_JS)

    print(f"\n✅ Dashboard JS compiled successfully")
    print(f"   Deploy to pick up changes (Railway redeploys on git push)")
    print(f"   The HTML shell at app/static/dashboard/shell.html loads it automatically.")


if __name__ == "__main__":
    main()
