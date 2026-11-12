#!/usr/bin/env node
// Read-only post-deploy check. Browser hydration can conceal a missing Render
// rewrite by correcting the title after the server has sent the homepage HTML.
const assert = require("node:assert/strict");
const meta = require("../frontend/src/routeMeta.json");
const { PUBLIC_ROUTES, PRIVATE_ROUTES, SITE, escapeHtml } = require("../frontend/src/seo/routeHtml");

function attribute(tag, name) {
  return tag.match(new RegExp(`\\b${name}=(["'])(.*?)\\1`, "i"))?.[2];
}

function singleTag(html, name, key, value) {
  const tags = [...html.matchAll(new RegExp(`<${name}\\b[^>]*>`, "gi"))]
    .map(([tag]) => tag).filter((tag) => attribute(tag, key) === value);
  assert.equal(tags.length, 1, `expected one ${name}[${key}=${value}], found ${tags.length}`);
  return tags[0];
}

async function main() {
  const base = new URL(process.argv[2] || SITE);
  assert.ok(["http:", "https:"].includes(base.protocol), "base URL must use HTTP or HTTPS");
  assert.ok(!base.username && !base.password && !base.search && !base.hash && base.pathname === "/", "use a base origin without credentials, path, query or fragment");
  const paths = ["/", ...PUBLIC_ROUTES, ...PRIVATE_ROUTES];
  let passed = 0;
  const failures = [];
  // Sequential requests keep this small verification from creating a traffic burst.
  for (const path of paths) {
    for (const requestPath of path === "/" ? [path] : [path, `${path}/`]) {
      try {
        const response = await fetch(new URL(requestPath, base), { signal: AbortSignal.timeout(20_000) });
        assert.equal(response.status, 200, `HTTP ${response.status}`);
        assert.match(response.headers.get("content-type") || "", /text\/html/i);
        const html = await response.text();
        const titles = [...html.matchAll(/<title>([^<]*)<\/title>/gi)];
        assert.equal(titles.length, 1, "expected one title");
        assert.equal(titles[0][1], escapeHtml(meta[path].title), "initial title differs from route metadata");
        const indexable = !PRIVATE_ROUTES.includes(path);
        const canonical = indexable ? `${SITE}${path}` : `${SITE}/`;
        assert.equal(attribute(singleTag(html, "link", "rel", "canonical"), "href"), canonical, "initial canonical differs");
        assert.equal(attribute(singleTag(html, "meta", "name", "description"), "content"), escapeHtml(meta[path].description), "initial description differs");
        assert.equal(attribute(singleTag(html, "meta", "name", "robots"), "content"), indexable ? "index,follow,max-image-preview:large" : "noindex,nofollow", "indexing directive differs");
        assert.equal(attribute(singleTag(html, "meta", "property", "og:url"), "content"), canonical, "social canonical differs");
        console.log(`PASS ${requestPath}`);
        passed++;
      } catch (error) {
        failures.push({ path: requestPath, reason: error.message });
        console.error(`FAIL ${requestPath}: ${error.message}`);
      }
    }
  }
  console.log(JSON.stringify({ base: base.origin, checkedAtUtc: new Date().toISOString(), passed, failed: failures.length, failures }));
  if (failures.length) process.exitCode = 1;
}

main().catch((error) => { console.error(error.message); process.exitCode = 1; });
