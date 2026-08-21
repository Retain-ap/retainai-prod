// src/App.jsx
import React, { useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import LandingPage from "./components/LandingPage";
import Login from "./components/Login";
import Signup from "./components/Signup";
import CrmDashboard from "./components/CrmDashboard";
import ProtectedRoute from "./components/ProtectedRoute";
import PrivacyPolicy from "./pages/PrivacyPolicy";
import TermsOfService from "./pages/TermsOfService";
import RefundPolicy from "./pages/RefundPolicy";
import AcceptInvite from "./pages/AcceptInvite"; // ← added
import { SettingsProvider } from "./components/SettingsContext";
import "./index.css";

/** Listens for the Google Contacts popup completion and navigates back to /app/import */
function OAuthPopupBridge() {
  const navigate = useNavigate();
  useEffect(() => {
    const handler = (e) => {
      if (e?.data && e.data.type === "google-import-complete") {
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
    const privateRoute = pathname.startsWith("/app") || pathname === "/login";
    const meta = ROUTE_META[pathname] || ROUTE_META["/"];
    const canonicalPath = ROUTE_META[pathname] ? pathname : "/";
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
      <Router>
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
                <CrmDashboard />
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
