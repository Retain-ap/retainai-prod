// src/App.jsx
import React, { useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import LandingPage from "./components/LandingPage";
import Login from "./components/Login";
import Signup from "./components/Signup";
import CrmDashboard from "./components/CrmDashboard";
import ProtectedRoute from "./components/ProtectedRoute";
import PrivacyPolicy from "./pages/PrivacyPolicy";
import TermsOfService from "./pages/TermsOfService";
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

function App() {
  return (
    <SettingsProvider>
      <Router>
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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </SettingsProvider>
  );
}

export default App;
