import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { API_BASE } from "../config";

export default function StripeConnectCard({ user, refreshUser }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const location = useLocation();
  const navigate = useNavigate();

  const API = useMemo(() => {
    const env = (v) => (v && v.trim()) || "";
    const fromEnv =
      env(process.env.REACT_APP_API_URL) ||
      env(process.env.REACT_APP_API_BASE);

    if (fromEnv) return fromEnv.replace(/\/$/, "");
    return (API_BASE || "").replace(/\/$/, "");
  }, []);

  const isConnected = user?.stripe_connected === true;

  useEffect(() => {
    const params = new URLSearchParams(location.search);

    const connected = params.get("stripe_connected") === "1";
    const refreshed = params.get("stripe_refresh") === "1";
    const hasError = params.get("stripe_error") === "1";
    const errorDesc = params.get("stripe_error_desc");

    if (connected || refreshed) {
      (async () => {
        try {
          if (typeof refreshUser === "function") {
            await refreshUser();
          }
        } catch {}
      })();

      params.delete("stripe_connected");
      params.delete("stripe_refresh");

      navigate(
        {
          pathname: location.pathname,
          search: params.toString(),
        },
        { replace: true }
      );
    }

    if (hasError) {
      setError(decodeURIComponent(errorDesc || "Stripe connection failed."));
      params.delete("stripe_error");
      params.delete("stripe_error_desc");

      navigate(
        {
          pathname: location.pathname,
          search: params.toString(),
        },
        { replace: true }
      );
    }
  }, [location.pathname, location.search, navigate, refreshUser]);

  async function fetchStripeUrl(path, fallbackError) {
    if (!user?.email) {
      throw new Error("Missing user email");
    }

    const url = `${API}${path}?user_email=${encodeURIComponent(user.email)}`;

    const res = await fetch(url, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
    });

    const contentType = (res.headers.get("content-type") || "").toLowerCase();
    const raw = await res.text();

    let data = {};
    if (contentType.includes("application/json")) {
      try {
        data = JSON.parse(raw);
      } catch {
        throw new Error(`Invalid JSON response (${res.status})`);
      }
    } else {
      throw new Error(`Invalid server response (${res.status})`);
    }

    if (!res.ok) {
      throw new Error(data?.error || fallbackError || `Request failed (${res.status})`);
    }

    if (!data?.url) {
      throw new Error(data?.error || fallbackError || "Missing redirect URL");
    }

    return data.url;
  }

  async function handleDashboard() {
    setLoading(true);
    setError("");
    try {
      const url = await fetchStripeUrl(
        "/api/stripe/dashboard-link",
        "Could not open Stripe dashboard"
      );
      window.location.assign(url);
    } catch (e) {
      setError(e.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  async function handleLinkExisting() {
    setLoading(true);
    setError("");
    try {
      const url = await fetchStripeUrl(
        "/api/stripe/oauth/connect",
        "Failed to link existing Stripe account"
      );
      window.location.assign(url);
    } catch (e) {
      setError(e.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  async function handleSignup() {
    setLoading(true);
    setError("");
    try {
      const url = await fetchStripeUrl(
        "/api/stripe/connect-url",
        "Failed to create Stripe account"
      );
      window.location.assign(url);
    } catch (e) {
      setError(e.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  async function handleDisconnect() {
    if (!user?.email) {
      setError("Missing user email");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const res = await fetch(
        `${API}/api/stripe/disconnect?user_email=${encodeURIComponent(user.email)}`,
        {
          method: "POST",
          credentials: "include",
          headers: { Accept: "application/json" },
        }
      );

      const contentType = (res.headers.get("content-type") || "").toLowerCase();
      const raw = await res.text();

      let data = {};
      if (contentType.includes("application/json") && raw) {
        try {
          data = JSON.parse(raw);
        } catch {}
      }

      if (!res.ok) {
        setError(data?.error || `Failed to disconnect (${res.status})`);
        return;
      }

      if (typeof refreshUser === "function") {
        await refreshUser();
      }
    } catch (e) {
      setError(e.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={`integration-card${isConnected ? " stripe-connected" : ""}`}>
      <div
        style={{
          width: "100%",
          minHeight: 240,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ fontSize: 34, color: "#635bff", marginBottom: 12 }}>
          <svg width="34" height="34" viewBox="0 0 24 24" fill="currentColor">
            <path d="M7.8 4.5h8.4v2.1H11.7c-2.1 0-3.3 1.2-3.3 3s1.2 3 3.3 3H16c2.1 0 3.6 1.2 3.6 3.9 0 2.7-1.8 4.5-5.4 4.5H8.1v-2.1h6.6c1.8 0 2.7-1.2 2.7-2.7 0-1.5-.9-2.7-2.7-2.7H8.1v-2.1H16c1.8 0 3-1.2 3-2.7s-1.2-2.7-3-2.7H7.8v-2.1z" />
          </svg>
        </span>

        <div style={{ width: "100%", textAlign: "center" }}>
          <div style={{ fontWeight: 700, color: "#fff", fontSize: 20, marginBottom: 2 }}>
            Stripe Payments
          </div>

          <div style={{ color: "#aaa", fontSize: 15, margin: "2px 0 18px 0" }}>
            {isConnected
              ? "Your Stripe account is connected."
              : "Connect or create a Stripe account to accept payments."}
          </div>

          {isConnected ? (
            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 12 }}>
              <button className="settings-btn connected" disabled>
                Connected
              </button>

              <button className="settings-btn" onClick={handleDashboard} disabled={loading}>
                {loading ? "Opening…" : "Open Stripe Dashboard"}
              </button>

              <button
                className="settings-btn refresh"
                onClick={async () => {
                  setError("");
                  if (typeof refreshUser === "function") {
                    try {
                      await refreshUser();
                    } catch {}
                  }
                }}
                disabled={loading}
              >
                Refresh Status
              </button>

              <button
                className="settings-btn disconnect"
                onClick={handleDisconnect}
                disabled={loading}
                style={{ background: "#e66565" }}
              >
                {loading ? "Disconnecting…" : "Disconnect"}
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 12 }}>
              <button className="settings-btn" onClick={handleLinkExisting} disabled={loading}>
                {loading ? "Redirecting…" : "Link Existing Stripe Account"}
              </button>

              <button className="settings-btn" onClick={handleSignup} disabled={loading}>
                {loading ? "Redirecting…" : "Create Stripe Account"}
              </button>
            </div>
          )}

          {error && (
            <div className="integration-error" style={{ color: "#e66565", marginTop: 16 }}>
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}