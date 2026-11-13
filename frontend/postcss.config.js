// Preserve the actual CRA Tailwind pipeline. CRA ignored this external config
// and supplied flexbug fixes plus stage-3 transforms from webpack internally.
module.exports = {
  plugins: {
    tailwindcss: {},
    "postcss-flexbugs-fixes": {},
    "postcss-preset-env": { autoprefixer: { flexbox: "no-2009" }, stage: 3 },
  }
}
