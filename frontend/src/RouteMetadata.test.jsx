import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter } from "react-router";
import { RouteMetadata } from "./App";
import routeMeta from "./routeMeta.json";

const HEAD = `
  <meta name="description" content="">
  <meta name="robots" content="">
  <meta property="og:title" content="">
  <meta property="og:description" content="">
  <meta property="og:url" content="">
  <meta name="twitter:title" content="">
  <meta name="twitter:description" content="">
  <link rel="canonical" href="">`;

function metadataAt(path) {
  document.head.innerHTML = HEAD;
  render(<MemoryRouter initialEntries={[path]}><RouteMetadata /></MemoryRouter>);
  // <head> metadata has no accessible role, so Testing Library queries can't reach it.
  // eslint-disable-next-line testing-library/no-node-access
  const attr = (selector, name) => document.head.querySelector(selector).getAttribute(name);
  return {
    title: document.title,
    description: attr('meta[name="description"]', "content"),
    robots: attr('meta[name="robots"]', "content"),
    canonical: attr('link[rel="canonical"]', "href"),
    ogUrl: attr('meta[property="og:url"]', "content"),
  };
}

afterEach(() => { document.head.innerHTML = ""; });

test.each(["/partners", "/partners/", "/partners//"])("%s keeps the partner page's own metadata and canonical", (path) => {
  expect(metadataAt(path)).toEqual({
    title: routeMeta["/partners"].title,
    description: routeMeta["/partners"].description,
    robots: "index,follow,max-image-preview:large",
    canonical: "https://www.retainai.ca/partners",
    ogUrl: "https://www.retainai.ca/partners",
  });
});

test.each(["/login", "/login/"])("%s stays noindex with its own title", (path) => {
  expect(metadataAt(path)).toMatchObject({ title: routeMeta["/login"].title, robots: "noindex,nofollow", canonical: "https://www.retainai.ca/" });
});

test("the homepage keeps its canonical and the workspace stays noindex", () => {
  expect(metadataAt("/")).toMatchObject({ title: routeMeta["/"].title, robots: "index,follow,max-image-preview:large", canonical: "https://www.retainai.ca/" });
  expect(metadataAt("/app/")).toMatchObject({ robots: "noindex,nofollow" });
});

// The static host answers every URL with the app, so an unknown path that kept
// the homepage's indexable metadata looked like a duplicate homepage (soft 404).
test.each(["/not-a-page", "/not-a-page/", "/pricing/extra", "/r/code/extra"])("unknown path %s is noindex, not a copy of the homepage", (path) => {
  expect(metadataAt(path)).toMatchObject({ title: "Page not found — RetainAI", robots: "noindex" });
});

test.each(Object.keys(routeMeta).filter((path) => !["/login", "/accept-invite"].includes(path)))("known public route %s stays indexable", (path) => {
  expect(metadataAt(path).robots).toBe("index,follow,max-image-preview:large");
});

test.each(["/r/salon-coach", "/r/SalonCoach", "/R/SalonCoach"])("partner referral link %s is not treated as a missing page", (path) => {
  expect(metadataAt(path)).toMatchObject({ title: routeMeta["/"].title, robots: "index,follow,max-image-preview:large" });
});

// React Router matches case-insensitively against the percent-decoded path, so
// these addresses show the real page and must carry its metadata, with the
// canonical in lowercase.
test.each([
  ["/PRICING", "/pricing"],
  ["/Pricing/", "/pricing"],
  ["/%70ricing", "/pricing"],
  ["/%50RICING", "/pricing"],
  ["/Privacy-Policy", "/privacy-policy"],
  ["/retention%2Dcrm%2Dfor%2Dservice%2Dbusinesses", "/retention-crm-for-service-businesses"],
])("%s gets %s metadata and its lowercase canonical", (path, route) => {
  expect(metadataAt(path)).toEqual({
    title: routeMeta[route].title,
    description: routeMeta[route].description,
    robots: "index,follow,max-image-preview:large",
    canonical: `https://www.retainai.ca${route}`,
    ogUrl: `https://www.retainai.ca${route}`,
  });
});

test.each(["/LOGIN", "/%6Cogin", "/APP/settings", "/Accept-Invite"])("private route %s stays noindex whatever its case or encoding", (path) => {
  expect(metadataAt(path)).toMatchObject({ robots: "noindex,nofollow", canonical: "https://www.retainai.ca/" });
});

test.each(["/pricing%2Fextra", "/%E0%A4%A", "/pricing%"])("%s, which the router does not match, is a noindex missing page", (path) => {
  expect(metadataAt(path)).toMatchObject({ title: "Page not found — RetainAI", robots: "noindex" });
});

test("FAQ schema is reused on pricing and removed when its answers are not on the page", () => {
  document.head.innerHTML = `${HEAD}<script id="retainai-faq-schema" type="application/ld+json">{}</script>`;
  render(<MemoryRouter initialEntries={["/"]}><RouteMetadata /><Link to="/pricing">Pricing</Link><Link to="/about">About</Link></MemoryRouter>);
  // Structured data lives in head and has no accessible role.
  // eslint-disable-next-line testing-library/no-node-access
  const schemas = () => document.head.querySelectorAll("#retainai-faq-schema");
  expect(schemas()).toHaveLength(1);
  expect(JSON.parse(schemas()[0].textContent).mainEntity).toHaveLength(6);
  fireEvent.click(screen.getByRole("link", { name: "Pricing" }));
  expect(schemas()).toHaveLength(1);
  expect(document.title).toBe(routeMeta["/pricing"].title);
  fireEvent.click(screen.getByRole("link", { name: "About" }));
  expect(schemas()).toHaveLength(0);
  expect(document.title).toBe(routeMeta["/about"].title);
});
