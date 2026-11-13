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
import {
  appointmentDateKey,
  appointmentTimeKey,
  calendarDayDistance,
  compareAppointmentToNow,
  dayKeyNow,
  getBrowserTimeZone,
  parseAppointmentDateTime,
} from "./appointmentDateTime";
import ValueReceipt from "./ValueReceipt";
import ServiceSetupPanel, { SALON_PLAYBOOKS } from "./ServiceSetupPanel";
import { dueForRebooking, rebookingSuggestions, waitingToBook } from "../rebooking";
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
  return parseAppointmentDateTime(raw);
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
  const reasons = [];
  reasons.push(last ? `${days} days since the last recorded activity` : "No recent activity is recorded");
  if (!lead.email && !(lead.phone || lead.phone_number)) reasons.push("Contact information is incomplete");
  if (String(lead.status || "").toLowerCase().includes("vip")) reasons.push("Marked as a high-value relationship");
  if (spend > 0) reasons.push(`${money(spend)} in recorded relationship value`);
  return { score, label, kind, days, last, spend, reasons };
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

function shortDay(dateKey) {
  const ms = Date.parse(`${dateKey}T00:00:00Z`);
  return Number.isFinite(ms) ? new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" }) : dateKey;
}

/** The value the owner recorded for this customer, or null. Never a made-up default. */
function recordedValue(lead) {
  for (const field of ["next_value", "average_sale", "value"]) {
    const amount = Number(lead?.[field]);
    if (Number.isFinite(amount) && amount > 0) return amount;
  }
  return null;
}

/** Factual context for a drafted follow-up, taken only from recorded visits. */
function followUpContext(rebook) {
  return `Due to rebook: last completed visit ${shortDay(rebook.lastVisit)}; usually every ${rebook.intervalDays} days.`;
}

export default function RetentionCommandCenter({ leads = [], appointments = [], user, onOpenAutomations, onOpenMessages, onUpdateLead, onOpenImports, onOpenAppointments, onDraftFollowUp, onMarkContacted }) {
  const [marking, setMarking] = useState("");
  const [actionError, setActionError] = useState("");
  const [tab, setTab] = useState("briefing");
  const [timelineLead, setTimelineLead] = useState(null);

  const enriched = useMemo(
    () => leads.map((lead) => ({ lead, health: healthFor(lead) })).sort((a, b) => a.health.score - b.health.score),
    [leads]
  );
  const atRisk = enriched.filter((item) => ["risk", "inactive"].includes(item.health.kind));
  const needsAttention = enriched.filter((item) => item.health.kind === "attention");
  const healthy = enriched.filter((item) => ["healthy", "vip"].includes(item.health.kind));
  const workspaceTimeZone = user?.timezone || getBrowserTimeZone();
  const rebooking = useMemo(
    () => rebookingSuggestions({ leads, appointments, user, today: dayKeyNow(workspaceTimeZone), timeZone: workspaceTimeZone }),
    [leads, appointments, user, workspaceTimeZone]
  );
  const salonPreset = user?.setup_preset === "salon_barber";
  const playbooks = salonPreset
    ? SALON_PLAYBOOKS.map((playbook) => ({ ...playbook, icon: PLAYBOOKS.find((item) => item.key === playbook.key)?.icon }))
    : PLAYBOOKS;
  const healthByLead = new Map(enriched.map((item) => [item.lead, item.health]));
  const withVisits = new Set(rebooking.map((item) => item.lead));
  const opportunities = [
    // Due or overdue against each customer's own completed-visit rhythm.
    ...dueForRebooking(rebooking).map((item) => ({
      lead: item.lead,
      health: healthByLead.get(item.lead) || healthFor(item.lead),
      rebook: item,
      reason: item.daysUntilDue < 0 ? `Rebooking overdue by ${-item.daysUntilDue} days` : item.daysUntilDue === 0 ? "Rebooking due today" : `Rebooking due in ${item.daysUntilDue} days`,
      value: recordedValue(item.lead),
    })),
    // No completed visit on record: only long inactivity suggests a win-back.
    ...enriched
      .filter((item) => !withVisits.has(item.lead) && item.health.days > 90)
      .map((item) => ({ ...item, reason: "Win-back: no completed visit recorded and inactive for 90+ days", value: recordedValue(item.lead) })),
  ];
  const waiting = waitingToBook(rebooking);
  // Only values the owner recorded are added up; customers without one are counted, not guessed.
  const valued = opportunities.filter((item) => item.value !== null);
  const opportunityValue = valued.reduce((sum, item) => sum + item.value, 0);
  const valueSummary = valued.length
    ? `${money(opportunityValue)} recorded for ${valued.length} of ${opportunities.length}`
    : "No customer values recorded";
  const markContacted = async (lead) => {
    setActionError("");
    setMarking(String(lead.id));
    try {
      await onMarkContacted(lead);
    } catch (error) {
      setActionError(error?.message || "The contact could not be recorded.");
    } finally {
      setMarking("");
    }
  };
  const pulse = leads.length
    ? Math.round(enriched.reduce((sum, item) => sum + item.health.score, 0) / enriched.length)
    : 0;
  const firstName = String(user?.name || user?.firstName || "")
    .trim()
    .split(/\s+/)[0];

  const upcoming = (appointments || []).filter((item) => {
    const status = String(item?.status || "").toLowerCase().replace(/-/g, "_");
    if (item?.done || item?.completed || ["cancelled", "canceled", "completed"].includes(status)) return false;
    const raw = item.appointment_time || item.start || item.date;
    const timeZone = item.timeZone || item.timezone || user?.timezone || getBrowserTimeZone();
    const dateKey = item.date || appointmentDateKey(raw, timeZone);
    const timeKey = item.time || appointmentTimeKey(raw, timeZone) || "00:00";
    const dayDistance = calendarDayDistance(dayKeyNow(timeZone), dateKey);
    return (
      Number.isFinite(dayDistance) &&
      dayDistance >= 0 &&
      dayDistance <= 7 &&
      compareAppointmentToNow(dateKey, timeKey, timeZone) >= 0
    );
  });

  const tabs = [
    ["briefing", "Daily Briefing", <FaBolt />],
    ["inbox", "Action Inbox", <FaInbox />],
    ["opportunities", "Revenue Opportunities", <FaBullseye />],
    ["customers", "Customer Health", <FaUsers />],
    ["playbooks", "Playbooks", <FaMagic />],
    ["pulse", "Business Pulse", <FaChartLine />],
    ["value", "Value Receipt", <FaHeartbeat />],
  ];

  return (
    <div className="product-page retention-overview">
      <header className="product-hero">
        <div>
          <div className="overview-live"><span /> Workspace intelligence live</div>
          <div className="product-eyebrow">Your daily command center</div>
          <h1>Good morning{firstName ? `, ${firstName}` : ""}.</h1>
          <p>Here is the clearest path to stronger relationships and more repeat revenue today.</p>
        </div>
        <button className="product-button primary" onClick={() => onOpenMessages?.()}>
          <FaInbox /> Open messages
        </button>
      </header>

      <div className="product-tabs" role="tablist" aria-label="Retention intelligence">
        {tabs.map(([key, label, icon]) => (
          <button
            key={key}
            className={`product-tab ${tab === key ? "active" : ""}`}
            onClick={() => setTab(key)}
            role="tab"
            aria-selected={tab === key}
            aria-label={label}
            title={label}
          >
            <span className="product-tab-icon" aria-hidden="true">{icon}</span>
            <span className="product-tab-label">{label}</span>
          </button>
        ))}
      </div>

      <div className="metric-grid">
        <div className="metric-card"><div className="metric-icon"><FaHeartbeat /></div><span>Business pulse</span><strong>{pulse || "—"}</strong><small>Average relationship health</small></div>
        <div className="metric-card"><div className="metric-icon attention"><FaUsers /></div><span>Needs attention</span><strong>{atRisk.length + needsAttention.length}</strong><small>Relationships to protect</small></div>
        <div className="metric-card"><div className="metric-icon opportunity"><FaChartLine /></div><span>Due to rebook</span><strong>{opportunities.length}</strong><small>{valueSummary}</small></div>
        <div className="metric-card"><div className="metric-icon schedule"><FaRegClock /></div><span>Next 7 days</span><strong>{upcoming.length}</strong><small>Upcoming appointments</small></div>
      </div>

      {tab === "briefing" && (
        <div className="product-grid">
          <ServiceSetupPanel
            preset={salonPreset ? "salon_barber" : "general"}
            leads={leads}
            appointments={appointments}
            rebooking={rebooking}
            today={dayKeyNow(workspaceTimeZone)}
            onOpenPlaybooks={() => setTab("playbooks")}
            onOpenImports={onOpenImports}
            onOpenAppointments={onOpenAppointments}
          />
          <section className="product-card">
            <div className="product-card-header"><div><h2>Today’s priorities</h2><p className="product-card-copy">The highest-impact actions to take now.</p></div></div>
            <div className="insight-list">
              <div className="insight-row"><div className="insight-row-main"><strong>{atRisk.length} customers are at risk</strong><small>Reach out before these relationships go cold.</small></div><button className="product-button" onClick={() => setTab("customers")}>Review</button></div>
              <div className="insight-row"><div className="insight-row-main"><strong>{opportunities.length} rebooking opportunities</strong><small>{waiting.length ? `${waiting.length} contacted and waiting to book. ` : ""}{valueSummary}.</small></div><button className="product-button" onClick={() => setTab("opportunities")}>Open</button></div>
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
          <div className="product-card-header"><div><h2>Due to rebook</h2><p className="product-card-copy">Rebooking dates come from each customer's completed visits. Nothing is sent automatically: draft a follow-up to review, or mark a customer contacted once you've reached them.</p></div><strong title="Values you recorded for these customers, not revenue">{valued.length ? money(opportunityValue) : "—"}</strong></div>
          {actionError && <div className="product-alert" role="alert">{actionError}</div>}
          <div className="insight-list">
            {opportunities.slice(0, 30).map(({ lead, health, reason, value, rebook }) => (
              <div className="insight-row rebook-row" key={lead.id || lead.email}>
                <div className="insight-row-main">
                  <strong>{leadName(lead)}</strong>
                  <small>{reason}{rebook ? ` · every ${rebook.intervalDays} days` : ` · ${health.days} days since activity`}</small>
                  {rebook && <ul className="rebook-reasons">{rebook.reasons.map((text) => <li key={text}>{text}</li>)}</ul>}
                </div>
                <strong title="Value you recorded for this customer">{value !== null ? money(value) : <small>No value recorded</small>}</strong>
                <div className="rebook-actions">
                  {lead.email_opt_out && <small className="rebook-note">Unsubscribed from email</small>}
                  {!lead.email_opt_out && !lead.email && <small className="rebook-note">No email address</small>}
                  {rebook && onDraftFollowUp && lead.email && !lead.email_opt_out && (
                    <button className="product-button primary" onClick={() => onDraftFollowUp(lead, followUpContext(rebook))}>Draft follow-up</button>
                  )}
                  {onMarkContacted && lead.id && (
                    <button className="product-button" disabled={marking === String(lead.id)} onClick={() => markContacted(lead)}>
                      {marking === String(lead.id) ? "Recording…" : "Mark contacted"}
                    </button>
                  )}
                  {rebook && onUpdateLead && (
                    <button
                      className="product-button"
                      onClick={() => {
                        const answer = window.prompt(`Rebook ${leadName(lead)} every how many days? (7 to 365)`, String(rebook.intervalDays));
                        const days = Number(answer);
                        if (answer === null) return;
                        if (!Number.isInteger(days) || days < 7 || days > 365) {
                          window.alert("Enter a whole number of days from 7 to 365.");
                          return;
                        }
                        Promise.resolve(onUpdateLead({ ...lead, rebook_interval_days: days })).catch((error) => window.alert(error?.message || "The interval could not be saved."));
                      }}
                    >
                      Set interval
                    </button>
                  )}
                  {rebook?.basis === "override" && onUpdateLead && (
                    <button className="product-button" onClick={() => Promise.resolve(onUpdateLead({ ...lead, rebook_interval_days: null })).catch((error) => window.alert(error?.message || "The change could not be saved."))}>Use visit history</button>
                  )}
                  <button className="product-button" onClick={() => setTimelineLead({ lead, health })}>View relationship</button>
                </div>
              </div>
            ))}
            {!opportunities.length && <div className="insight-row"><div className="insight-row-main"><strong>No one is due right now</strong><small>Customers appear here when their usual time between completed visits has nearly passed.</small></div></div>}
          </div>
          {waiting.length > 0 && (
            <div className="rebook-waiting">
              <h3>Contacted, waiting to book ({waiting.length})</h3>
              <div className="insight-list">
                {waiting.map((item) => (
                  <div className="insight-row" key={item.lead.id || item.lead.email}>
                    <div className="insight-row-main">
                      <strong>{leadName(item.lead)}</strong>
                      <small>Contacted {shortDay(item.contactedOn)}. Back on the list {shortDay(item.waitingUntil)} if they haven't booked.</small>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
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
          {playbooks.map((playbook) => (
            <section className="product-card" key={playbook.key}>
              <div className="product-eyebrow">{playbook.icon} Ready-made playbook</div>
              <h3 style={{ marginTop: 12 }}>{playbook.name}</h3>
              <p style={{ color: "var(--ra-muted)", lineHeight: 1.6 }}>{playbook.copy}</p>
              <button className="product-button primary" onClick={() => onOpenAutomations?.(playbook.key)}>Review this playbook</button>
              <small className="product-card-copy" style={{ display: "block", marginTop: 8 }}>Opens it for review. Nothing is sent until you activate it.</small>
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

      {tab === "value" && (
        <div className="product-grid">
          <ValueReceipt leads={leads} appointments={appointments} />
          <section className="product-card">
            <div className="product-eyebrow">Estimates · not revenue</div>
            <h3 style={{ marginTop: 10 }}>Open rebooking opportunities</h3>
            <p className="product-card-copy">
              Adds up only the values you recorded on these customers; customers without a value are counted, not guessed.
              This is not money received and is never included in verified revenue.
            </p>
            <div className="insight-list">
              <div className="insight-row"><span>Recorded value of open opportunities</span><strong>{valued.length ? money(opportunityValue) : "—"}</strong></div>
              <div className="insight-row"><span>Opportunities with a recorded value</span><strong>{valued.length}</strong></div>
              <div className="insight-row"><span>Customers with an opportunity</span><strong>{opportunities.length}</strong></div>
              <div className="insight-row"><span>Relationships monitored</span><strong>{leads.length}</strong></div>
            </div>
          </section>
          <section className="product-card">
            <h3>Recommended next step</h3>
            <p className="product-card-copy">
              {opportunities.length
                ? `Review your top ${Math.min(3, opportunities.length)} rebooking opportunities and decide who to contact.`
                : `Your ${user?.businessType || "business"} relationships look current.`}
            </p>
            <button className="product-button primary" onClick={() => setTab("opportunities")}>Open opportunities</button>
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
            <div className="account-detail-box" style={{ marginTop: 14 }}>
              <strong>Why this score</strong>
              <ul>
                {timelineLead.health.reasons.map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            </div>
            <div className="account-detail-box" style={{ marginTop: 14 }}>
              <strong>Relationship memory</strong>
              <p>
                {timelineLead.lead.notes ||
                  timelineLead.lead.summary ||
                  `${leadName(timelineLead.lead)} is best reached through ${timelineLead.lead.phone ? "phone or WhatsApp" : "email"}. RetainAI will expand this memory as conversations, appointments, preferences, and outcomes are recorded.`}
              </p>
            </div>
            <div className="timeline">
              {[
                ["Customer added", timelineLead.lead.createdAt || timelineLead.lead.created_at],
                ["Last outbound message", timelineLead.lead.last_outbound_at || timelineLead.lead.last_contacted],
                ["Last customer reply", timelineLead.lead.last_inbound_at || timelineLead.lead.last_reply_at],
                ["Record updated", timelineLead.lead.updated_at],
              ].filter(([, date]) => date).sort((a, b) => (parseAppointmentDateTime(b[1])?.getTime() || 0) - (parseAppointmentDateTime(a[1])?.getTime() || 0)).map(([label, date]) => (
                <div className="timeline-item" key={`${label}-${date}`}><strong>{label}</strong><small>{parseAppointmentDateTime(date)?.toLocaleString() || "Date unavailable"}</small></div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
