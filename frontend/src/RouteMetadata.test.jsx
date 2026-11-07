import React from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
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

test("the homepage and unknown paths still use the homepage canonical", () => {
  expect(metadataAt("/")).toMatchObject({ title: routeMeta["/"].title, canonical: "https://www.retainai.ca/" });
  expect(metadataAt("/not-a-page/")).toMatchObject({ title: routeMeta["/"].title, canonical: "https://www.retainai.ca/" });
  expect(metadataAt("/app/")).toMatchObject({ robots: "noindex,nofollow" });
});
