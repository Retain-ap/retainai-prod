// CRA and Vite emit different bundle tags/HTML whitespace; compare every DOM
// node/attribute and JSON-LD payload after removing only generated /static tags.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { JSDOM } from "jsdom";

const [baselineDir, candidateDir = "build"] = process.argv.slice(2);
if (!baselineDir) throw new Error("Usage: node scripts/compare-prerender.mjs baseline-build [candidate-build]");

function htmlPaths(dir, prefix = "") {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const name = path.posix.join(prefix, entry.name);
    return entry.isDirectory() ? htmlPaths(path.join(dir, entry.name), name) : name.endsWith(".html") ? [name] : [];
  }).sort();
}
function content(dir, file, candidate) {
  const dom = new JSDOM(fs.readFileSync(path.join(dir, file), "utf8"));
  const doc = dom.window.document;
  for (const tag of doc.querySelectorAll('script[src^="/static/"],link[href^="/static/"]')) {
    if (candidate) {
      const asset = (tag.getAttribute("src") || tag.getAttribute("href")).split("?")[0];
      assert.ok(fs.existsSync(path.join(dir, asset.slice(1))), `${file} has a missing generated asset: ${asset}`);
    }
    tag.remove();
  }
  function nodeValue(node) {
    if (node.nodeType === 8) return null;
    if (node.nodeType === 3) return node.textContent.trim().replace(/\s+/g, " ") || null;
    if (node.nodeType !== 1) return null;
    if (node.tagName === "SCRIPT" && node.type === "application/ld+json") return ["JSON-LD", JSON.parse(node.textContent)];
    const attributes = [...node.attributes].map(attr => [attr.name,
      // CRA's HTML minifier removes whitespace after viewport commas; this is
      // the same viewport directive list, not a copy/layout/metadata change.
      node.tagName === "META" && node.name === "viewport" && attr.name === "content"
        ? attr.value.split(",").map(directive => directive.trim()).join(",") : attr.value,
    ]).sort();
    return [node.tagName, attributes, [...node.childNodes].map(nodeValue).filter(value => value !== null)];
  }
  const normalized = nodeValue(doc.documentElement);
  dom.window.close();
  return normalized;
}
const routes = htmlPaths(baselineDir);
assert.deepEqual(htmlPaths(candidateDir), routes, "The exact prerendered route set must remain the same");
for (const route of routes) assert.deepEqual(content(candidateDir, route, true), content(baselineDir, route, false), `Prerender DOM changed: ${route}`);
function publicFiles(dir, prefix = "") {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const name = path.posix.join(prefix, entry.name);
    if (name === "static" || name === "asset-manifest.json") return [];
    return entry.isDirectory() ? publicFiles(path.join(dir, entry.name), name) : name.endsWith(".html") ? [] : [name];
  }).sort();
}
const assets = publicFiles(baselineDir);
assert.deepEqual(publicFiles(candidateDir), assets, "Copied public assets must retain the same paths");
for (const asset of assets) assert.deepEqual(fs.readFileSync(path.join(candidateDir, asset)), fs.readFileSync(path.join(baselineDir, asset)), `Public asset changed: ${asset}`);
console.log(`All ${routes.length} prerendered HTML documents match the baseline DOM and JSON-LD; generated asset references exist; ${assets.length} public assets remain byte-identical.`);
