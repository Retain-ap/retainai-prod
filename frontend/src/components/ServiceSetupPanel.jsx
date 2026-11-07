import React, { useMemo, useState } from "react";
import { FaCheckCircle, FaRegCircle } from "react-icons/fa";
import { dayStart, visitsByLead } from "../rebooking";

const DAY = 24 * 60 * 60 * 1000;
const REVIEWED_KEYS = { general: "retainai:service-playbooks-reviewed", salon_barber: "retainai:salon-playbooks-reviewed" };

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
export function setupMetrics({ leads = [], appointments = [], rebooking = [], today }) {
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
    fromCalendly: appointments.filter((appt) => appt?.source === "calendly").length,
  };
}

export const salonMetrics = setupMetrics;

const COPY = {
  general: {
    region: "Service business setup",
    eyebrow: "Service business setup",
    preset: "General service business setup chosen",
    customers: "customer",
    playbooks: "Review the rebooking and reminder playbooks",
  },
  salon_barber: {
    region: "Salon and barber setup",
    eyebrow: "Salon and barber setup",
    preset: "Salon and barber preset chosen",
    customers: "client",
    playbooks: "Review the salon playbooks",
  },
};

export default function ServiceSetupPanel({ preset = "general", leads, appointments, rebooking, today, onOpenPlaybooks, onOpenImports, onOpenAppointments }) {
  const copy = COPY[preset] || COPY.general;
  const reviewedKey = REVIEWED_KEYS[preset] || REVIEWED_KEYS.general;
  const [reviewed, setReviewed] = useState(() => {
    try { return localStorage.getItem(reviewedKey) === "1"; } catch { return false; }
  });
  const metrics = useMemo(() => setupMetrics({ leads, appointments, rebooking, today }), [leads, appointments, rebooking, today]);
  const anyCompleted = rebooking.length > 0;

  const steps = [
    { label: copy.preset, done: true },
    { label: `Import your ${copy.customers} list`, done: leads.length > 0, action: onOpenImports, actionLabel: "Import" },
    {
      // Calendly is optional and may not be available on this server yet, so
      // appointments added in RetainAI complete this step too.
      id: "bookings",
      label: "Bring in your bookings",
      done: appointments.length > 0,
      // Calendly may not be available, so the action adds a RetainAI appointment.
      action: onOpenAppointments,
      actionLabel: "Add appointment",
      hint: "Add appointments in RetainAI, or sync them from Calendly if it is available on the Import page.",
    },
    { label: "A visit is marked completed", done: anyCompleted, hint: "Rebooking dates come from completed visits." },
    { label: `A ${copy.customers} has a personal rebooking rhythm`, done: metrics.withRhythm > 0, hint: `Needs 2 completed visits for the same ${copy.customers}.` },
    {
      label: metrics.importedAwaitingConsent
        ? `Confirm email consent for ${metrics.importedAwaitingConsent} imported ${copy.customers}${metrics.importedAwaitingConsent === 1 ? "" : "s"}`
        : `Imported ${copy.customers}s' email consent reviewed`,
      done: metrics.importedAwaitingConsent === 0,
      hint: `Importing or syncing never records consent. Automated emails wait until it is confirmed on the ${copy.customers}'s profile.`,
    },
    {
      label: copy.playbooks,
      done: reviewed,
      action: () => {
        try { localStorage.setItem(reviewedKey, "1"); } catch {}
        setReviewed(true);
        onOpenPlaybooks?.();
      },
      actionLabel: "Review",
      hint: "Nothing is switched on until you activate a playbook yourself.",
    },
  ];

  return (
    <section className="product-card salon-setup" aria-label={copy.region} style={{ gridColumn: "1 / -1" }}>
      <div className="product-card-header">
        <div>
          <div className="product-eyebrow">{copy.eyebrow}</div>
          <h2 style={{ marginTop: 8 }}>{steps.filter((step) => step.done).length} of {steps.length} steps done</h2>
        </div>
      </div>
      <ul className="salon-steps">
        {steps.map((step) => (
          <li key={step.label} className={step.done ? "done" : ""} data-testid={step.id ? `setup-step-${step.id}` : undefined}>
            {step.done ? <FaCheckCircle aria-hidden="true" /> : <FaRegCircle aria-hidden="true" />}
            <span><strong>{step.label}</strong>{step.hint && <small>{step.hint}</small>}</span>
            {!step.done && step.action && <button type="button" className="product-button" onClick={step.action}>{step.actionLabel}</button>}
          </li>
        ))}
      </ul>
      <div className="salon-metrics" data-testid="salon-metrics">
        {[
          ["completed30", metrics.completed30, "Completed visits, last 30 days"],
          ["withRhythm", metrics.withRhythm, `${copy.customers === "client" ? "Clients" : "Customers"} with a rebooking rhythm`],
          ["dueNow", metrics.dueNow, "Due to rebook this week"],
          ["withNextBooking", metrics.withNextBooking, `${copy.customers === "client" ? "Clients" : "Customers"} with a next booking`],
          ["noShowRate30", metrics.noShowRate30 === null ? "—" : `${metrics.noShowRate30}%`, "No-show rate, last 30 days"],
        ].map(([key, value, label]) => (
          <div key={key} data-testid={`salon-metric-${key}`}><strong>{value}</strong><span>{label}</span></div>
        ))}
      </div>
      <p className="product-card-copy salon-note">
        Counts only: no names, notes or messages appear here.{" "}
        {metrics.fromCalendly
          ? `${metrics.fromCalendly} booking${metrics.fromCalendly === 1 ? "" : "s"} imported from Calendly, plus appointments added in RetainAI.`
          : "No bookings imported from a booking platform yet; appointments you add in RetainAI are used."}
      </p>
    </section>
  );
}
