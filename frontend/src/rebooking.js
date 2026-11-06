// Personalized rebooking: when is each customer next likely to need a visit?
//
// Based only on completed visits RetainAI has recorded. Each suggestion says
// where its interval comes from, from most to least specific:
//   1. an interval the owner set on the contact (rebook_interval_days)
//   2. the customer's own completed-visit history
//   3. the typical interval across this workspace's customers
//   4. a default for the business type (salon/barber presets, else general)

const DAY = 24 * 60 * 60 * 1000;
export const MIN_INTERVAL_DAYS = 7;
export const MAX_INTERVAL_DAYS = 365;
// Visits closer together than this are treated as one visit (split or duplicate records).
const SAME_VISIT_DAYS = 3;

export const DEFAULT_INTERVALS = {
  barber: { days: 28, label: "barbershop default (4 weeks)" },
  salon: { days: 42, label: "salon default (6 weeks)" },
  general: { days: 60, label: "general default (60 days)" },
};

export function businessKind(user) {
  const preset = String(user?.setup_preset || "").toLowerCase();
  const text = `${user?.businessType || ""} ${user?.lineOfBusiness || ""}`.toLowerCase();
  if (/barber/.test(text)) return "barber";
  if (/salon|hair|beauty|nail|lash|brow|spa|stylist/.test(text) || preset === "salon_barber") return "salon";
  return "general";
}

/** A real calendar day (YYYY-MM-DD...) as UTC midnight ms, or null. */
export function dayStart(dateKey) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(dateKey || ""));
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  if (year < 2000 || year > 2100) return null;
  const ms = Date.UTC(year, month - 1, day);
  const check = new Date(ms);
  // Date.UTC rolls 2026-02-31 over to March: reject instead of guessing.
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return null;
  return ms;
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
}

const clampInterval = (days) => Math.max(MIN_INTERVAL_DAYS, Math.min(MAX_INTERVAL_DAYS, Math.round(days)));

function leadKeyOf(lead) {
  return String(lead?.id || lead?.email || "").toLowerCase();
}

/**
 * Completed and upcoming visits per contact key. A visit dated after
 * `todayMs` can't have been completed yet, so it is never completion evidence.
 */
export function visitsByLead(appointments = [], todayMs = null) {
  const out = new Map();
  appointments.forEach((appt) => {
    const key = leadKeyOf(appt?.lead) || String(appt?.lead_id || appt?.lead_email || "").toLowerCase();
    const day = dayStart(appt?.date || appt?.appointment_time);
    if (!key || day === null) return;
    const status = String(appt?.status || "").toLowerCase().replace(/_/g, "-");
    const fromBackend = Boolean(appt?._backend || status);
    // Backend "done" is also set for cancelled and no-show visits.
    const markedDone = fromBackend ? status === "completed" : Boolean(appt?.done);
    const completed = markedDone && (todayMs === null || day <= todayMs);
    const upcoming = !markedDone && !appt?.done && !["completed", "cancelled", "canceled", "no-show"].includes(status);
    const entry = out.get(key) || { completed: [], upcoming: [] };
    if (completed) entry.completed.push(day);
    else if (upcoming) entry.upcoming.push(day);
    out.set(key, entry);
  });
  out.forEach((entry) => {
    const days = [...new Set(entry.completed)].sort((a, b) => a - b);
    entry.completed = days.filter((day, index) => index === 0 || (day - days[index - 1]) / DAY >= SAME_VISIT_DAYS);
    entry.upcoming.sort((a, b) => a - b);
  });
  return out;
}

function personalIntervals(completed) {
  const gaps = [];
  for (let i = 1; i < completed.length; i += 1) gaps.push((completed[i] - completed[i - 1]) / DAY);
  return gaps.filter((gap) => gap >= MIN_INTERVAL_DAYS && gap <= MAX_INTERVAL_DAYS);
}

function formatDay(ms) {
  return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

/**
 * Suggestions for every contact with at least one completed visit.
 * `today` is a YYYY-MM-DD string in the workspace's timezone.
 */
export function rebookingSuggestions({ leads = [], appointments = [], user, today }) {
  const todayMs = dayStart(today);
  const visits = visitsByLead(appointments, todayMs);
  const kind = businessKind(user);

  const personal = new Map();
  visits.forEach((entry, key) => {
    const gaps = personalIntervals(entry.completed);
    if (gaps.length) personal.set(key, { days: median(gaps), count: gaps.length });
  });
  const workspaceMedians = [...personal.values()].filter((value) => value.count >= 2).map((value) => value.days);
  const workspaceInterval = workspaceMedians.length >= 3 ? clampInterval(median(workspaceMedians)) : null;

  const out = [];
  leads.forEach((lead) => {
    const key = leadKeyOf(lead);
    const entry = visits.get(key);
    if (!entry || !entry.completed.length || todayMs === null) return;
    const lastVisit = entry.completed[entry.completed.length - 1];
    const own = personal.get(key);
    const override = Number(lead?.rebook_interval_days);
    let interval;
    let basis;
    let reason;
    if (Number.isFinite(override) && override >= MIN_INTERVAL_DAYS && override <= MAX_INTERVAL_DAYS) {
      interval = Math.round(override);
      basis = "override";
      reason = `You set a ${interval}-day rebooking interval for this customer.`;
    } else if (own && own.count >= 2) {
      interval = clampInterval(own.days);
      basis = "personal";
      reason = `Visits about every ${interval} days (median of ${own.count} gaps between ${own.count + 1} completed visits).`;
    } else if (own) {
      interval = clampInterval(own.days);
      basis = "personal_single";
      reason = `One gap of ${interval} days between their 2 completed visits. More visits will make this more reliable.`;
    } else if (workspaceInterval) {
      interval = workspaceInterval;
      basis = "workspace";
      reason = `Only 1 completed visit recorded, so this uses your customers' typical ${interval}-day interval.`;
    } else {
      interval = DEFAULT_INTERVALS[kind].days;
      basis = "default";
      reason = `Only 1 completed visit recorded and not enough history yet, so this uses the ${DEFAULT_INTERVALS[kind].label}.`;
    }
    const due = lastVisit + interval * DAY;
    const nextBooked = entry.upcoming.find((day) => day >= todayMs);
    out.push({
      lead,
      intervalDays: interval,
      basis,
      completedVisits: entry.completed.length,
      lastVisit: new Date(lastVisit).toISOString().slice(0, 10),
      dueDate: new Date(due).toISOString().slice(0, 10),
      daysUntilDue: Math.round((due - todayMs) / DAY),
      bookedFor: nextBooked ? new Date(nextBooked).toISOString().slice(0, 10) : "",
      reasons: [
        `Last completed visit ${formatDay(lastVisit)}.`,
        reason,
        nextBooked ? `Already booked for ${formatDay(nextBooked)}.` : "",
      ].filter(Boolean),
    });
  });
  return out.sort((a, b) => a.daysUntilDue - b.daysUntilDue);
}

/** Customers to contact now: due within `aheadDays` or overdue, and not already booked. */
export function dueForRebooking(suggestions, aheadDays = 7) {
  return suggestions.filter((item) => !item.bookedFor && item.daysUntilDue <= aheadDays);
}
