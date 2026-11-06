import React, { useMemo, useState } from "react";
import { FaCheckCircle, FaRegCircle } from "react-icons/fa";
import { dayStart, visitsByLead } from "../rebooking";

const DAY = 24 * 60 * 60 * 1000;
const REVIEWED_KEY = "retainai:salon-playbooks-reviewed";

// Ready-made salon/barber playbooks. Each opens an existing automation template
// for the owner to review; nothing is switched on from here.
export const SALON_PLAYBOOKS = [
  { key: "rebook", name: "Rebook at each client's usual interval", copy: "Suggests a check-in when a client's normal time between cuts or colours has passed." },
  { key: "no_show", name: "Day-before appointment reminder", copy: "A short reminder before each booking to cut no-shows." },
  { key: "reviews", name: "Thank-you and review request", copy: "A thank-you after a completed visit, with an optional review link." },
  { key: "winback", name: "Win back lapsed clients", copy: "A friendly note for clients who haven't been in for a long time." },
  { key: "birthday", name: "Birthday note", copy: "Sent only to clients whose email consent is confirmed." },
];

/** Aggregate counts only: no names, notes or messages. */
export function salonMetrics({ leads = [], appointments = [], rebooking = [], today }) {
  const todayMs = dayStart(today);
  if (todayMs === null) {
    return { completed30: 0, noShowRate30: null, withRhythm: 0, dueNow: 0, withNextBooking: 0, importedAwaitingConsent: 0 };
  }
  const since = todayMs - 30 * DAY;
  let completed30 = 0;
  let noShow30 = 0;
  let booked30 = 0;
  appointments.forEach((appt) => {
    const day = dayStart(appt?.date || appt?.appointment_time);
    if (day === null || day < since || day > todayMs) return;
    const status = String(appt?.status || "").toLowerCase().replace(/_/g, "-");
    const fromBackend = Boolean(appt?._backend || status);
    if (status === "no-show") noShow30 += 1;
    else if (fromBackend ? status === "completed" : appt?.done) completed30 += 1;
    if (status !== "cancelled" && status !== "canceled") booked30 += 1;
  });
  const visits = visitsByLead(appointments, todayMs);
  let withNextBooking = 0;
  visits.forEach((entry) => { if (entry.upcoming.some((day) => day >= todayMs)) withNextBooking += 1; });
  return {
    completed30,
    noShowRate30: booked30 ? Math.round((noShow30 / booked30) * 100) : null,
    withRhythm: rebooking.filter((item) => item.basis === "personal" || item.basis === "personal_single").length,
    dueNow: rebooking.filter((item) => !item.bookedFor && item.daysUntilDue <= 7).length,
    withNextBooking,
    importedAwaitingConsent: leads.filter((lead) => lead?.imported_at && lead?.email_consent_status !== "confirmed").length,
  };
}

export default function SalonSetupPanel({ leads, appointments, rebooking, today, onOpenPlaybooks, onOpenImports }) {
  const [reviewed, setReviewed] = useState(() => {
    try { return localStorage.getItem(REVIEWED_KEY) === "1"; } catch { return false; }
  });
  const metrics = useMemo(() => salonMetrics({ leads, appointments, rebooking, today }), [leads, appointments, rebooking, today]);
  const anyCompleted = rebooking.length > 0;

  const steps = [
    { label: "Salon and barber preset chosen", done: true },
    { label: "Import your client list", done: leads.length > 0, action: onOpenImports, actionLabel: "Import" },
    { label: "Mark a visit as completed", done: anyCompleted, hint: "Rebooking dates come from completed visits." },
    { label: "A client has a personal rebooking rhythm", done: metrics.withRhythm > 0, hint: "Needs 2 completed visits for the same client." },
    {
      label: metrics.importedAwaitingConsent
        ? `Confirm email consent for ${metrics.importedAwaitingConsent} imported client${metrics.importedAwaitingConsent === 1 ? "" : "s"}`
        : "Imported clients' email consent reviewed",
      done: metrics.importedAwaitingConsent === 0,
      hint: "Automated emails wait until consent is confirmed on the client's profile.",
    },
    {
      label: "Review the salon playbooks",
      done: reviewed,
      action: () => {
        try { localStorage.setItem(REVIEWED_KEY, "1"); } catch {}
        setReviewed(true);
        onOpenPlaybooks?.();
      },
      actionLabel: "Review",
      hint: "Nothing is switched on until you activate a playbook yourself.",
    },
  ];

  return (
    <section className="product-card salon-setup" aria-label="Salon and barber setup" style={{ gridColumn: "1 / -1" }}>
      <div className="product-card-header">
        <div>
          <div className="product-eyebrow">Salon and barber setup</div>
          <h2 style={{ marginTop: 8 }}>{steps.filter((step) => step.done).length} of {steps.length} steps done</h2>
        </div>
      </div>
      <ul className="salon-steps">
        {steps.map((step) => (
          <li key={step.label} className={step.done ? "done" : ""}>
            {step.done ? <FaCheckCircle aria-hidden="true" /> : <FaRegCircle aria-hidden="true" />}
            <span><strong>{step.label}</strong>{step.hint && <small>{step.hint}</small>}</span>
            {!step.done && step.action && <button type="button" className="product-button" onClick={step.action}>{step.actionLabel}</button>}
          </li>
        ))}
      </ul>
      <div className="salon-metrics" data-testid="salon-metrics">
        {[
          ["completed30", metrics.completed30, "Completed visits, last 30 days"],
          ["withRhythm", metrics.withRhythm, "Clients with a rebooking rhythm"],
          ["dueNow", metrics.dueNow, "Due to rebook this week"],
          ["withNextBooking", metrics.withNextBooking, "Clients with a next booking"],
          ["noShowRate30", metrics.noShowRate30 === null ? "—" : `${metrics.noShowRate30}%`, "No-show rate, last 30 days"],
        ].map(([key, value, label]) => (
          <div key={key} data-testid={`salon-metric-${key}`}><strong>{value}</strong><span>{label}</span></div>
        ))}
      </div>
      <p className="product-card-copy salon-note">
        Counts only: no client names, notes or messages appear here. Booking platform: none connected yet;
        appointments you add in RetainAI are used.
      </p>
    </section>
  );
}
