#!/usr/bin/env node
/**
 * build-dashboard.js
 * 
 * Compiles oyvoda-v10.jsx → app/static/dashboard/oyvoda-dashboard.js
 * Run once after cloning, and whenever the dashboard JSX changes.
 * 
 * Usage:
 *   node scripts/build-dashboard.js
 * 
 * Requires: node (already installed for the project)
 * Installs: @babel/core, @babel/cli, @babel/preset-react, @babel/preset-env
 *           (into node_modules, not global)
 */

const { execSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
// JSX source — lives at frontend/dashboard/oyvoda-v10.jsx
// Also tracked in mnt/user-data/outputs/oyvoda-v10.jsx (Claude artifact)
const JSX_SRC = path.join(ROOT, 'frontend', 'dashboard', 'oyvoda-v10.jsx');
const OUT_DIR = path.join(ROOT, 'app', 'static', 'dashboard');
const OUT_FILE = path.join(OUT_DIR, 'oyvoda-dashboard.js');
const PKG_FILE = path.join(ROOT, 'package.json');

const AUTO_MOUNT = `
// ── Auto-mount Oyvoda dashboard to #root ────────────────────────────────────
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
`;

console.log('🏗  Oyvoda Dashboard Build');
console.log('   Source:', JSX_SRC);
console.log('   Output:', OUT_FILE);

// 1. Check source exists
if (!fs.existsSync(JSX_SRC)) {
  console.error('❌ Source not found:', JSX_SRC);
  process.exit(1);
}

// 2. Ensure output dir
fs.mkdirSync(OUT_DIR, { recursive: true });

// 3. Ensure package.json has babel deps
let pkg = {};
if (fs.existsSync(PKG_FILE)) {
  pkg = JSON.parse(fs.readFileSync(PKG_FILE, 'utf8'));
}
const babelDeps = {
  '@babel/core': '^7.23.0',
  '@babel/cli': '^7.23.0',
  '@babel/preset-react': '^7.23.0',
  '@babel/preset-env': '^7.23.0',
};
pkg.devDependencies = { ...(pkg.devDependencies || {}), ...babelDeps };
if (!pkg.name) pkg.name = 'oyvoda';
if (!pkg.version) pkg.version = '0.1.0';
fs.writeFileSync(PKG_FILE, JSON.stringify(pkg, null, 2));

// 4. Write babel config
const babelConfig = {
  presets: [
    ['@babel/preset-react', { runtime: 'classic' }],
    ['@babel/preset-env', { targets: 'last 2 Chrome versions', modules: false }],
  ],
};
fs.writeFileSync(
  path.join(ROOT, 'babel.config.json'),
  JSON.stringify(babelConfig, null, 2)
);

// 5. Install babel deps if needed
const babelBin = path.join(ROOT, 'node_modules', '.bin', 'babel');
if (!fs.existsSync(babelBin)) {
  console.log('📦 Installing Babel (first run only)...');
  execSync('npm install --save-dev @babel/core @babel/cli @babel/preset-react @babel/preset-env', {
    cwd: ROOT,
    stdio: 'inherit',
  });
}

// 6. Compile JSX → JS
console.log('⚙️  Compiling JSX...');
const result = spawnSync(babelBin, [
  JSX_SRC,
  '--config-file', path.join(ROOT, 'babel.config.json'),
  '--out-file', OUT_FILE,
], { cwd: ROOT, encoding: 'utf8' });

if (result.status !== 0) {
  console.error('❌ Babel compilation failed:');
  console.error(result.stderr);
  process.exit(1);
}

// 7. Post-process: strip ESM imports, add auto-mount
let js = fs.readFileSync(OUT_FILE, 'utf8');
// Strip import lines (Babel converts syntax but may leave import declarations)
js = js.split('\n').filter(l => !l.trim().startsWith('import ')).join('\n');
// Strip export default
js = js.replace(/export default function App\(\)/, 'function App()');
js = js.replace(/export function /g, 'function ');
js = js.replace(/export const /g, 'const ');
// Add auto-mount
js = js + AUTO_MOUNT;

fs.writeFileSync(OUT_FILE, js);

const stats = fs.statSync(OUT_FILE);
console.log(`✅ Built: ${OUT_FILE}`);
console.log(`   Size: ${(stats.size / 1024).toFixed(1)} KB`);
console.log('');
console.log('Next: docker compose restart api');
