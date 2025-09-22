/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        gold: "#FFD700",
        goldHover: "#e6c200",
        dark: "#0F0F0F",
        brand: {
          black: "#0f0f0f",
          gold: "#FFD700",
          goldHover: "#e6c200",
        },
      },
    },
  },
  plugins: [],
};
