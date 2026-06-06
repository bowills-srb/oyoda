/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: [
    "./app/static/dashboard-v2/index.html",
    "./app/static/dashboard-v2/src/**/*.{js,ts,jsx,tsx}",
  ],
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        page: "var(--surface-page)",
        raised: "var(--surface-raised)",
        sunken: "var(--surface-sunken)",
        hover: "var(--surface-hover)",
        selected: "var(--surface-selected)",
        hairline: "var(--border-hairline)",
        border: "var(--border-default)",
        strong: "var(--border-strong)",
        focus: "var(--border-focus)",
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        tertiary: "var(--text-tertiary)",
        disabled: "var(--text-disabled)",
        accent: "var(--accent-600)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
        display: ["var(--font-display)"],
      },
      boxShadow: {
        shell: "0 18px 50px rgba(15, 20, 25, 0.08)",
      },
      // Phase 5.2 motion vocabulary — used by ListDetailSurface mobile sheet.
      // Define here (not in styles.css) so they're Tailwind utilities and
      // don't grow styles.css.
      keyframes: {
        "sheet-in": {
          from: { opacity: "0", transform: "translateY(16px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        "overlay-in": {
          from: { opacity: "0" },
          to:   { opacity: "1" },
        },
      },
      animation: {
        "sheet-in":   "sheet-in 180ms ease-out",
        "overlay-in": "overlay-in 160ms ease-out",
      },
    },
  },
  plugins: [],
};
