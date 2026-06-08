/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces — deep, calm, near-black with a touch of warmth.
        bg: "var(--bg)",
        panel: "var(--panel)",
        raised: "var(--raised)",
        hover: "var(--hover)",
        selected: "var(--selected)",
        // Lines
        hairline: "var(--hairline)",
        line: "var(--line)",
        // Text
        ink: "var(--ink)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        // The employee's voice — a single warm accent, used sparingly.
        accent: "var(--accent)",
        // Channel hues
        "ch-text": "var(--ch-text)",
        "ch-email": "var(--ch-email)",
        "ch-voice": "var(--ch-voice)",
        // Priority
        high: "var(--high)",
        med: "var(--med)",
        low: "var(--low)",
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
      },
      maxWidth: {
        prose: "62ch",
      },
      keyframes: {
        "drawer-in": {
          from: { opacity: "0", transform: "translateX(12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "drawer-in": "drawer-in 240ms cubic-bezier(0.22, 1, 0.36, 1)",
        "fade-up": "fade-up 200ms ease-out",
      },
    },
  },
  plugins: [],
};
