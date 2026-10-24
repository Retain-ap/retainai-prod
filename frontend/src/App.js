// src/App.jsx
import React, { Suspense, lazy, useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import LandingPage from "./components/LandingPage";
import Login from "./components/Login";
import Signup from "./components/Signup";
import ProtectedRoute from "./components/ProtectedRoute";
import PrivacyPolicy from "./pages/PrivacyPolicy";
import TermsOfService from "./pages/TermsOfService";
import RefundPolicy from "./pages/RefundPolicy";
import AcceptInvite from "./pages/AcceptInvite"; // ← added
import { SettingsProvider } from "./components/SettingsContext";
import { API_BASE } from "./apiBase";
import "./index.css";

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

const ROUTE_META = {
  "/": {
    title: "RetainAI — Keep More Customers and Miss Fewer Follow-Ups",
    description:
      "Bring WhatsApp conversations, customer follow-ups, appointments, invoices, and retention priorities into one clear workspace with RetainAI.",
  },
  "/signup": {
    title: "Start Your RetainAI Trial — Customer Retention CRM",
    description:
      "Start a 14-day RetainAI trial and organize customer relationships, follow-ups, appointments, invoices, and retention opportunities.",
  },
  "/privacy-policy": {
    title: "Privacy Policy — RetainAI",
    description: "Learn how RetainAI protects customer and account information.",
  },
  "/terms-of-service": {
    title: "Terms of Service — RetainAI",
    description: "Review the terms governing use of the RetainAI customer retention CRM.",
  },
  "/refund-policy": {
    title: "Refund & Cancellation Policy — RetainAI",
    description: "Review RetainAI trial, subscription, cancellation, and refund terms.",
  },
};

function RouteMetadata() {
  const { pathname } = useLocation();

  useEffect(() => {
    const privateRoute =
      pathname.startsWith("/app") ||
      pathname === "/login" ||
      pathname === "/accept-invite";
    const meta = ROUTE_META[pathname] || ROUTE_META["/"];
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
      privateRoute ? "noindex,nofollow" : "index,follow,max-image-preview:large"
    );
    setMeta('meta[property="og:title"]', "content", meta.title);
    setMeta('meta[property="og:description"]', "content", meta.description);
    setMeta('meta[property="og:url"]', "content", canonicalUrl);
    setMeta('meta[name="twitter:title"]', "content", meta.title);
    setMeta('meta[name="twitter:description"]', "content", meta.description);
    setMeta('link[rel="canonical"]', "href", canonicalUrl);
  }, [pathname]);

  return null;
}

function App() {
  return (
    <SettingsProvider>
      <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <RouteMetadata />
        {/* Always mounted so we catch the popup postMessage */}
        <OAuthPopupBridge />
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route
            path="/app/*"
            element={
              <ProtectedRoute>
                <Suspense fallback={<WorkspaceLoading />}>
                  <CrmDashboard />
                </Suspense>
              </ProtectedRoute>
            }
          />
          <Route path="/accept-invite" element={<AcceptInvite />} /> {/* ← added */}
          <Route path="/privacy-policy" element={<PrivacyPolicy />} />
          <Route path="/terms-of-service" element={<TermsOfService />} />
          <Route path="/refund-policy" element={<RefundPolicy />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </SettingsProvider>
  );
}

export default App;
