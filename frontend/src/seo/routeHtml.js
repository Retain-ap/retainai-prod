// Builds each public route's initial HTML from the homepage build output, so a
// crawler gets the route's own title, description, canonical URL and summary
// before JavaScript runs (Google advises against relying on JavaScript to change
// an initial canonical). CommonJS so scripts/prerender-routes.js (Node) and Jest
// can both load it. Every replacement must match exactly once, or the build fails.

const SITE = "https://www.retainai.ca";

// Indexable public pages, and pages that must never be indexed.
const PUBLIC_ROUTES = ["/partners", "/signup", "/privacy-policy", "/terms-of-service", "/refund-policy"];
const PRIVATE_ROUTES = ["/login", "/accept-invite"];

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function countMatches(html, pattern) {
  const flags = pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`;
  return (html.match(new RegExp(pattern.source, flags)) || []).length;
}

function replaceOnce(html, pattern, replace, label) {
  const found = countMatches(html, pattern);
  if (found !== 1) throw new Error(`prerender: expected exactly one ${label}, found ${found}`);
  return html.replace(pattern, replace);
}

function setAttribute(html, tagPattern, attribute, value, label) {
  const attr = new RegExp(`\\s${attribute}="[^"]*"`);
  return replaceOnce(html, tagPattern, (tag) => {
    if (!attr.test(tag)) throw new Error(`prerender: ${label} has no ${attribute}`);
    return tag.replace(attr, () => ` ${attribute}="${escapeHtml(value)}"`);
  }, label);
}

function fallbackContent(meta, path) {
  const title = escapeHtml(meta.title);
  const description = escapeHtml(meta.description);
  const action = path === "/signup"
    ? '<a href="/signup" style="color:#f5d87e">Start a 14-day trial</a>'
    : '<a href="/" style="color:#f5d87e">RetainAI home</a>';
  return (
    '<main style="min-height:100vh;background:#0b0c0e;color:#fff;padding:64px 7%;font-family:Arial,sans-serif">' +
    `<h1 style="font-size:40px;line-height:1.1">${title}</h1>` +
    `<p style="font-size:19px;line-height:1.6;color:#c8cad0;max-width:760px">${description}</p>` +
    `<p>${action}</p></main>`
  );
}

/**
 * @param {string} html  the built homepage HTML
 * @param {string} path  a key of routeMeta, e.g. "/partners"
 * @param {{title: string, description: string}} meta
 * @param {{indexable: boolean}} options
 */
function renderRouteHtml(html, path, meta, { indexable }) {
  if (!meta || !meta.title || !meta.description) throw new Error(`prerender: no metadata for ${path}`);
  const canonical = indexable ? `${SITE}${path === "/" ? "/" : path}` : `${SITE}/`;
  let out = html;
  out = replaceOnce(out, /<title>[^<]*<\/title>/, () => `<title>${escapeHtml(meta.title)}</title>`, "<title>");
  const tags = [
    [/<meta name="description"[^>]*>/, "content", meta.description, "description"],
    [/<meta name="robots"[^>]*>/, "content", indexable ? "index,follow,max-image-preview:large" : "noindex,nofollow", "robots"],
    [/<link rel="canonical"[^>]*>/, "href", canonical, "canonical"],
    [/<meta property="og:title"[^>]*>/, "content", meta.title, "og:title"],
    [/<meta property="og:description"[^>]*>/, "content", meta.description, "og:description"],
    [/<meta property="og:url"[^>]*>/, "content", canonical, "og:url"],
    [/<meta name="twitter:title"[^>]*>/, "content", meta.title, "twitter:title"],
    [/<meta name="twitter:description"[^>]*>/, "content", meta.description, "twitter:description"],
  ];
  for (const [pattern, attribute, value, label] of tags) {
    out = setAttribute(out, pattern, attribute, value, label);
  }
  if (path !== "/") {
    out = replaceOnce(
      out,
      /<div id="root">[\s\S]*<\/div>(\s*<\/body>)/,
      (_match, bodyClose) => `<div id="root">${fallbackContent(meta, path)}</div>${bodyClose}`,
      "root fallback"
    );
  }
  return out;
}

module.exports = { PUBLIC_ROUTES, PRIVATE_ROUTES, SITE, renderRouteHtml, escapeHtml };
