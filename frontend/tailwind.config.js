/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: { DEFAULT: "#f6f3ec", raised: "#fbfaf6", sunk: "#efebe1" },
        ink: { DEFAULT: "#16202e", soft: "#3b4656", mute: "#6b7482", faint: "#a3a9b2" },
        rule: { DEFAULT: "#dcd6c8", strong: "#c4bcaa" },
        // Colour is reserved for verdicts.
        pass: { DEFAULT: "#1f7a4d", bg: "#e7f2ea", line: "#9ccbb0" },
        warn: { DEFAULT: "#9a6200", bg: "#fbf0d9", line: "#e3c27e" },
        block: { DEFAULT: "#b3261e", bg: "#fbe9e7", line: "#e8a39d" },
      },
      fontFamily: {
        display: ['"Fraunces"', '"Songti SC"', '"STSong"', "serif"],
        sans: ['"IBM Plex Sans"', '"PingFang SC"', '"Microsoft YaHei"', '"Noto Sans SC"', "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: { card: "0 1px 0 rgba(22,32,46,0.04), 0 8px 24px -16px rgba(22,32,46,0.25)" },
    },
  },
  plugins: [],
};
