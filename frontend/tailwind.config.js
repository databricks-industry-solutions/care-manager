/** @type {import('tailwindcss').Config} */
// Palette is driven by CSS variables (see index.css) so the whole clinical theme
// flips between light and dark by toggling the `dark` class on <html>. The
// `rgb(var(--x) / <alpha-value>)` form keeps Tailwind opacity utilities working
// (e.g. bg-clinical-accent/10).
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        clinical: {
          bg: "rgb(var(--c-bg) / <alpha-value>)",
          card: "rgb(var(--c-card) / <alpha-value>)",
          ink: "rgb(var(--c-ink) / <alpha-value>)",
          muted: "rgb(var(--c-muted) / <alpha-value>)",
          line: "rgb(var(--c-line) / <alpha-value>)",
          accent: "rgb(var(--c-accent) / <alpha-value>)",
        },
        risk: {
          high: "rgb(var(--c-risk-high) / <alpha-value>)",
          highbg: "rgb(var(--c-risk-highbg) / <alpha-value>)",
          rising: "rgb(var(--c-risk-rising) / <alpha-value>)",
          risingbg: "rgb(var(--c-risk-risingbg) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["DM Sans", "Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
