import fs from "fs";
import path from "path";
import routeMeta from "../routeMeta.json";
import publicContent from "../publicContent.json";
import { PRIVATE_ROUTES, PUBLIC_ROUTES, renderRouteHtml as buildRouteHtml } from "./routeHtml";

const homepage = fs.readFileSync(path.resolve(__dirname, "../../public/index.html"), "utf8");

function head(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const attr = (selector, name) => doc.querySelector(selector)?.getAttribute(name);
  return {
    title: doc.title,
    description: attr('meta[name="description"]', "content"),
    robots: attr('meta[name="robots"]', "content"),
    canonical: attr('link[rel="canonical"]', "href"),
    ogUrl: attr('meta[property="og:url"]', "content"),
    ogTitle: attr('meta[property="og:title"]', "content"),
    twitterDescription: attr('meta[name="twitter:description"]', "content"),
    h1: doc.querySelector("#root h1")?.textContent,
    canonicals: doc.querySelectorAll('link[rel="canonical"]').length,
  };
}

test.each(PUBLIC_ROUTES)("%s gets its own indexable title, description and canonical before JavaScript", (route) => {
  const meta = routeMeta[route];
  const page = head(buildRouteHtml(homepage, route, meta, { indexable: true }));
  expect(page).toMatchObject({
    title: meta.title,
    description: meta.description,
    robots: "index,follow,max-image-preview:large",
    canonical: `https://www.retainai.ca${route}`,
    ogUrl: `https://www.retainai.ca${route}`,
    ogTitle: meta.title,
    twitterDescription: meta.description,
    h1: publicContent.pages[route]?.heading || meta.title,
    canonicals: 1,
  });
});

test.each(PRIVATE_ROUTES)("%s is noindex from the first byte", (route) => {
  const page = head(buildRouteHtml(homepage, route, routeMeta[route], { indexable: false }));
  expect(page.robots).toBe("noindex,nofollow");
  expect(page.title).toBe(routeMeta[route].title);
});

test("the homepage keeps its full summary and gets the app's homepage metadata", () => {
  const page = head(buildRouteHtml(homepage, "/", routeMeta["/"], { indexable: true }));
  expect(page).toMatchObject({ title: routeMeta["/"].title, description: routeMeta["/"].description, canonical: "https://www.retainai.ca/" });
  expect(page.h1).toBe("The AI CRM that keeps customers coming back.");
});

test("values are HTML-escaped and a missing tag fails instead of shipping wrong metadata", () => {
  const escaped = buildRouteHtml(homepage, "/refund-policy", { title: 'Refunds & "cancellations"', description: "<b>x</b>" }, { indexable: true });
  expect(escaped).toContain("<title>Refunds &amp; &quot;cancellations&quot;</title>");
  expect(escaped).not.toContain("<b>x</b>");
  expect(() => buildRouteHtml(homepage.replace(/<link rel="canonical"[^>]*>/, ""), "/partners", routeMeta["/partners"], { indexable: true }))
    .toThrow(/canonical/);
  expect(() => buildRouteHtml(homepage, "/nowhere", undefined, { indexable: true })).toThrow(/no metadata/);
});

test("every prerendered route has metadata, and structured data matches the visible launch price", () => {
  for (const route of [...PUBLIC_ROUTES, ...PRIVATE_ROUTES]) expect(routeMeta[route]).toBeTruthy();
  const jsonLd = JSON.parse(homepage.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);
  const landing = fs.readFileSync(path.resolve(__dirname, "../components/LandingPage.jsx"), "utf8");
  const visible = landing.match(/className="lp-price"><strong>\$(\d+)<\/strong><span>CAD/)[1];
  expect(jsonLd.offers).toMatchObject({ priceCurrency: "CAD", price: visible });
});

test("the install manifests do not advertise placeholder screenshots", () => {
  for (const name of ["manifest.webmanifest", "manifest.json"]) {
    const manifest = JSON.parse(fs.readFileSync(path.resolve(__dirname, `../../public/${name}`), "utf8"));
    expect(manifest.screenshots).toBeUndefined();
  }
});

test.each(["/", "/pricing"])("%s serves the exact visible FAQ answers and schema before JavaScript", (route) => {
  const html = buildRouteHtml(homepage, route, routeMeta[route], { indexable: true });
  const doc = new DOMParser().parseFromString(html, "text/html");
  const schema = JSON.parse(doc.querySelector("#retainai-faq-schema").textContent);
  expect(doc.querySelectorAll("h1")).toHaveLength(1);
  expect(doc.querySelectorAll("details")).toHaveLength(6);
  expect(doc.querySelector("details").hasAttribute("open")).toBe(true);
  expect(schema.mainEntity).toHaveLength(6);
  publicContent.faqs.forEach(([question, answer], index) => {
    expect(schema.mainEntity[index]).toMatchObject({ name: question, acceptedAnswer: { text: answer } });
    expect(doc.body.textContent).toContain(answer);
  });
});

test("category content and internal links are present before JavaScript", () => {
  const route = "/retention-crm-for-service-businesses";
  const doc = new DOMParser().parseFromString(buildRouteHtml(homepage, route, routeMeta[route], { indexable: true }), "text/html");
  expect(doc.body.textContent).toContain("From memory to a shared next step");
  expect(doc.body.textContent).toContain("It is not built for large sales organizations");
  expect(doc.querySelector('a[href="/pricing"]')).not.toBeNull();
  expect(doc.querySelector("#retainai-faq-schema")).toBeNull();
});

test("the sitemap lists exactly the indexable routes, and the rebooking guide is linked before JavaScript", () => {
  const sitemap = fs.readFileSync(path.resolve(__dirname, "../../public/sitemap.xml"), "utf8");
  const listed = [...sitemap.matchAll(/<loc>https:\/\/www\.retainai\.ca([^<]*)<\/loc>/g)].map((match) => match[1] || "/");
  expect([...listed].sort()).toEqual(["/", ...PUBLIC_ROUTES].sort());
  for (const route of PRIVATE_ROUTES) expect(listed).not.toContain(route);

  const route = "/find-customers-who-stopped-rebooking";
  const doc = new DOMParser().parseFromString(buildRouteHtml(homepage, route, routeMeta[route], { indexable: true }), "text/html");
  expect(doc.querySelector("h1").textContent).toBe("How to find customers who stopped rebooking");
  expect(doc.body.textContent).toContain("usual time between them");
  const fromCategory = new DOMParser().parseFromString(buildRouteHtml(homepage, "/retention-crm-for-service-businesses", routeMeta["/retention-crm-for-service-businesses"], { indexable: true }), "text/html");
  expect(fromCategory.querySelector(`a[href="${route}"]`)).not.toBeNull();
});

test("/partners serves its terms and live product benefits before JavaScript", () => {
  const doc = new DOMParser().parseFromString(buildRouteHtml(homepage, "/partners", routeMeta["/partners"], { indexable: true }), "text/html");
  const text = doc.body.textContent;
  expect(text).toContain("30% of qualifying base membership payments for the first 12 months");
  expect(text).toContain("30-day hold");
  publicContent.partners.benefits.forEach((item) => expect(text).toContain(item));
  expect(doc.querySelector('a[href^="mailto:owner@retainai.ca"]')).not.toBeNull();
  expect(text).toContain("earnings are not guaranteed");
  expect(doc.querySelectorAll("h1")).toHaveLength(1);
});
