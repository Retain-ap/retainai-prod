import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  FaChartPie,
  FaClipboardList,
  FaCog,
  FaHeartbeat,
  FaSearch,
  FaShieldAlt,
  FaUsers,
} from "react-icons/fa";
import { apiUrl } from "../apiBase";
import "./product-system.css";

async function ownerRequest(path, options = {}) {
  const response = await fetch(apiUrl(`owner/${path}`), {
    credentials: "include",
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function when(value) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function IntegrationDots({ integrations = {} }) {
  return (
    <div style={{ display: "flex", gap: 5 }}>
      {Object.entries(integrations).map(([key, connected]) => (
        <span
          key={key}
          title={`${key}: ${connected ? "connected" : "not connected"}`}
          style={{
            width: 9,
            height: 9,
            borderRadius: "50%",
            background: connected ? "var(--ra-green)" : "rgba(255,255,255,.16)",
          }}
        />
      ))}
    </div>
  );
}

export default function OwnerConsole() {
  const [tab, setTab] = useState("overview");
  const [overview, setOverview] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [queue, setQueue] = useState([]);
  const [health, setHealth] = useState(null);
  const [audit, setAudit] = useState([]);
  const [features, setFeatures] = useState({});
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [summary, accountData, queueData, healthData, auditData, featureData] =
        await Promise.all([
          ownerRequest("overview"),
          ownerRequest("accounts"),
          ownerRequest("support-queue"),
          ownerRequest("health"),
          ownerRequest("audit"),
          ownerRequest("features"),
        ]);
      setOverview(summary);
      setAccounts(accountData.accounts || []);
      setQueue(queueData.queue || []);
      setHealth(healthData);
      setAudit(auditData.audit || []);
      setFeatures(featureData.features || {});
    } catch (requestError) {
      setError(requestError.message || "Could not load the owner console.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filteredAccounts = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return accounts;
    return accounts.filter((item) =>
      `${item.business} ${item.name} ${item.email} ${item.status}`.toLowerCase().includes(needle)
    );
  }, [accounts, query]);

  async function accountAction(email, action, extra = {}) {
    setBusy(`${email}:${action}`);
    setError("");
    try {
      await ownerRequest(`accounts/${encodeURIComponent(email)}/action`, {
        method: "POST",
        body: JSON.stringify({ action, ...extra }),
      });
      await load();
    } catch (requestError) {
      setError(requestError.message || "The account action failed.");
    } finally {
      setBusy("");
    }
  }

  async function permanentlyDeleteAccount(email) {
    const confirmation = window.prompt(
      `Permanent deletion removes the account, team access, and CRM contacts. Type ${email} to confirm.`
    );
    if (confirmation !== email) return;
    await accountAction(email, "delete", { confirmation });
  }

  async function toggleFeature(key, enabled) {
    setBusy(`feature:${key}`);
    try {
      const data = await ownerRequest("features", {
        method: "POST",
        body: JSON.stringify({ key, enabled }),
      });
      setFeatures(data.features || {});
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  const tabs = [
    ["overview", "Overview", <FaChartPie />],
    ["accounts", "Customer Accounts", <FaUsers />],
    ["success", "Success Queue", <FaClipboardList />],
    ["health", "System Health", <FaHeartbeat />],
    ["audit", "Audit Log", <FaShieldAlt />],
    ["features", "Feature Controls", <FaCog />],
  ];

  return (
    <div className="product-page">
      <header className="product-hero">
        <div>
          <div className="product-eyebrow">Platform owner</div>
          <h1>RetainAI Command Centre</h1>
          <p>Customer growth, account health, platform readiness and sensitive owner actions in one secured workspace.</p>
        </div>
        <button className="product-button" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh data"}
        </button>
      </header>

      <div className="product-tabs" role="tablist" aria-label="Owner console">
        {tabs.map(([key, label, icon]) => (
          <button key={key} className={`product-tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
            {icon} {label}
          </button>
        ))}
      </div>

      {error && <div className="product-card" style={{ marginTop: 18, color: "var(--ra-red)" }}>{error}</div>}

      {tab === "overview" && overview && (
        <>
          <div className="metric-grid">
            <div className="metric-card"><span>Total accounts</span><strong>{overview.accounts_total}</strong><small>+{overview.recent_signups} this week</small></div>
            <div className="metric-card"><span>Active customers</span><strong>{overview.active_accounts}</strong><small>{overview.trials} trials in progress</small></div>
            <div className="metric-card"><span>Estimated MRR</span><strong>${overview.estimated_mrr}</strong><small>Based on active standard plans</small></div>
            <div className="metric-card"><span>Contacts managed</span><strong>{overview.contacts_total}</strong><small>Across all customer workspaces</small></div>
          </div>
          <div className="product-grid">
            <section className="product-card">
              <div className="product-card-header"><div><h2>Platform attention</h2><p className="product-card-copy">Accounts requiring an owner decision.</p></div></div>
              <div className="insight-list">
                <div className="insight-row"><span>Past due</span><strong>{overview.past_due}</strong></div>
                <div className="insight-row"><span>Suspended</span><strong>{overview.suspended}</strong></div>
                <div className="insight-row"><span>Success queue</span><strong>{queue.length}</strong></div>
              </div>
            </section>
            <section className="product-card">
              <div className="product-card-header"><div><h2>Connected ecosystem</h2><p className="product-card-copy">Customer integration adoption.</p></div></div>
              <div className="insight-list">
                {["whatsapp", "google", "stripe"].map((key) => (
                  <div className="insight-row" key={key}><span style={{ textTransform: "capitalize" }}>{key}</span><strong>{overview.integrations?.[key] || 0}</strong></div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}

      {tab === "accounts" && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header">
            <div><h2>Customer Accounts</h2><p className="product-card-copy">Search, diagnose and safely manage RetainAI customers.</p></div>
            <div style={{ width: 300, maxWidth: "100%", position: "relative" }}>
              <FaSearch style={{ position: "absolute", left: 12, top: 13, color: "var(--ra-muted)" }} />
              <input className="product-input" style={{ paddingLeft: 36 }} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search accounts…" />
            </div>
          </div>
          <div className="owner-table-wrap">
            <table className="owner-table">
              <thead><tr><th>Customer</th><th>Status</th><th>Activity</th><th>Workspace</th><th>Integrations</th><th>Owner actions</th></tr></thead>
              <tbody>
                {filteredAccounts.map((account) => (
                  <tr key={account.email}>
                    <td><strong>{account.business || account.name || "Unnamed business"}</strong><small>{account.email}</small></td>
                    <td><span className={`status-pill ${account.status}`}>{account.status.replaceAll("_", " ")}</span><small>{account.plan}</small></td>
                    <td><strong>{when(account.last_login)}</strong><small>Last login</small></td>
                    <td><strong>{account.lead_count} contacts</strong><small>{account.team_count} teammates</small></td>
                    <td><IntegrationDots integrations={account.integrations} /></td>
                    <td>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {account.status === "suspended" ? (
                          <button className="product-button" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "reactivate")}>Reactivate</button>
                        ) : (
                          <button className="product-button danger" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "suspend")}>Suspend</button>
                        )}
                        <button className="product-button" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "extend_trial", { days: 7 })}>+7 trial days</button>
                        <button className="product-button" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "archive")}>Archive</button>
                        <button className="product-button danger" disabled={Boolean(busy)} onClick={() => permanentlyDeleteAccount(account.email)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "success" && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header"><div><h2>Customer Success Queue</h2><p className="product-card-copy">Proactively help customers before they need to contact support.</p></div></div>
          <div className="insight-list">
            {queue.map((item) => (
              <div className="insight-row" key={item.email}>
                <div className="insight-row-main"><strong>{item.business || item.email}</strong><small>{item.reasons.join(" · ")}</small></div>
                <span className={`status-pill ${item.status}`}>{item.status.replaceAll("_", " ")}</span>
              </div>
            ))}
            {!queue.length && !loading && <div className="insight-row"><div className="insight-row-main"><strong>No proactive support items</strong><small>Every account meets the current success checks.</small></div></div>}
          </div>
        </section>
      )}

      {tab === "health" && health && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header"><div><h2>System Health</h2><p className="product-card-copy">Configuration readiness without exposing secret values.</p></div><span className={`status-pill ${health.ok ? "active" : "past_due"}`}>{health.ok ? "All ready" : "Needs attention"}</span></div>
          <div className="system-check-grid">
            {Object.entries(health.checks || {}).map(([key, ok]) => (
              <div className={`system-check ${ok ? "ok" : "missing"}`} key={key}>
                <strong>{key.replaceAll("_", " ")}</strong><span>{ok ? "Configured" : "Missing configuration"}</span>
              </div>
            ))}
          </div>
          {health.deployment && <p className="product-card-copy">Deployment revision: <code>{health.deployment}</code></p>}
        </section>
      )}

      {tab === "audit" && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header"><div><h2>Owner Audit Log</h2><p className="product-card-copy">A permanent record of sensitive platform actions.</p></div></div>
          <div className="owner-table-wrap">
            <table className="owner-table">
              <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
              <tbody>{audit.map((row) => <tr key={row.id}><td>{when(row.timestamp)}</td><td>{row.actor}</td><td>{row.action.replaceAll("_", " ")}</td><td>{row.target || "Platform"}</td><td><code>{JSON.stringify(row.details || {})}</code></td></tr>)}</tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "features" && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header"><div><h2>Feature Controls</h2><p className="product-card-copy">Release capabilities gradually without redeploying the app.</p></div></div>
          <div className="insight-list">
            {[
              ["retention_briefing", "Retention intelligence"],
              ["revenue_opportunities", "Revenue opportunities"],
              ["smart_playbooks", "Smart playbooks"],
              ["weekly_reports", "Weekly business reports"],
            ].map(([key, label]) => (
              <div className="insight-row" key={key}>
                <div className="insight-row-main"><strong>{label}</strong><small>{key}</small></div>
                <button className={`product-button ${features[key] ? "primary" : ""}`} disabled={busy === `feature:${key}`} onClick={() => toggleFeature(key, !features[key])}>{features[key] ? "Enabled" : "Disabled"}</button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
