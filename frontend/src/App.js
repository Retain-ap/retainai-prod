// src/App.jsx
import React, { Suspense, lazy, useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useNavigate } from "react-router";
import LandingPage from "./components/LandingPage";
import MarketingPage from "./pages/MarketingPage";
import publicContent from "./publicContent.json";
import Login from "./components/Login";
import Signup from "./components/Signup";
import ProtectedRoute from "./components/ProtectedRoute";
import PrivacyPolicy from "./pages/PrivacyPolicy";
import TermsOfService from "./pages/TermsOfService";
import RefundPolicy from "./pages/RefundPolicy";
import Partners from "./pages/Partners";
import ReferralRedirect from "./pages/ReferralRedirect";
import AcceptInvite from "./pages/AcceptInvite"; // ← added
import NotFound from "./pages/NotFound";
import { SettingsProvider } from "./components/SettingsContext";
import { API_BASE } from "./apiBase";
import "./index.css";
import routeMeta from "./routeMeta.json";

const CHUNK_RELOAD_KEY = "retainai:chunk-reload";

/** Load the signed-in workspace on demand; reload once if a deploy replaced its chunk. */
const CrmDashboard = lazy(() =>
  import("./components/CrmDashboard")
    .then((module) => {
      try {
        window.sessionStorage.removeItem(CHUNK_RELOAD_KEY);
      } catch {}
      return module;
    })
    .catch((error) => {
      let reloaded = false;
      try {
        reloaded = window.sessionStorage.getItem(CHUNK_RELOAD_KEY) === "1";
        if (!reloaded) window.sessionStorage.setItem(CHUNK_RELOAD_KEY, "1");
      } catch {
        reloaded = true;
      }
      if (!reloaded) {
        window.location.reload();
        return new Promise(() => {});
      }
      throw error;
    })
);

function WorkspaceLoading() {
  return (
    <div
      role="status"
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "#0f1115",
        color: "#d7d3ca",
        fontWeight: 700,
      }}
    >
      Loading your workspace…
    </div>
  );
}

/** Listens for the Google Contacts popup completion and navigates back to /app/import */
function OAuthPopupBridge() {
  const navigate = useNavigate();
  useEffect(() => {
    const handler = (e) => {
      let trustedOrigin = "";
      try {
        trustedOrigin = new URL(API_BASE, window.location.origin).origin;
      } catch (_) {
        trustedOrigin = window.location.origin;
      }
      if (
        e.origin === trustedOrigin &&
        e?.data &&
        e.data.type === "google-import-complete"
      ) {
        navigate("/app/import", { replace: true });
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [navigate]);
  return null;
}

// Shared with scripts/prerender-routes.js, which writes the same metadata into
// each public route's initial HTML at build time.
const ROUTE_META = routeMeta;

const NOT_FOUND_META = {
  title: "Page not found — RetainAI",
  description: "This RetainAI page doesn't exist. Continue from the homepage, pricing or log in.",
};

// Every path the router serves. The static host returns the app for any URL,
// so an unknown path must say noindex itself or search engines treat it as a
// copy of the homepage (a soft 404).
function isKnownPath(pathname) {
  return Boolean(ROUTE_META[pathname]) || /^\/app(\/|$)/.test(pathname) || /^\/r\/[^/]+$/.test(pathname);
}

// The key metadata is looked up by, matched the way React Router matches routes:
// percent-decoded per segment (an encoded "/" stays inside its segment; if any
// escape is malformed the path is used as typed, like the router's decodePath)
// and compared case-insensitively, so /PRICING and /%70ricing are /pricing.
// A static host may also redirect /partners to /partners/, so trailing slashes
// are dropped; "/" stays "/". Only this lookup key is lowercased: the URL
// itself, including a referral code, is never rewritten.
function routeKey(rawPathname) {
  let decoded = rawPathname;
  try {
    decoded = rawPathname
      .split("/")
      .map((segment) => decodeURIComponent(segment).replace(/\//g, "%2F"))
      .join("/");
  } catch {}
  return decoded.replace(/\/+$/, "").toLowerCase() || "/";
}

export function RouteMetadata() {
  const { pathname: rawPathname } = useLocation();
  const pathname = routeKey(rawPathname);

  useEffect(() => {
    const privateRoute =
      pathname.startsWith("/app") ||
      pathname === "/login" ||
      pathname === "/accept-invite";
    const notFound = !privateRoute && !isKnownPath(pathname);
    const meta = notFound
      ? NOT_FOUND_META
      : ROUTE_META[pathname] ||
        (pathname.startsWith("/app")
          ? { title: "RetainAI", description: ROUTE_META["/"].description }
          : ROUTE_META["/"]);
    const canonicalPath = privateRoute ? "/" : ROUTE_META[pathname] ? pathname : "/";
    const canonicalUrl = `https://www.retainai.ca${canonicalPath === "/" ? "/" : canonicalPath}`;

    document.title = meta.title;
    const setMeta = (selector, attribute, value) => {
      const element = document.head.querySelector(selector);
      if (element) element.setAttribute(attribute, value);
    };
    setMeta('meta[name="description"]', "content", meta.description);
    setMeta(
      'meta[name="robots"]',
      "content",
      privateRoute ? "noindex,nofollow" : notFound ? "noindex" : "index,follow,max-image-preview:large"
    );
    setMeta('meta[property="og:title"]', "content", meta.title);
    setMeta('meta[property="og:description"]', "content", meta.description);
    setMeta('meta[property="og:url"]', "content", canonicalUrl);
    setMeta('meta[name="twitter:title"]', "content", meta.title);
    setMeta('meta[name="twitter:description"]', "content", meta.description);
    setMeta('link[rel="canonical"]', "href", canonicalUrl);
    // Keep one FAQ schema, only on routes that visibly include these answers.
    let faqScript = document.head.querySelector("#retainai-faq-schema");
    if (pathname === "/" || pathname === "/pricing") {
      if (!faqScript) {
        faqScript = document.createElement("script");
        faqScript.id = "retainai-faq-schema";
        faqScript.type = "application/ld+json";
        document.head.appendChild(faqScript);
      }
      faqScript.textContent = JSON.stringify({ "@context": "https://schema.org", "@type": "FAQPage", mainEntity: publicContent.faqs.map(([question, answer]) => ({ "@type": "Question", name: question, acceptedAnswer: { "@type": "Answer", text: answer } })) });
    } else {
      faqScript?.remove();
    }
  }, [pathname]);

  return null;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      {Object.keys(publicContent.pages).map((path) => <Route key={path} path={path} element={<MarketingPage path={path} />} />)}
      <Route path="/partners" element={<Partners />} />
      <Route path="/r/:code" element={<ReferralRedirect />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route
        path="/app/*"
        element={
          <Suspense fallback={<WorkspaceLoading />}>
            <ProtectedRoute>
              <CrmDashboard />
            </ProtectedRoute>
          </Suspense>
        }
      />
      <Route path="/accept-invite" element={<AcceptInvite />} /> {/* ← added */}
      <Route path="/privacy-policy" element={<PrivacyPolicy />} />
      <Route path="/terms-of-service" element={<TermsOfService />} />
      <Route path="/refund-policy" element={<RefundPolicy />} />
      {/* Short names people type or remember from Closet Muse. */}
      <Route path="/privacy" element={<Navigate to="/privacy-policy" replace />} />
      <Route path="/terms" element={<Navigate to="/terms-of-service" replace />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

function App() {
  return (
    <SettingsProvider>
      <Router>
        <RouteMetadata />
        {/* Always mounted so we catch the popup postMessage */}
        <OAuthPopupBridge />
        <AppRoutes />
      </Router>
    </SettingsProvider>
  );
}

export default App;
