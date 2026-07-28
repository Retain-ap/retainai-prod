// File: frontend/src/components/StripeConnectCard.jsx
import React, { useState } from "react";
import { apiUrl } from "../apiBase";

export default function StripeConnectCard({ user, refreshUser }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const isConnected = user?.stripe_connected === true;

  async function fetchJson(url, options = {}) {
    const res = await fetch(url, {
      credentials: "include",
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
    });

    const contentType = (res.headers.get("content-type") || "").toLowerCase();
    const raw = await res.text();

    let data = {};
    if (contentType.includes("application/json") && raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        throw new Error(`Invalid JSON response (${res.status})`);
      }
    }

    if (!res.ok) {
      throw new Error(data?.error || `Request failed (${res.status})`);
    }

    return data;
  }

  async function fetchStripeUrl(path, fallbackError) {
    if (!user?.email) {
      throw new Error("Missing user email");
    }

    const url = apiUrl(
      `${path}?user_email=${encodeURIComponent(user.email)}`
    );

    const data = await fetchJson(url, { method: "GET" });

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
        "stripe/dashboard-link",
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
        "stripe/oauth/connect",
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
        "stripe/connect-url",
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
      await fetchJson(
        apiUrl(`stripe/disconnect?user_email=${encodeURIComponent(user.email)}`),
        { method: "POST" }
      );

      if (typeof refreshUser === "function") {
        await refreshUser();
      }
    } catch (e) {
      setError(e.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  async function handleRefresh() {
    setError("");

    if (typeof refreshUser === "function") {
      try {
        await refreshUser();
      } catch (e) {
        setError(e.message || "Could not refresh Stripe status");
      }
    }
  }

  return (
    <article className={`account-card account-card-stripe${isConnected ? " is-connected" : ""}`}>
      <div className="account-card-top">
        <div className="account-brand-icon stripe" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M7.8 4.5h8.4v2.1H11.7c-2.1 0-3.3 1.2-3.3 3s1.2 3 3.3 3H16c2.1 0 3.6 1.2 3.6 3.9 0 2.7-1.8 4.5-5.4 4.5H8.1v-2.1h6.6c1.8 0 2.7-1.2 2.7-2.7 0-1.5-.9-2.7-2.7-2.7H8.1v-2.1H16c1.8 0 3-1.2 3-2.7s-1.2-2.7-3-2.7H7.8v-2.1z" />
          </svg>
        </div>
        <span className={`account-status-badge ${isConnected ? "connected" : "disconnected"}`}>
          <span />
          {isConnected ? "Connected" : "Not connected"}
        </span>
      </div>

      <div className="account-card-copy">
        <h3>Stripe Payments</h3>
        <p>Accept payments and manage your connected Stripe business account.</p>
      </div>

      <div className="account-card-content">
        <div className="account-detail-box">
          {isConnected
            ? "Payments are enabled for this workspace. Open Stripe for payouts, balances, and account settings."
            : "Link an existing Stripe account or create a new one through RetainAI."}
        </div>
        {user?.stripe_account_id ? (
          <div className="account-id-row">
            <span>Account</span>
            <code>{user.stripe_account_id}</code>
          </div>
        ) : null}
        {error ? <div className="account-inline-message error">{error}</div> : null}
      </div>

      <div className="account-card-actions">
        {isConnected ? (
          <>
            <button className="account-primary-btn stripe" onClick={handleDashboard} disabled={loading}>
              {loading ? "Opening…" : "Open Stripe"}
            </button>
            <button className="account-secondary-btn" onClick={handleRefresh} disabled={loading}>
              Refresh
            </button>
            <button className="account-danger-btn" onClick={handleDisconnect} disabled={loading}>
              Disconnect
            </button>
          </>
        ) : (
          <>
            <button className="account-primary-btn stripe" onClick={handleLinkExisting} disabled={loading}>
              {loading ? "Redirecting…" : "Link existing account"}
            </button>
            <button className="account-secondary-btn" onClick={handleSignup} disabled={loading}>
              Create account
            </button>
          </>
        )}
      </div>
    </article>
  );
}
