import React, { useMemo, useState } from "react";
import {
  FaBolt,
  FaBullseye,
  FaChartLine,
  FaHeartbeat,
  FaInbox,
  FaMagic,
  FaRegClock,
  FaUsers,
} from "react-icons/fa";
import "./product-system.css";

const DAY = 24 * 60 * 60 * 1000;

const PLAYBOOKS = [
  { key: "winback", name: "Win back inactive customers", copy: "A thoughtful re-engagement sequence for customers who have gone quiet.", icon: <FaHeartbeat /> },
  { key: "rebook", name: "Smart rebooking", copy: "Follow up when each customer is most likely to need their next service.", icon: <FaRegClock /> },
  { key: "no_show", name: "Reduce no-shows", copy: "Confirm appointments and send a timely reminder before the booking.", icon: <FaBolt /> },
  { key: "reviews", name: "Request customer reviews", copy: "Ask happy customers for feedback after a successful appointment.", icon: <FaMagic /> },
  { key: "birthday", name: "Birthday outreach", copy: "Create a personal moment with a birthday message or offer.", icon: <FaBullseye /> },
  { key: "invoice", name: "Recover unpaid invoices", copy: "Send friendly reminders without making the relationship feel transactional.", icon: <FaChartLine /> },
];

function dateFromLead(lead) {
  const raw =
    lead.last_inbound_at ||
    lead.last_outbound_at ||
    lead.last_contacted ||
    lead.last_contact ||
    lead.updated_at ||
    lead.createdAt ||
    lead.created_at;
  const parsed = raw ? new Date(raw) : null;
  return parsed && !Number.isNaN(parsed.getTime()) ? parsed : null;
}

function healthFor(lead) {
  const last = dateFromLead(lead);
  const days = last ? Math.max(0, Math.floor((Date.now() - last.getTime()) / DAY)) : 120;
  const spend = Number(lead.total_spend || lead.lifetime_value || lead.value || 0);
  let score = Math.max(10, 100 - Math.min(days, 100));
  if (lead.email) score += 4;
  if (lead.phone || lead.phone_number) score += 4;
  if (String(lead.status || "").toLowerCase().includes("vip")) score += 12;
  score = Math.min(100, score);
  let label = "Healthy";
  let kind = "healthy";
  if (days > 90) { label = "Inactive"; kind = "inactive"; }
  else if (score < 46) { label = "At risk"; kind = "risk"; }
  else if (score < 70) { label = "Needs attention"; kind = "attention"; }
  if (spend >= 1000 && score >= 70) { label = "VIP"; kind = "vip"; }
  return { score, label, kind, days, last, spend };
}

function leadName(lead) {
  return lead.name || [lead.first_name, lead.last_name].filter(Boolean).join(" ") || lead.email || "Unnamed customer";
}

function money(value) {
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(value || 0);
}

function HealthPill({ health }) {
  return <span className={`health-pill ${health.kind}`}>{health.label} · {health.score}</span>;
}

export default function RetentionCommandCenter({ leads = [], appointments = [], onOpenAutomations, onOpenMessages }) {
  const [tab, setTab] = useState("briefing");
  const [timelineLead, setTimelineLead] = useState(null);

  const enriched = useMemo(
    () => leads.map((lead) => ({ lead, health: healthFor(lead) })).sort((a, b) => a.health.score - b.health.score),
    [leads]
  );
  const atRisk = enriched.filter((item) => ["risk", "inactive"].includes(item.health.kind));
  const needsAttention = enriched.filter((item) => item.health.kind === "attention");
  const healthy = enriched.filter((item) => ["healthy", "vip"].includes(item.health.kind));
  const opportunities = enriched
    .filter((item) => item.health.days >= 21)
    .map((item) => ({
      ...item,
      reason: item.health.days > 90 ? "Win-back opportunity" : "Likely ready to rebook",
      value: Number(item.lead.next_value || item.lead.average_sale || item.lead.value || 75),
    }));
  const opportunityValue = opportunities.reduce((sum, item) => sum + item.value, 0);
  const pulse = leads.length
    ? Math.round(enriched.reduce((sum, item) => sum + item.health.score, 0) / enriched.length)
    : 0;

  const upcoming = (appointments || []).filter((item) => {
    const raw = item.appointment_time || item.start || item.date;
    const date = raw ? new Date(raw) : null;
    return date && date.getTime() >= Date.now() && date.getTime() <= Date.now() + 7 * DAY;
  });

  const tabs = [
    ["briefing", "Daily Briefing", <FaBolt />],
    ["inbox", "Action Inbox", <FaInbox />],
    ["opportunities", "Revenue Opportunities", <FaBullseye />],
    ["customers", "Customer Health", <FaUsers />],
    ["playbooks", "Playbooks", <FaMagic />],
    ["pulse", "Business Pulse", <FaChartLine />],
  ];

  return (
    <div className="product-page">
      <header className="product-hero">
        <div>
          <div className="product-eyebrow">Retention intelligence</div>
          <h1>Good morning. Here’s what needs attention.</h1>
          <p>RetainAI has prioritized your customer relationships, upcoming revenue and important follow-ups.</p>
        </div>
        <button className="product-button primary" onClick={() => onOpenMessages?.()}>
          <FaInbox /> Open messages
        </button>
      </header>

      <div className="product-tabs" role="tablist" aria-label="Retention intelligence">
        {tabs.map(([key, label, icon]) => (
          <button key={key} className={`product-tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
            {icon} {label}
          </button>
        ))}
      </div>

      <div className="metric-grid">
        <div className="metric-card"><span>Business pulse</span><strong>{pulse || "—"}</strong><small>Average relationship health</small></div>
        <div className="metric-card"><span>Needs attention</span><strong>{atRisk.length + needsAttention.length}</strong><small>Relationships to protect</small></div>
        <div className="metric-card"><span>Potential revenue</span><strong>{money(opportunityValue)}</strong><small>Estimated rebooking value</small></div>
        <div className="metric-card"><span>Next 7 days</span><strong>{upcoming.length}</strong><small>Upcoming appointments</small></div>
      </div>

      {tab === "briefing" && (
        <div className="product-grid">
          <section className="product-card">
            <div className="product-card-header"><div><h2>Today’s priorities</h2><p className="product-card-copy">The highest-impact actions to take now.</p></div></div>
            <div className="insight-list">
              <div className="insight-row"><div className="insight-row-main"><strong>{atRisk.length} customers are at risk</strong><small>Reach out before these relationships go cold.</small></div><button className="product-button" onClick={() => setTab("customers")}>Review</button></div>
              <div className="insight-row"><div className="insight-row-main"><strong>{opportunities.length} rebooking opportunities</strong><small>Estimated value {money(opportunityValue)}.</small></div><button className="product-button" onClick={() => setTab("opportunities")}>Open</button></div>
              <div className="insight-row"><div className="insight-row-main"><strong>{upcoming.length} appointments this week</strong><small>Confirm important bookings and reduce no-shows.</small></div><button className="product-button" onClick={() => onOpenAutomations?.("no_show")}>Automate</button></div>
            </div>
          </section>
          <section className="product-card">
            <div className="product-card-header"><div><h2>AI recommendation</h2><p className="product-card-copy">Based on the current customer mix.</p></div></div>
            <div className="pulse-score"><div><strong>{pulse || "—"}</strong><span>health score</span></div></div>
            <p style={{ color: "var(--ra-muted)", lineHeight: 1.65, textAlign: "center" }}>
              {atRisk.length
                ? `Start with the ${Math.min(atRisk.length, 5)} most at-risk customers, then activate the smart rebooking playbook for consistent follow-up.`
                : "Your relationships look healthy. Focus on review requests and smart rebooking to maintain momentum."}
            </p>
          </section>
        </div>
      )}

      {tab === "inbox" && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header"><div><h2>AI Action Inbox</h2><p className="product-card-copy">One prioritized place for work that needs a human decision.</p></div></div>
          <div className="insight-list">
            {[...atRisk, ...needsAttention].slice(0, 20).map(({ lead, health }) => (
              <div className="insight-row" key={lead.id || lead.email}>
                <div className="insight-row-main"><strong>Follow up with {leadName(lead)}</strong><small>{health.days >= 120 ? "No recent activity is recorded." : `Last activity approximately ${health.days} days ago.`}</small></div>
                <HealthPill health={health} />
                <button className="product-button primary" onClick={() => onOpenMessages?.(lead)}>Draft reply</button>
              </div>
            ))}
            {!atRisk.length && !needsAttention.length && <div className="insight-row"><div className="insight-row-main"><strong>You’re caught up</strong><small>No relationships currently need urgent attention.</small></div></div>}
          </div>
        </section>
      )}

      {tab === "opportunities" && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header"><div><h2>Revenue Opportunities</h2><p className="product-card-copy">Customers most likely to benefit from a timely follow-up.</p></div><strong>{money(opportunityValue)}</strong></div>
          <div className="insight-list">
            {opportunities.slice(0, 30).map(({ lead, health, reason, value }) => (
              <div className="insight-row" key={lead.id || lead.email}>
                <div className="insight-row-main"><strong>{leadName(lead)}</strong><small>{reason} · {health.days} days since activity</small></div>
                <strong>{money(value)}</strong>
                <button className="product-button" onClick={() => setTimelineLead({ lead, health })}>View relationship</button>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "customers" && (
        <section className="product-card" style={{ marginTop: 18 }}>
          <div className="product-card-header"><div><h2>Customer Health</h2><p className="product-card-copy">Transparent scores based on relationship recency and customer data quality.</p></div></div>
          <div className="insight-list">
            {enriched.map(({ lead, health }) => (
              <div className="insight-row" key={lead.id || lead.email}>
                <div className="insight-row-main"><strong>{leadName(lead)}</strong><small>{health.last ? `Last activity ${health.last.toLocaleDateString()}` : "No activity recorded"}</small></div>
                <HealthPill health={health} />
                <button className="product-button" onClick={() => setTimelineLead({ lead, health })}>Timeline</button>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "playbooks" && (
        <div className="product-grid">
          {PLAYBOOKS.map((playbook) => (
            <section className="product-card" key={playbook.key}>
              <div className="product-eyebrow">{playbook.icon} Ready-made playbook</div>
              <h3 style={{ marginTop: 12 }}>{playbook.name}</h3>
              <p style={{ color: "var(--ra-muted)", lineHeight: 1.6 }}>{playbook.copy}</p>
              <button className="product-button primary" onClick={() => onOpenAutomations?.(playbook.key)}>Use this playbook</button>
            </section>
          ))}
        </div>
      )}

      {tab === "pulse" && (
        <div className="product-grid">
          <section className="product-card">
            <div className="pulse-score"><div><strong>{pulse || "—"}</strong><span>business pulse</span></div></div>
            <p style={{ color: "var(--ra-muted)", textAlign: "center", lineHeight: 1.65 }}>
              {pulse >= 80 ? "Customer relationships are strong. Keep your follow-up rhythm consistent." : pulse >= 60 ? "Your business is stable, with a few relationships that need attention." : "There is meaningful retention opportunity. Start with your action inbox today."}
            </p>
          </section>
          <section className="product-card">
            <div className="product-card-header"><h2>Relationship mix</h2></div>
            <div className="insight-list">
              <div className="insight-row"><span>Healthy and VIP</span><strong>{healthy.length}</strong></div>
              <div className="insight-row"><span>Needs attention</span><strong>{needsAttention.length}</strong></div>
              <div className="insight-row"><span>At risk or inactive</span><strong>{atRisk.length}</strong></div>
              <div className="insight-row"><span>Total customers</span><strong>{leads.length}</strong></div>
            </div>
          </section>
        </div>
      )}

      {timelineLead && (
        <div className="command-overlay" onMouseDown={() => setTimelineLead(null)}>
          <section className="command-panel" style={{ maxHeight: "74vh", overflow: "auto" }} onMouseDown={(event) => event.stopPropagation()}>
            <div className="product-card-header">
              <div><div className="product-eyebrow">Relationship timeline</div><h2 style={{ marginTop: 8 }}>{leadName(timelineLead.lead)}</h2></div>
              <button className="product-button" onClick={() => setTimelineLead(null)}>Close</button>
            </div>
            <HealthPill health={timelineLead.health} />
            <p style={{ color: "var(--ra-muted)", lineHeight: 1.65 }}>
              {leadName(timelineLead.lead)} has {timelineLead.health.days >= 120 ? "no recent recorded activity" : `not had recorded activity for approximately ${timelineLead.health.days} days`}. Their preferred contact information is {timelineLead.lead.phone || timelineLead.lead.email || "not complete"}.
            </p>
            <div className="timeline">
              {[
                ["Customer added", timelineLead.lead.createdAt || timelineLead.lead.created_at],
                ["Last outbound message", timelineLead.lead.last_outbound_at || timelineLead.lead.last_contacted],
                ["Last customer reply", timelineLead.lead.last_inbound_at || timelineLead.lead.last_reply_at],
                ["Record updated", timelineLead.lead.updated_at],
              ].filter(([, date]) => date).sort((a, b) => new Date(b[1]) - new Date(a[1])).map(([label, date]) => (
                <div className="timeline-item" key={`${label}-${date}`}><strong>{label}</strong><small>{new Date(date).toLocaleString()}</small></div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
