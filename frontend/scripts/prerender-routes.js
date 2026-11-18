#!/usr/bin/env node
// Runs after `vite build` (npm "postbuild"). Writes build/<route>/index.html
// for each public route with that route's own title, description, canonical URL and
// a short summary, and aligns the homepage's initial metadata with src/routeMeta.json.
// If the static host serves a directory's index.html, crawlers get the right
// metadata before JavaScript; if not, the host's SPA rewrite serves build/index.html
// exactly as before. Any missing tag fails the build instead of shipping wrong metadata.
const fs = require("fs");
const path = require("path");
const routeMeta = require("../src/routeMeta.json");
const { PUBLIC_ROUTES, PRIVATE_ROUTES, renderRouteHtml } = require("../src/seo/routeHtml");

const buildDir = path.resolve(__dirname, "..", "build");
const indexPath = path.join(buildDir, "index.html");
const homepage = fs.readFileSync(indexPath, "utf8");

const written = [];
for (const route of [...PUBLIC_ROUTES, ...PRIVATE_ROUTES]) {
  const html = renderRouteHtml(homepage, route, routeMeta[route], { indexable: PUBLIC_ROUTES.includes(route) });
  const dir = path.join(buildDir, route.slice(1));
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "index.html"), html);
  written.push(route);
}
fs.writeFileSync(indexPath, renderRouteHtml(homepage, "/", routeMeta["/"], { indexable: true }));
console.log(`prerender-routes: wrote initial HTML for /, ${written.join(", ")}`);
