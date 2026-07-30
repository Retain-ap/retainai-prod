import React, { useCallback, useEffect, useMemo, useState } from "react";
import { FaSyncAlt } from "react-icons/fa";
import { SiWhatsapp } from "react-icons/si";
import { apiUrl } from "../apiBase";

function formatWhen(value) {
  if (!value) return "Not seen yet";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

export default function WhatsAppHealthCard({ user }) {
  const userEmail = String(user?.email || "").trim().toLowerCase();
  const [health, setHealth] = useState(null);
  const [inbound, setInbound] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [connection, setConnection] = useState(null);
  const [form, setForm] = useState({
    access_token: "",
    phone_id: "",
    waba_id: "",
    business_number: "",
  });
  const canManage = user?.role === "owner" || user?.canEditBusiness || user?.platformOwner;

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const healthRequest = fetch(apiUrl("whatsapp/health"), {
        credentials: "include",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });

      const inboundRequest = userEmail
        ? fetch(
            apiUrl(`whatsapp/inbound-health?user_email=${encodeURIComponent(userEmail)}&_=${Date.now()}`),
            {
              credentials: "include",
              cache: "no-store",
              headers: {
                Accept: "application/json",
                "X-User-Email": userEmail,
              },
            }
          )
        : Promise.resolve(null);

      const connectionRequest = fetch(apiUrl("integrations/whatsapp"), {
        credentials: "include",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      const [healthResponse, inboundResponse, connectionResponse] = await Promise.all([
        healthRequest,
        inboundRequest,
        connectionRequest,
      ]);
      const healthData = await healthResponse.json().catch(() => ({}));
      if (!healthResponse.ok) {
        throw new Error(healthData?.error || `WhatsApp health failed (${healthResponse.status})`);
      }

      let inboundData = null;
      if (inboundResponse) {
        inboundData = await inboundResponse.json().catch(() => ({}));
        if (!inboundResponse.ok) {
          throw new Error(inboundData?.error || `Inbound health failed (${inboundResponse.status})`);
        }
      }

      setHealth(healthData);
      setInbound(inboundData);
      const connectionData = await connectionResponse.json().catch(() => ({}));
      if (connectionResponse.ok) {
        setConnection(connectionData);
        setForm((current) => ({
          ...current,
          phone_id: connectionData.phone_id || "",
          waba_id: connectionData.waba_id || "",
          business_number: connectionData.business_number || "",
        }));
      }
    } catch (err) {
      setHealth(null);
      setInbound(null);
      setError(err?.message || "Could not check WhatsApp status.");
    } finally {
      setLoading(false);
    }
  }, [userEmail]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const connected = useMemo(
    () => Boolean(health?.has_token && health?.has_phone_id && health?.has_waba_id),
    [health]
  );

  const webhookSeen = Boolean(inbound?.webhook_last_seen_at || health?.webhook_last_seen_at);
  const matchedInboundSeen = Boolean(
    inbound?.last_matched_inbound_at || health?.last_matched_inbound_at
  );
  const unmatchedCount = Number(inbound?.unmatched_count ?? health?.unmatched_inbound_count ?? 0);
  const ready = connected && webhookSeen && unmatchedCount === 0;

  const saveConnection = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const response = await fetch(apiUrl("integrations/whatsapp"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(form),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || "Could not connect WhatsApp.");
      setForm((current) => ({ ...current, access_token: "" }));
      setEditing(false);
      await refresh();
    } catch (err) {
      setError(err?.message || "Could not connect WhatsApp.");
    } finally {
      setSaving(false);
    }
  };

  const usePlatformDefault = async () => {
    if (!window.confirm("Remove this workspace connection and return to the platform default?")) return;
    setSaving(true);
    setError("");
    try {
      const response = await fetch(apiUrl("integrations/whatsapp"), {
        method: "DELETE",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || "Could not remove the connection.");
      setEditing(false);
      setForm({ access_token: "", phone_id: "", waba_id: "", business_number: "" });
      await refresh();
    } catch (err) {
      setError(err?.message || "Could not remove the connection.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className={`account-card account-card-whatsapp${ready ? " is-connected" : ""}`}>
      <div className="account-card-top">
        <div className="account-brand-icon whatsapp" aria-hidden="true">
          <SiWhatsapp />
        </div>
        <span className={`account-status-badge ${ready ? "connected" : "attention"}`}>
          <span />
          {loading ? "Checking" : ready ? "Connected" : "Check setup"}
        </span>
      </div>

      <div className="account-card-copy">
        <h3>WhatsApp Business</h3>
        <p>Send approved templates and receive customer replies directly inside RetainAI.</p>
      </div>

      <div className="account-card-content">
        <div className="account-check-list">
          <div className={health?.has_token ? "ready" : "missing"}>
            <span /> API access token
          </div>
          <div className={health?.has_phone_id ? "ready" : "missing"}>
            <span /> Phone number ID
          </div>
          <div className={health?.has_waba_id ? "ready" : "missing"}>
            <span /> Business account ID
          </div>
          <div className={webhookSeen ? "ready" : "missing"}>
            <span /> Webhook receiving events
          </div>
          <div className={matchedInboundSeen ? "ready" : "missing"}>
            <span /> Customer reply matched to a lead
          </div>
        </div>

        <div className="account-id-row">
          <span>Last webhook event</span>
          <code>{formatWhen(inbound?.webhook_last_seen_at || health?.webhook_last_seen_at)}</code>
        </div>

        <div className="account-id-row">
          <span>Last matched reply</span>
          <code>{formatWhen(inbound?.last_matched_inbound_at || health?.last_matched_inbound_at)}</code>
        </div>

        {health?.default_template ? (
          <div className="account-id-row">
            <span>Default template</span>
            <code>{health.default_template}</code>
          </div>
        ) : null}

        <div className="account-id-row">
          <span>Credential scope</span>
          <code>{health?.credential_source === "workspace" ? "This workspace" : "Platform default"}</code>
        </div>

        {unmatchedCount > 0 ? (
          <div className="account-inline-message error">
            {unmatchedCount} inbound repl{unmatchedCount === 1 ? "y was" : "ies were"} received but could not be matched to a lead. Make sure the lead phone number includes the correct country code.
          </div>
        ) : null}

        {!matchedInboundSeen && webhookSeen && !loading ? (
          <div className="account-inline-message">
            Delivery events are reaching RetainAI, but no customer reply has matched a lead yet.
          </div>
        ) : null}

        {error ? <div className="account-inline-message error">{error}</div> : null}

        {editing && canManage ? (
          <form onSubmit={saveConnection} className="whatsapp-connection-form">
            <label>
              Meta access token
              <input
                type="password"
                autoComplete="new-password"
                value={form.access_token}
                onChange={(event) => setForm({ ...form, access_token: event.target.value })}
                placeholder={connection?.has_workspace_token ? "Leave blank to keep saved token" : "Permanent system-user token"}
              />
            </label>
            <label>
              Phone number ID
              <input
                value={form.phone_id}
                onChange={(event) => setForm({ ...form, phone_id: event.target.value })}
                required
              />
            </label>
            <label>
              WhatsApp business account ID
              <input
                value={form.waba_id}
                onChange={(event) => setForm({ ...form, waba_id: event.target.value })}
                placeholder="Detected automatically when possible"
              />
            </label>
            <label>
              Display phone number
              <input
                value={form.business_number}
                onChange={(event) => setForm({ ...form, business_number: event.target.value })}
                placeholder="+1 416 555 0123"
              />
            </label>
            <div className="whatsapp-connection-actions">
              <button className="account-primary-btn whatsapp" type="submit" disabled={saving}>
                {saving ? "Validating..." : "Validate and save"}
              </button>
              <button className="account-secondary-btn" type="button" onClick={() => setEditing(false)}>
                Cancel
              </button>
              {connection?.source === "workspace" ? (
                <button className="account-secondary-btn" type="button" onClick={usePlatformDefault} disabled={saving}>
                  Use platform default
                </button>
              ) : null}
            </div>
          </form>
        ) : null}
      </div>

      <div className="account-card-actions">
        <button className="account-primary-btn whatsapp" onClick={refresh} disabled={loading}>
          <FaSyncAlt className={loading ? "account-spin" : ""} />
          {loading ? "Checking..." : "Run connection check"}
        </button>
        {canManage ? (
          <button className="account-secondary-btn" onClick={() => setEditing((value) => !value)}>
            {editing ? "Close setup" : "Manage workspace connection"}
          </button>
        ) : null}
      </div>
    </article>
  );
}
