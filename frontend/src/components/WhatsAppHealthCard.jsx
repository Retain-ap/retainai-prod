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

      const [healthResponse, inboundResponse] = await Promise.all([healthRequest, inboundRequest]);
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
      </div>

      <div className="account-card-actions">
        <button className="account-primary-btn whatsapp" onClick={refresh} disabled={loading}>
          <FaSyncAlt className={loading ? "account-spin" : ""} />
          {loading ? "Checking…" : "Run connection check"}
        </button>
      </div>
    </article>
  );
}