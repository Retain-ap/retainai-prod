import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  FaChartPie,
  FaClipboardList,
  FaCog,
  FaDatabase,
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
  const [backups, setBackups] = useState([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [integrationFilter, setIntegrationFilter] = useState("all");
  const [selectedEmail, setSelectedEmail] = useState("");
  const [supportNote, setSupportNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [summary, accountData, queueData, healthData, auditData, featureData, backupData] =
        await Promise.all([
          ownerRequest("overview"),
          ownerRequest("accounts"),
          ownerRequest("support-queue"),
          ownerRequest("health"),
          ownerRequest("audit"),
          ownerRequest("features"),
          ownerRequest("backups"),
        ]);
      setOverview(summary);
      setAccounts(accountData.accounts || []);
      setQueue(queueData.queue || []);
      setHealth(healthData);
      setAudit(auditData.audit || []);
      setFeatures(featureData.features || {});
      setBackups(backupData.backups || []);
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
    return accounts.filter((item) => {
      const matchesQuery =
        !needle ||
        `${item.business} ${item.name} ${item.email} ${item.status}`
          .toLowerCase()
          .includes(needle);
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "at_risk"
          ? Boolean(item.risk_reasons?.length)
          : item.status === statusFilter);
      const matchesIntegration =
        integrationFilter === "all" ||
        Boolean(item.integrations?.[integrationFilter]);
      return matchesQuery && matchesStatus && matchesIntegration;
    });
  }, [accounts, query, statusFilter, integrationFilter]);

  const selectedAccount = useMemo(
    () => accounts.find((item) => item.email === selectedEmail) || null,
    [accounts, selectedEmail]
  );

  useEffect(() => {
    setSupportNote(selectedAccount?.support_note || "");
  }, [selectedAccount]);

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
      `This permanently removes the account after you have exported its data. Type DELETE ${email} to confirm.`
    );
    if (confirmation !== `DELETE ${email}`) return;
    await accountAction(email, "delete_now", { confirmation });
  }

  async function scheduleDeletion(email) {
    const confirmation = window.prompt(
      `Schedule this workspace for deletion in 14 days? Type ${email} to confirm. You can cancel during the recovery window.`
    );
    if (confirmation !== email) return;
    await accountAction(email, "schedule_delete");
  }

  async function exportAccount(email) {
    setBusy(`${email}:export`);
    setError("");
    try {
      const response = await fetch(apiUrl(`owner/accounts/${encodeURIComponent(email)}/export`), {
        credentials: "include",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Account export failed.");
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = `retainai-${email}-export.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
    } catch (requestError) {
      setError(requestError.message || "Account export failed.");
    } finally {
      setBusy("");
    }
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

  async function saveSupportNote() {
    if (!selectedAccount) return;
    await accountAction(selectedAccount.email, "support_note", { note: supportNote });
  }

  async function createBackup() {
    setBusy("backup:create");
    setError("");
    try {
      const data = await ownerRequest("backups", { method: "POST", body: JSON.stringify({}) });
      setBackups(data.backups || []);
    } catch (requestError) {
      setError(requestError.message || "Backup creation failed.");
    } finally {
      setBusy("");
    }
  }

  async function downloadBackup(name) {
    setBusy(`backup:${name}`);
    try {
      const response = await fetch(apiUrl(`owner/backups/${encodeURIComponent(name)}`), {
        credentials: "include",
      });
      if (!response.ok) throw new Error("Backup download failed.");
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
    } catch (requestError) {
      setError(requestError.message || "Backup download failed.");
    } finally {
      setBusy("");
    }
  }

  const tabs = [
    ["overview", "Overview", <FaChartPie />],
    ["accounts", "Customer Accounts", <FaUsers />],
    ["success", "Success Queue", <FaClipboardList />],
    ["health", "System Health", <FaHeartbeat />],
    ["backups", "Backups", <FaDatabase />],
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
            <div className="metric-card"><span>Trials in progress</span><strong>{overview.trials}</strong><small>Potential customers in evaluation</small></div>
            <div className="metric-card"><span>Contacts managed</span><strong>{overview.contacts_total}</strong><small>Across all customer workspaces</small></div>
            <div className="metric-card"><span>Onboarded</span><strong>{overview.onboarded_accounts}</strong><small>{overview.average_onboarding}% average completion</small></div>
            <div className="metric-card"><span>At-risk accounts</span><strong>{overview.at_risk_accounts}</strong><small>Need proactive attention</small></div>
            <div className="metric-card"><span>Recorded MRR</span><strong>{Object.keys(overview.recorded_mrr || {}).length ? Object.entries(overview.recorded_mrr).map(([currency, amount]) => `${currency} $${amount}`).join(" · ") : "Waiting for Stripe"}</strong><small>Captured from subscription events</small></div>
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
            <div className="owner-filter-bar">
              <div style={{ minWidth: 240, position: "relative" }}>
                <FaSearch style={{ position: "absolute", left: 12, top: 13, color: "var(--ra-muted)" }} />
                <input className="product-input" style={{ paddingLeft: 36 }} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search accounts…" />
              </div>
              <select className="product-input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Filter by account status">
                <option value="all">All statuses</option>
                <option value="at_risk">At risk</option>
                <option value="active">Active</option>
                <option value="trial">Trial</option>
                <option value="pending_payment">Pending payment</option>
                <option value="past_due">Past due</option>
                <option value="suspended">Suspended</option>
                <option value="deletion_pending">Deletion pending</option>
              </select>
              <select className="product-input" value={integrationFilter} onChange={(event) => setIntegrationFilter(event.target.value)} aria-label="Filter by integration">
                <option value="all">All integrations</option>
                <option value="whatsapp">WhatsApp connected</option>
                <option value="google">Google connected</option>
                <option value="stripe">Stripe connected</option>
              </select>
            </div>
          </div>
          <div className="owner-account-summary">
            <span><strong>{filteredAccounts.length}</strong> accounts shown</span>
            <span><strong>{filteredAccounts.reduce((sum, item) => sum + Number(item.lead_count || 0), 0)}</strong> contacts</span>
            <span><strong>{filteredAccounts.filter((item) => item.risk_reasons?.length).length}</strong> need attention</span>
          </div>
          {selectedAccount && (
            <div className="owner-account-detail">
              <div className="product-card-header">
                <div>
                  <div className="product-eyebrow">Account details</div>
                  <h2>{selectedAccount.business || selectedAccount.name || selectedAccount.email}</h2>
                  <p className="product-card-copy">{selectedAccount.email} · Created {when(selectedAccount.created_at)}</p>
                </div>
                <button className="product-button" onClick={() => setSelectedEmail("")}>Close</button>
              </div>
              <div className="owner-detail-grid">
                <div><span>Status</span><strong>{selectedAccount.status.replaceAll("_", " ")}</strong></div>
                <div><span>Billing</span><strong>{String(selectedAccount.billing_status || "unknown").replaceAll("_", " ")}</strong></div>
                <div><span>Onboarding</span><strong>{selectedAccount.onboarding_score}%</strong></div>
                <div><span>Trial remaining</span><strong>{selectedAccount.trial_days_remaining || 0} days</strong></div>
                <div><span>Contacts</span><strong>{selectedAccount.lead_count}</strong></div>
                <div><span>Team</span><strong>{selectedAccount.team_count}</strong></div>
                <div><span>Email</span><strong>{selectedAccount.email_verified ? "Verified" : "Unverified"}</strong></div>
                <div><span>Recorded MRR</span><strong>{selectedAccount.subscription_mrr ? `${selectedAccount.subscription_currency} $${selectedAccount.subscription_mrr}` : "Not recorded"}</strong></div>
              </div>
              <div className="owner-risk-list">
                {selectedAccount.risk_reasons?.length
                  ? selectedAccount.risk_reasons.map((reason) => <span key={reason}>{reason}</span>)
                  : <span className="healthy">No current risk signals</span>}
              </div>
              <label className="owner-note-field">
                <span>Private owner support note</span>
                <textarea className="product-input" rows="3" maxLength="1000" value={supportNote} onChange={(event) => setSupportNote(event.target.value)} placeholder="Record follow-up context, customer needs, or an internal note…" />
              </label>
              <button className="product-button primary" disabled={Boolean(busy)} onClick={saveSupportNote}>Save private note</button>
              <button className="product-button danger" style={{ marginLeft: 8 }} disabled={Boolean(busy)} onClick={() => accountAction(selectedAccount.email, "force_logout")}>Sign out all devices</button>
            </div>
          )}
          <div className="owner-table-wrap">
            <table className="owner-table">
              <thead><tr><th>Customer</th><th>Status</th><th>Activity</th><th>Workspace</th><th>Integrations</th><th>Owner actions</th></tr></thead>
              <tbody>
                {filteredAccounts.map((account) => (
                  <tr key={account.email}>
                    <td><button className="owner-account-link" onClick={() => setSelectedEmail(account.email)}><strong>{account.business || account.name || "Unnamed business"}</strong><small>{account.email}</small></button></td>
                    <td><span className={`status-pill ${account.status}`}>{account.status.replaceAll("_", " ")}</span><small>{account.plan}</small></td>
                    <td><strong>{when(account.last_login)}</strong><small>Last login</small></td>
                    <td><strong>{account.lead_count} contacts</strong><small>{account.team_count} teammates · {account.onboarding_score}% onboarded</small></td>
                    <td><IntegrationDots integrations={account.integrations} /></td>
                    <td>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {account.status === "suspended" ? (
                          <button className="product-button" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "reactivate")}>Reactivate</button>
                        ) : (
                          <button className="product-button danger" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "suspend")}>Suspend</button>
                        )}
                        <button className="product-button" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "extend_trial", { days: 7 })}>+7 trial days</button>
                        <button className="product-button" disabled={Boolean(busy)} onClick={() => exportAccount(account.email)}>Export</button>
                        {account.status === "deletion_pending" ? (
                          <>
                            <button className="product-button" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "cancel_delete")}>Cancel deletion</button>
                            <button className="product-button danger" disabled={Boolean(busy)} onClick={() => permanentlyDeleteAccount(account.email)}>Delete now</button>
                          </>
                        ) : (
                          <>
                            <button className="product-button" disabled={Boolean(busy)} onClick={() => accountAction(account.email, "archive")}>Archive</button>
                            <button className="product-button danger" disabled={Boolean(busy)} onClick={() => scheduleDeletion(account.email)}>Schedule deletion</button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {!filteredAccounts.length && <tr><td colSpan="6"><div className="owner-empty-state"><strong>No matching accounts</strong><small>Adjust the search or filters to see more customers.</small></div></td></tr>}
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

      {tab === "backups" && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header">
            <div><h2>Verified platform backups</h2><p className="product-card-copy">Encrypted transport, integrity hashes, automatic retention and owner-only downloads. Keep an off-site copy for disaster recovery.</p></div>
            <button className="product-button primary" onClick={createBackup} disabled={Boolean(busy)}>{busy === "backup:create" ? "Creating…" : "Create backup now"}</button>
          </div>
          <div className="insight-list">
            {backups.map((backup) => (
              <div className="insight-row" key={backup.name}>
                <div className="insight-row-main"><strong>{when(backup.created_at)}</strong><small>{backup.name} · {(backup.bytes / 1024 / 1024).toFixed(2)} MB · SHA-256 {backup.sha256.slice(0, 12)}…</small></div>
                <button className="product-button" disabled={Boolean(busy)} onClick={() => downloadBackup(backup.name)}>Download</button>
              </div>
            ))}
            {!backups.length && <div className="owner-empty-state"><strong>No verified backup yet</strong><small>Create the first snapshot now. Automatic daily backups require RUN_SCHEDULER=1.</small></div>}
          </div>
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
