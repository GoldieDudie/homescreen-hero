/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  future: {
    hoverOnlyWhenSupported: true,
  },
  theme: {
    extend: {
      colors: {
        primary: "#195de6",
        "background-light": "#f6f6f8",
        "background-dark": "#111621",
        "card-dark": "#1a1f2e",
        "card-hover": "#222838",
        // User dashboard palette
        "user-bg": "#080d1a",
        "user-card": "#0f1528",
        "user-card-border": "#1a2540",
        "user-accent": "#e5a00d",
        "user-accent-dim": "#b8860b",
        "user-muted": "#8899b0",
      },
      fontFamily: {
        display: ["Inter", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        lg: "0.5rem",
        xl: "0.75rem",
        full: "9999px",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "progress-fill": {
          from: { width: "0%" },
          to: { width: "100%" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "progress-fill": "progress-fill 8s linear forwards",
        "fade-in": "fade-in 0.5s ease-out",
        blink: "blink 1s step-end infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
