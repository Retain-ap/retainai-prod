// src/components/Appointments.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  FaSearch,
  FaCalendarAlt,
  FaPlus,
  FaExclamationTriangle,
  FaSun,
  FaCalendarWeek,
  FaForward,
  FaCheckCircle,
  FaClock,
} from "react-icons/fa";
import { API_BASE } from "../apiBase";
import { getWorkspaceEmail } from "../workspaceIdentity";
import {
  addDaysToDateKey,
  appointmentDateTimeParts,
  buildAppointmentTimestamp,
  calendarDayDistance,
  compareAppointmentToNow,
  dateKeyFromParts,
  dayKeyNow,
  formatDateKey,
  getBrowserTimeZone,
  parseAppointmentDateTime,
  timeKeyFromParts,
} from "./appointmentDateTime";
import "./Appointments.css";

/* === THEME === */
const BG = "#181a1b";
const CARD = "#232323";
const SOFT = "#1e2326";
const BORDER = "#2b2f33";
const TEXT = "#f3f4f5";
const SUBTEXT = "#9aa3ab";

const GOLD = "#f7cb53";
const GREEN = "#30b46c";
const RED = "#e66565";

/* === API === */
/* === storage key for analytics/backend mirror === */
const BACKEND_APPT_COUNTS_KEY = (email) =>
  `retainai_backend_appt_counts_${String(email || "").trim().toLowerCase() || "anon"}`;

/* ===== Helpers ===== */
function parseDateSafe(v) {
  return parseAppointmentDateTime(v);
}

function normText(v) {
  return String(v || "").trim().toLowerCase();
}

function normEmail(v) {
  return String(v || "").trim().toLowerCase();
}

/** server-provided id field (if any) */
const getRealIdField = (r) =>
  r?.id ??
  r?._id ??
  r?.appointment_id ??
  r?.appointmentId ??
  r?.appointmentID ??
  r?.record_id ??
  r?.recordId ??
  r?.aid ??
  r?.uuid ??
  null;

const hasRealId = (r) => Boolean(getRealIdField(r));

const getRID = (r) =>
  String(r?._rid ?? r?._client_uid ?? getRealIdField(r) ?? "");

const safe = (v) => (v == null ? "" : String(v));

/* === Local-storage persistence (per-user) === */
const LS_KEYS = (email) => ({
  hidden: `appt_hidden_${email || "anon"}`,
  done: `appt_done_${email || "anon"}`,
  time: `appt_time_${email || "anon"}`,
  slots: `appt_slots_${email || "anon"}`,
});

const loadJSON = (k, fallback) => {
  try {
    const v = localStorage.getItem(k);
    return v ? JSON.parse(v) : fallback;
  } catch {
    return fallback;
  }
};

const saveJSON = (k, obj) => {
  try {
    localStorage.setItem(k, JSON.stringify(obj || {}));
  } catch {}
};

const uuid = () =>
  "xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });

const ping = (name) => window.dispatchEvent(new Event(name));

/* ===== Fingerprints for no-id rows ===== */
const sigOf = (r) =>
  [
    safe(r.lead_id ?? r.lead_email ?? r.lead_first_name ?? ""),
    safe(r.appointment_time ?? ""),
    safe(r.title ?? ""),
    safe(r.notes ?? ""),
  ].join("|");

const stableKey = (r) =>
  [
    sigOf(r),
    safe(r.created_at || r.updated_at || r.appointment_time || ""),
    safe(r.title || ""),
  ].join("~");

function assignStableRIDs(rows, slotMap) {
  const copy = (rows || []).map((r) => ({ ...r }));

  copy.sort((a, b) => {
    const ka = stableKey(a);
    const kb = stableKey(b);
    if (ka < kb) return -1;
    if (ka > kb) return 1;
    return 0;
  });

  const bySig = new Map();
  copy.forEach((r) => {
    const sig = hasRealId(r) ? `REAL:${getRealIdField(r)}` : `SIG:${sigOf(r)}`;
    if (!bySig.has(sig)) bySig.set(sig, []);
    bySig.get(sig).push(r);
  });

  const nextSlots = { ...(slotMap || {}) };

  bySig.forEach((groupRows, sig) => {
    if (sig.startsWith("REAL:")) {
      groupRows.forEach((r) => {
        r._rid = String(getRealIdField(r));
      });
      return;
    }

    const key = sig.slice(4);
    const slots = Array.isArray(nextSlots[key]) ? [...nextSlots[key]] : [];
    while (slots.length < groupRows.length) slots.push(uuid());

    groupRows.forEach((r, i) => {
      r._rid = slots[i];
      r._client_uid = slots[i];
    });

    nextSlots[key] = slots;
  });

  return { rows: copy, nextSlots };
}

function normalizeBackend(raw, fallbackTimezone = "") {
  const dt = parseDateSafe(raw?.appointment_time);
  const timeZone = raw?.timezone || fallbackTimezone;
  const parts = appointmentDateTimeParts(raw?.appointment_time, timeZone);
  if (!dt || !parts) return null;
  const status = normText(raw?.status).replace(/-/g, "_");

  return {
    _backend: raw,
    _rid: getRID(raw),
    title: raw.title || raw.lead_first_name || raw.business_name || "Appointment",
    date: dateKeyFromParts(parts),
    time: timeKeyFromParts(parts),
    timeZone,
    sortKey: dt.getTime(),
    status,
    cancelled: status === "cancelled" || status === "canceled",
    done: !!(raw.done ?? raw.completed ?? raw.is_done) || status === "completed",
    notes: raw.notes || "",
    lead: {
      id: raw.lead_id || "",
      name:
        raw.lead_full_name ||
        [raw.lead_first_name, raw.lead_last_name].filter(Boolean).join(" ") ||
        raw.lead_email ||
        "Client",
      email: raw.lead_email || "",
      tags: [],
    },
  };
}

function getAppointments(leads = [], backendRows = [], fallbackTimezone = "") {
  const list = [];
  const now = new Date();

  const normalizedSignature = (appointment) =>
    [
      safe(appointment?.lead?.id || appointment?.lead?.email || appointment?.lead_id || appointment?.lead_email)
        .trim()
        .toLowerCase(),
      `${safe(appointment?.date)}T${safe(appointment?.time || "00:00")}`.slice(0, 16),
      safe(appointment?.title || "Appointment").trim().toLowerCase(),
    ].join("|");

  const backendSignatures = new Set();
  (backendRows || []).forEach((appointment) => {
    if (appointment.cancelled) return;
    const dt = parseDateSafe(appointment?._backend?.appointment_time) ||
      parseDateSafe(`${appointment.date}T${appointment.time || "00:00"}`);
    if (!dt) return;
    const normalized = {
      ...appointment,
      sortKey: Number.isFinite(appointment.sortKey) ? appointment.sortKey : dt.getTime(),
      isOverdue:
        !appointment.done &&
        compareAppointmentToNow(
          appointment.date,
          appointment.time,
          appointment.timeZone || fallbackTimezone,
          now
        ) < 0,
    };
    backendSignatures.add(normalizedSignature(normalized));
    list.push(normalized);
  });

  (leads || []).forEach((lead) =>
    (lead.appointments || []).forEach((app, idx) => {
      const dt = parseDateSafe(`${app.date}T${app.time || "00:00"}`);
      if (!dt) return;
      const normalized = {
        ...app,
        _local: true,
        _localKey:
          app._localKey ||
          `${String(lead.id)}|${String(app.title)}|${String(app.date)}|${String(app.time || "")}|${idx}`,
        lead,
        timeZone: fallbackTimezone,
        sortKey: dt.getTime(),
        isOverdue:
          !app.done &&
          compareAppointmentToNow(app.date, app.time || "00:00", fallbackTimezone, now) < 0,
      };
      if (!backendSignatures.has(normalizedSignature(normalized))) list.push(normalized);
    })
  );

  list.sort((a, b) => a.sortKey - b.sortKey);
  return list;
}

function categorize(appointments) {
  const buckets = { overdue: [], today: [], next7: [], later: [], done: [] };
  const now = new Date();

  appointments.forEach((a) => {
    if (a.done) {
      buckets.done.push(a);
      return;
    }
    const todayKey = dayKeyNow(a.timeZone, now);
    const relative = compareAppointmentToNow(a.date, a.time || "00:00", a.timeZone, now);
    if (!Number.isFinite(relative)) return;
    if (a.date === todayKey && relative >= 0) {
      buckets.today.push(a);
      return;
    }
    if (relative < 0) {
      buckets.overdue.push(a);
      return;
    }
    const diff = calendarDayDistance(todayKey, a.date);
    if (diff <= 7) buckets.next7.push(a);
    else buckets.later.push(a);
  });

  return buckets;
}

function monthLabel(dateStr) {
  return formatDateKey(dateStr, { month: "short", day: "numeric", year: "numeric" });
}

function statusMeta(appt) {
  if (appt.done) return { label: "Done", color: GREEN };
  if (appt.isOverdue) return { label: "Overdue", color: RED };
  return { label: "Scheduled", color: GOLD };
}

function keyFor(a) {
  return `${a._rid ?? a._localKey ?? a.lead?.id ?? "x"}|${a.title}|${a.date}|${a.time || ""}`;
}

function getLeadDisplayName(lead) {
  return lead?.name || lead?.email || "Lead";
}

function dateWeeksFromNow(weeks, timeZone) {
  return addDaysToDateKey(dayKeyNow(timeZone), weeks * 7);
}

export default function Appointments({ user, leads = [], setLeads }) {
  const [backendAppointments, setBackendAppointments] = useState([]);
  const [backendWorkspace, setBackendWorkspace] = useState("");
  const [workspaceTimezone, setWorkspaceTimezone] = useState("");
  const [loadingAppointments, setLoadingAppointments] = useState(false);
  const [appointmentsError, setAppointmentsError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [hiddenIds, setHiddenIds] = useState({});
  const [doneOverride, setDoneOverride] = useState({});
  const [timeOverride, setTimeOverride] = useState({});
  const [slotMap, setSlotMap] = useState({});
  const slotMapRef = useRef({});
  const activeWorkspaceRef = useRef("");
  const capturedReminderRef = useRef(false);

  const [search, setSearch] = useState("");
  const [showCompleted, setShowCompleted] = useState(false);
  const [saving, setSaving] = useState(false);

  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [noteAppointment, setNoteAppointment] = useState(null);
  const [noteSaving, setNoteSaving] = useState(false);
  const [visitNote, setVisitNote] = useState({
    outcome: "Completed",
    details: "",
    preferences: "",
    followUp: "",
    rebook: "",
  });
  const [form, setForm] = useState({
    leadId: "",
    title: "",
    date: "",
    time: "",
    notes: "",
  });

  const userEmail = getWorkspaceEmail(user);
  activeWorkspaceRef.current = userEmail;
  const effectiveTimezone =
    workspaceTimezone || user?.timezone || getBrowserTimeZone();
  const freshAppointmentForm = () => {
    const suggested = new Date(Date.now() + 30 * 60 * 1000);
    suggested.setMinutes(Math.ceil(suggested.getMinutes() / 15) * 15, 0, 0);
    const parts = appointmentDateTimeParts(suggested, effectiveTimezone);
    return {
      leadId: "",
      title: "",
      date: dateKeyFromParts(parts),
      time: timeKeyFromParts(parts),
      notes: "",
    };
  };
  const suggestedRebookWeeks = useMemo(() => {
    const business = String(user?.businessType || user?.lineOfBusiness || user?.business || "").toLowerCase();
    if (/barber|hair|nail|salon|beauty|spa/.test(business)) return 4;
    if (/dental|chiro|physio|therapy|wellness/.test(business)) return 6;
    if (/clean|hvac|maintenance|home service/.test(business)) return 12;
    return 4;
  }, [user?.businessType, user?.lineOfBusiness, user?.business]);

  useEffect(() => {
    const K = LS_KEYS(userEmail);
    const loadedHidden = loadJSON(K.hidden, {});
    const loadedDone = loadJSON(K.done, {});
    const loadedTime = loadJSON(K.time, {});
    const loadedSlots = loadJSON(K.slots, {});

    setHiddenIds(loadedHidden);
    setDoneOverride(loadedDone);
    setTimeOverride(loadedTime);
    setSlotMap(loadedSlots);
    slotMapRef.current = loadedSlots;
    setBackendWorkspace("");
    setWorkspaceTimezone("");
    setAppointmentsError("");
    setActionError("");
  }, [userEmail]);

  useEffect(() => {
    saveJSON(LS_KEYS(userEmail).hidden, hiddenIds);
  }, [hiddenIds, userEmail]);

  useEffect(() => {
    saveJSON(LS_KEYS(userEmail).done, doneOverride);
  }, [doneOverride, userEmail]);

  useEffect(() => {
    saveJSON(LS_KEYS(userEmail).time, timeOverride);
  }, [timeOverride, userEmail]);

  useEffect(() => {
    saveJSON(LS_KEYS(userEmail).slots, slotMap);
  }, [slotMap, userEmail]);

  function syncBackendCountsToApp(rows) {
    const byId = {};
    const byEmail = {};

    (rows || []).forEach((r) => {
      const leadId = String(r?.lead_id || "").trim();
      const leadEmail = normEmail(r?.lead_email || "");

      if (leadId) byId[leadId] = (byId[leadId] || 0) + 1;
      if (leadEmail) byEmail[leadEmail] = (byEmail[leadEmail] || 0) + 1;
    });

    saveJSON(BACKEND_APPT_COUNTS_KEY(userEmail), {
      byId,
      byEmail,
      updatedAt: new Date().toISOString(),
    });

    if (typeof setLeads === "function") {
      setLeads((prev) => {
        const safePrev = Array.isArray(prev) ? prev : [];
        return safePrev.map((lead) => {
          const idCount = byId[String(lead?.id || "").trim()] || 0;
          const emailCount = byEmail[normEmail(lead?.email || "")] || 0;
          const backendCount = Math.max(idCount, emailCount);

          return {
            ...lead,
            _backendAppointmentCount: backendCount,
            _hasAnyAppointment: backendCount > 0 || (lead.appointments || []).length > 0,
          };
        });
      });
    }

    ping("appointments:analytics-sync");
  }

  const fetchBackend = async () => {
    const requestedWorkspace = userEmail;
    if (!requestedWorkspace) {
      setBackendAppointments([]);
      setBackendWorkspace("");
      setWorkspaceTimezone("");
      setAppointmentsError("");
      setLoadingAppointments(false);
      return [];
    }
    setLoadingAppointments(true);
    try {
      const r = await fetch(`${API_BASE}/api/appointments/${encodeURIComponent(requestedWorkspace)}`, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j?.error || `Appointments request failed (${r.status})`);
      if (!Array.isArray(j?.appointments)) throw new Error("Appointments response was incomplete");
      const rows = j.appointments;
      if (activeWorkspaceRef.current !== requestedWorkspace) return null;
      setBackendAppointments(rows);
      setBackendWorkspace(requestedWorkspace);
      setWorkspaceTimezone(j?.timezone || "");
      setAppointmentsError("");
      syncBackendCountsToApp(rows);
      return rows;
    } catch (error) {
      if (activeWorkspaceRef.current === requestedWorkspace) {
        setAppointmentsError(error?.message || "Appointments could not be loaded");
      }
      return null;
    } finally {
      if (activeWorkspaceRef.current === requestedWorkspace) setLoadingAppointments(false);
    }
  };

  useEffect(() => {
    fetchBackend();

    const onChanged = () => fetchBackend();
    const onVis = () => {
      if (document.visibilityState === "visible") fetchBackend();
    };

    window.addEventListener("appointments:changed", onChanged);
    document.addEventListener("visibilitychange", onVis);

    return () => {
      window.removeEventListener("appointments:changed", onChanged);
      document.removeEventListener("visibilitychange", onVis);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userEmail]);

  const assignedBackend = useMemo(() => {
    const rows = backendWorkspace === userEmail ? backendAppointments : [];
    return assignStableRIDs(rows, slotMapRef.current || {});
  }, [backendAppointments, backendWorkspace, userEmail]);

  useEffect(() => {
    const oldStr = JSON.stringify(slotMapRef.current || {});
    const newStr = JSON.stringify(assignedBackend.nextSlots || {});
    if (oldStr !== newStr) {
      slotMapRef.current = assignedBackend.nextSlots || {};
      setSlotMap(assignedBackend.nextSlots || {});
    }
  }, [assignedBackend.nextSlots]);

  const effectiveBackend = useMemo(() => {
    return (assignedBackend.rows || [])
      .map((r) => {
        const id = r._rid;
        const clone = { ...r };
        if (timeOverride[id]) clone.appointment_time = timeOverride[id];
        if (typeof doneOverride[id] === "boolean") clone.done = doneOverride[id];
        return clone;
      })
      .filter((r) => !hiddenIds[r._rid]);
  }, [assignedBackend.rows, hiddenIds, doneOverride, timeOverride]);

  const normalizedBackend = useMemo(
    () => effectiveBackend.map((r) => normalizeBackend(r, effectiveTimezone)).filter(Boolean),
    [effectiveBackend, effectiveTimezone]
  );

  const allAppointments = useMemo(
    () => getAppointments(leads, normalizedBackend, effectiveTimezone),
    [leads, normalizedBackend, effectiveTimezone]
  );

  useEffect(() => {
    if (capturedReminderRef.current || !allAppointments.length) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("capture") !== "1") return;
    const now = Date.now();
    const mostRecent = allAppointments
      .filter((appointment) =>
        !appointment.done &&
        (appointment._backend
          ? appointment.sortKey <= now
          : compareAppointmentToNow(
              appointment.date,
              appointment.time || "00:00",
              appointment.timeZone || effectiveTimezone,
              new Date(now)
            ) <= 0)
      )
      .sort((a, b) => b.sortKey - a.sortKey)[0];
    if (mostRecent) {
      capturedReminderRef.current = true;
      openVisitNote(mostRecent);
    }
    // The reminder should be evaluated only when the appointment collection changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allAppointments]);

  const filtered = useMemo(() => {
    if (!search) return allAppointments;
    const q = normText(search);

    return allAppointments.filter((a) => {
      const hay = [
        a.title,
        a.lead?.name || "",
        a.lead?.email || "",
        a.notes || "",
        a.date || "",
      ]
        .join(" ")
        .toLowerCase();

      return hay.includes(q);
    });
  }, [allAppointments, search]);

  const buckets = useMemo(() => categorize(filtered), [filtered]);

  const withSeconds = (date, time) => buildAppointmentTimestamp(date, time);
  const serverIdOf = (appt) => getRealIdField(appt?._backend) ?? null;
  const isBackend = (appt) => Boolean(appt._backend);

  const updateDoneOverrides = (appt, val) => {
    const rid = appt._rid;
    const sid = serverIdOf(appt);
    setDoneOverride((m) => ({ ...m, [rid]: val, ...(sid ? { [sid]: val } : {}) }));
    ping("appointments:overrides-updated");
  };

  const rollbackDoneOverrides = (appt, prevVal) => {
    const rid = appt._rid;
    const sid = serverIdOf(appt);
    setDoneOverride((m) => ({ ...m, [rid]: prevVal, ...(sid ? { [sid]: prevVal } : {}) }));
    ping("appointments:overrides-updated");
  };

  const removeDoneOverrides = (appt) => {
    const rid = appt._rid;
    const sid = serverIdOf(appt);
    setDoneOverride((current) => {
      const next = { ...current };
      delete next[rid];
      if (sid) delete next[sid];
      return next;
    });
  };

  const updateTimeOverrides = (appt, iso) => {
    const rid = appt._rid;
    const sid = serverIdOf(appt);
    setTimeOverride((m) => ({ ...m, [rid]: iso, ...(sid ? { [sid]: iso } : {}) }));
    ping("appointments:overrides-updated");
  };

  const removeTimeOverrides = (appt) => {
    const rid = appt._rid;
    const sid = serverIdOf(appt);

    setTimeOverride((m) => {
      const c = { ...m };
      delete c[rid];
      if (sid) delete c[sid];
      return c;
    });

    ping("appointments:overrides-updated");
  };

  const hideOverrides = (appt) => {
    const rid = appt._rid;
    const sid = serverIdOf(appt);
    setHiddenIds((m) => ({ ...m, [rid]: true, ...(sid ? { [sid]: true } : {}) }));
    ping("appointments:overrides-updated");
  };

  const unhideOverrides = (appt) => {
    const rid = appt._rid;
    const sid = serverIdOf(appt);

    setHiddenIds((m) => {
      const c = { ...m };
      delete c[rid];
      if (sid) delete c[sid];
      return c;
    });

    ping("appointments:overrides-updated");
  };

  async function apiUpdateBackend(appt, updates) {
    const sid = serverIdOf(appt);
    if (!userEmail || !sid) throw new Error("This appointment is missing its server ID.");

    const body = {
      ...updates,
      done: updates.done,
      is_done: updates.done,
      completed: updates.done,
      status:
        updates.done === true
          ? "completed"
          : updates.done === false
          ? "scheduled"
          : undefined,
      appointment_time: updates.appointment_time,
      date: updates.appointment_time ? updates.appointment_time.slice(0, 10) : undefined,
      time: updates.appointment_time ? updates.appointment_time.slice(11, 16) : undefined,
      timezone: updates.timezone || appt.timeZone || effectiveTimezone,
    };

    const response = await fetch(
      `${API_BASE}/api/appointments/${encodeURIComponent(userEmail)}/${encodeURIComponent(
        String(sid)
      )}`,
      {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      }
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.error || `Appointment update failed (${response.status})`);
    }
    return payload?.appointment || true;
  }

  async function apiDeleteBackend(appt) {
    const sid = serverIdOf(appt);
    if (!userEmail || !sid) throw new Error("This appointment is missing its server ID.");

    const response = await fetch(
      `${API_BASE}/api/appointments/${encodeURIComponent(userEmail)}/${encodeURIComponent(
        String(sid)
      )}`,
      {
        method: "DELETE",
        credentials: "include",
        headers: { Accept: "application/json" },
      }
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.error || `Appointment deletion failed (${response.status})`);
    }
    return true;
  }

  async function persistLocalLeads(nextLeads) {
    if (!userEmail) throw new Error("Your workspace session is unavailable.");
    const response = await fetch(`${API_BASE}/api/leads`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ leads: nextLeads }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload?.error || "Customer record update failed.");
  }

  async function updateLocalLeadAppointments(mutator) {
    if (typeof setLeads !== "function") throw new Error("Customer records are unavailable.");
    const safeCurrent = Array.isArray(leads) ? leads : [];
    const next = mutator(safeCurrent);
    await persistLocalLeads(next);
    setLeads(next);
    return next;
  }

  async function toggleDone(appt) {
    const markingComplete = !appt.done;
    const actionId = `done:${keyFor(appt)}`;
    if (busyAction) return;
    setBusyAction(actionId);
    setActionError("");
    if (isBackend(appt)) {
      const newDone = markingComplete;
      updateDoneOverrides(appt, newDone);
      try {
        await apiUpdateBackend(appt, { done: newDone, title: appt.title });
        removeDoneOverrides(appt);
        await fetchBackend();
        ping("appointments:changed");
        if (newDone) openVisitNote({ ...appt, done: true });
      } catch (error) {
        rollbackDoneOverrides(appt, !newDone);
        setActionError(error?.message || "The appointment could not be updated.");
      } finally {
        setBusyAction("");
      }
      return;
    }
    try {
      await updateLocalLeadAppointments((prev) =>
        prev.map((l) => {
          if (String(l.id) !== String(appt.lead.id)) return l;
          return {
            ...l,
            appointments: (l.appointments || []).map((x) =>
              String(x._localKey || `${l.id}|${x.title}|${x.date}|${x.time || ""}`) ===
              String(appt._localKey)
                ? { ...x, done: !x.done }
                : x
            ),
          };
        })
      );
      ping("appointments:changed");
      if (markingComplete) openVisitNote({ ...appt, done: true });
    } catch (error) {
      setActionError(error?.message || "The appointment could not be updated.");
    } finally {
      setBusyAction("");
    }
  }

  function openVisitNote(appt) {
    setNoteAppointment(appt);
    setVisitNote({
      outcome: "Completed",
      details: "",
      preferences: "",
      followUp: "",
      rebook: "",
    });
  }

  async function saveVisitNote() {
    if (!noteAppointment) return;
    const capturedAt = new Date().toISOString();
    const lines = [
      `Visit outcome: ${visitNote.outcome}`,
      visitNote.details && `Service notes: ${visitNote.details.trim()}`,
      visitNote.preferences && `Customer preferences: ${visitNote.preferences.trim()}`,
      visitNote.followUp && `Follow-up: ${visitNote.followUp.trim()}`,
      visitNote.rebook && `Suggested rebook: ${visitNote.rebook}`,
    ].filter(Boolean);
    const summary = lines.join("\n");
    if (!summary) return;

    setNoteSaving(true);
    setActionError("");
    try {
      if (isBackend(noteAppointment)) {
        const previous = String(noteAppointment.notes || "").trim();
        await apiUpdateBackend(noteAppointment, {
          done: true,
          title: noteAppointment.title,
          notes: [previous, summary].filter(Boolean).join("\n\n"),
        });
      }

      await updateLocalLeadAppointments((prev) =>
        prev.map((lead) => {
          if (String(lead.id) !== String(noteAppointment.lead?.id)) return lead;
          const prior = String(lead.notes || "").trim();
          const updated = {
            ...lead,
            notes: [prior, summary].filter(Boolean).join("\n\n"),
            last_appointment_note: summary,
            last_appointment_note_at: capturedAt,
            rebook_recommended_for: visitNote.rebook || lead.rebook_recommended_for || "",
          };
          if (!isBackend(noteAppointment)) {
            updated.appointments = (lead.appointments || []).map((item) => {
              const localKey = item._localKey || `${lead.id}|${item.title}|${item.date}|${item.time || ""}`;
              return String(localKey) === String(noteAppointment._localKey)
                ? { ...item, done: true, notes: [item.notes, summary].filter(Boolean).join("\n\n") }
                : item;
            });
          }
          return updated;
        })
      );
      await fetchBackend();
      ping("appointments:changed");
      setNoteAppointment(null);
    } catch (error) {
      alert(error?.message || "Could not save the visit note.");
    } finally {
      setNoteSaving(false);
    }
  }

  async function reschedule(appt, days) {
    const actionId = `reschedule:${keyFor(appt)}`;
    if (busyAction) return;
    setBusyAction(actionId);
    setActionError("");
    if (isBackend(appt)) {
      const newDate = addDaysToDateKey(appt.date, days);
      const newTime = appt.time;
      const iso = withSeconds(newDate, newTime);
      if (!iso) {
        setActionError("This appointment has an invalid date or time.");
        setBusyAction("");
        return;
      }
      try {
        updateTimeOverrides(appt, iso);
        await apiUpdateBackend(appt, {
          appointment_time: iso,
          timezone: appt.timeZone || effectiveTimezone,
          title: appt.title,
          notes: appt.notes || "",
        });
        removeTimeOverrides(appt);
        await fetchBackend();
        ping("appointments:changed");
      } catch (error) {
        removeTimeOverrides(appt);
        setActionError(error?.message || "The appointment could not be rescheduled.");
      } finally {
        setBusyAction("");
      }
      return;
    }
    try {
      await updateLocalLeadAppointments((prev) =>
        prev.map((l) => {
          if (String(l.id) !== String(appt.lead.id)) return l;
          return {
            ...l,
            appointments: (l.appointments || []).map((x) => {
              const localKey = x._localKey || `${l.id}|${x.title}|${x.date}|${x.time || ""}`;
              if (String(localKey) !== String(appt._localKey)) return x;
              return { ...x, date: addDaysToDateKey(x.date, days) || x.date };
            }),
          };
        })
      );
      ping("appointments:changed");
    } catch (error) {
      setActionError(error?.message || "The appointment could not be rescheduled.");
    } finally {
      setBusyAction("");
    }
  }

  async function remove(appt) {
    if (!window.confirm(`Delete “${appt.title || "Appointment"}”? This cannot be undone.`)) return;
    const actionId = `delete:${keyFor(appt)}`;
    if (busyAction) return;
    setBusyAction(actionId);
    setActionError("");
    if (isBackend(appt)) {
      hideOverrides(appt);
      try {
        await apiDeleteBackend(appt);
        await fetchBackend();
        ping("appointments:changed");
      } catch (error) {
        unhideOverrides(appt);
        setActionError(error?.message || "The appointment could not be deleted.");
      } finally {
        setBusyAction("");
      }
      return;
    }
    try {
      await updateLocalLeadAppointments((prev) =>
        prev.map((l) =>
          String(l.id) === String(appt.lead.id)
            ? {
                ...l,
                appointments: (l.appointments || []).filter((x) => {
                  const localKey = x._localKey || `${l.id}|${x.title}|${x.date}|${x.time || ""}`;
                  return String(localKey) !== String(appt._localKey);
                }),
              }
            : l
        )
      );
      ping("appointments:changed");
    } catch (error) {
      setActionError(error?.message || "The appointment could not be deleted.");
    } finally {
      setBusyAction("");
    }
  }

  function beginEdit(appt) {
    setForm({
      leadId: String(appt.lead.id || ""),
      title: appt.title,
      date: appt.date,
      time: appt.time || "",
      notes: appt.notes || "",
    });
    setEditing(appt);
    setShowModal(true);
  }

  async function handleSave() {
    const { leadId, title, date, time, notes } = form;
    const appointmentTime = withSeconds(date, time);
    if (!leadId || !title.trim() || !date || !time || !appointmentTime) {
      setActionError("Choose a customer, title, valid date, and time.");
      return;
    }

    setSaving(true);
    setActionError("");
    let saved = false;

    try {
      if (editing && editing._backend) {
        const iso = appointmentTime;

        updateTimeOverrides(editing, iso);

        await apiUpdateBackend(editing, {
          appointment_time: iso,
          timezone: editing.timeZone || effectiveTimezone,
          title: title.trim(),
          notes: notes || "",
        });
        removeTimeOverrides(editing);
        await fetchBackend();
        ping("appointments:changed");
        saved = true;
      } else if (editing) {
        await updateLocalLeadAppointments((prev) => {
          return prev.map((l) => {
            const filtered = (l.appointments || []).filter((x) => {
              const localKey =
                x._localKey || `${l.id}|${x.title}|${x.date}|${x.time || ""}`;
              return String(localKey) !== String(editing._localKey);
            });
            if (String(l.id) !== String(leadId)) {
              return filtered.length === (l.appointments || []).length
                ? l
                : { ...l, appointments: filtered };
            }
            return {
              ...l,
              appointments: [...filtered, {
                _localKey: editing._localKey,
                title: title.trim(),
                date,
                time,
                notes,
                done: !!editing.done,
              }],
            };
          });
        });

        ping("appointments:changed");
        saved = true;
      } else {
        const selectedLead = (leads || []).find((l) => String(l.id) === String(leadId));
        if (!selectedLead) {
          throw new Error("Selected lead not found.");
        }

        const fullName = String(selectedLead.name || "").trim();
        const parts = fullName ? fullName.split(/\s+/) : [];
        const leadFirstName =
          parts[0] || selectedLead.first_name || selectedLead.firstName || "Client";
        const leadLastName =
          parts.length > 1
            ? parts.slice(1).join(" ")
            : selectedLead.last_name || selectedLead.lastName || "";

        const appointmentPayload = {
          lead_id: selectedLead.id || "",
          lead_email: selectedLead.email || "",
          lead_first_name: leadFirstName,
          lead_last_name: leadLastName,
          lead_full_name: fullName,
          user_name: user?.name || "",
          user_email: userEmail,
          business_name: user?.business || user?.businessType || "",
          appointment_time: appointmentTime,
          timezone: effectiveTimezone,
          appointment_location: selectedLead.location || user?.location || "",
          duration: 30,
          notes: notes || "",
          status: "scheduled",
          title: title.trim(),
        };

        const res = await fetch(
          `${API_BASE}/api/appointments/${encodeURIComponent(userEmail)}`,
          {
            method: "POST",
            credentials: "include",
            headers: {
              "Content-Type": "application/json",
              Accept: "application/json",
            },
            body: JSON.stringify(appointmentPayload),
          }
        );

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err?.error || "Failed to create appointment.");
        }

        await fetchBackend();
        ping("appointments:changed");
        saved = true;
      }
    } catch (err) {
      if (editing?._backend) removeTimeOverrides(editing);
      console.error(err);
      setActionError(err?.message || "Failed to save appointment.");
    } finally {
      setSaving(false);
      if (saved) {
        setShowModal(false);
        setEditing(null);
        setForm({ leadId: "", title: "", date: "", time: "", notes: "" });
      }
    }
  }

  const stat = {
    overdue: buckets.overdue.length,
    today: buckets.today.length,
    week: buckets.next7.length,
    upcoming:
      buckets.overdue.length +
      buckets.today.length +
      buckets.next7.length +
      buckets.later.length,
    done: buckets.done.length,
  };

  return (
    <div
      className="appointments-page"
      style={{
        padding: "28px",
        background: BG,
        minHeight: "100vh",
        boxSizing: "border-box",
      }}
    >
      <div
        className="appointments-heading"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          alignItems: "center",
          gap: 16,
          marginBottom: 18,
        }}
      >
        <div>
          <div
            style={{
              color: TEXT,
              fontWeight: 900,
              fontSize: "2.05em",
              letterSpacing: "-0.5px",
            }}
          >
            Appointments
          </div>
          <div style={{ color: SUBTEXT, marginTop: 5, fontSize: 13 }}>
            Manage scheduled work, track overdue items, and keep appointment changes synced.
          </div>
        </div>

        <button
          onClick={() => {
            setShowModal(true);
            setEditing(null);
            setActionError("");
            setForm(freshAppointmentForm());
          }}
          style={{
            background: GOLD,
            color: "#191919",
            border: "none",
            borderRadius: 10,
            fontWeight: 800,
            padding: "10px 16px",
            fontSize: "1.02em",
            cursor: "pointer",
            boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <FaPlus /> Add Appointment
        </button>
      </div>

      {(appointmentsError || actionError) && (
        <div className="appointments-error" role="alert">
          <span>{actionError || appointmentsError || "Appointments could not be refreshed. Your last loaded schedule remains visible."}</span>
          <button
            type="button"
            disabled={loadingAppointments}
            onClick={() => {
              setActionError("");
              fetchBackend();
            }}
          >
            {loadingAppointments ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}

      {!appointmentsError && loadingAppointments && backendWorkspace !== userEmail && (
        <div className="appointments-loading" role="status">Loading appointments…</div>
      )}

      <div
        className="appointments-toolbar"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 18,
          alignItems: "center",
        }}
      >
        <div
          className="appointments-search"
          style={{
            display: "flex",
            alignItems: "center",
            background: CARD,
            borderRadius: 10,
            padding: "0 12px",
            border: `1px solid ${BORDER}`,
          }}
        >
          <FaSearch color={GOLD} style={{ marginRight: 8 }} />
          <input
            placeholder="Search by title, lead, email, date..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              background: "transparent",
              border: "none",
              outline: "none",
              color: TEXT,
              fontSize: "1.02em",
              padding: "10px 0",
              width: 280,
            }}
          />
        </div>

        <div
          style={{
            display: "inline-flex",
            border: `1px solid ${BORDER}`,
            borderRadius: 10,
            overflow: "hidden",
          }}
        >
          <button
            onClick={() => setShowCompleted(false)}
            style={{
              background: !showCompleted ? GOLD : "transparent",
              color: !showCompleted ? "#191919" : TEXT,
              padding: "8px 14px",
              fontWeight: 900,
              border: "none",
              cursor: "pointer",
            }}
          >
            Active
          </button>
          <button
            onClick={() => setShowCompleted(true)}
            style={{
              background: showCompleted ? GOLD : "transparent",
              color: showCompleted ? "#191919" : TEXT,
              padding: "8px 14px",
              fontWeight: 900,
              border: "none",
              cursor: "pointer",
            }}
          >
            Completed
          </button>
        </div>
      </div>

      <div
        className="appointments-stats"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
          marginBottom: 18,
        }}
      >
        <StatCard icon={<FaExclamationTriangle />} label="Overdue" value={stat.overdue} color={RED} />
        <StatCard icon={<FaSun />} label="Today" value={stat.today} color={GOLD} />
        <StatCard icon={<FaCalendarWeek />} label="Next 7 days" value={stat.week} color={GREEN} />
        <StatCard icon={<FaForward />} label="All upcoming" value={stat.upcoming} color={TEXT} />
        <StatCard icon={<FaCheckCircle />} label="Completed" value={stat.done} color={GREEN} />
      </div>

      {!loadingAppointments && !appointmentsError && allAppointments.length === 0 ? (
        <div className="appointments-empty">
          <strong>No appointments yet</strong>
          <span>Add an appointment to start building your schedule.</span>
        </div>
      ) : null}

      {!showCompleted ? (
        <>
          <Section
            title="Overdue"
            color={RED}
            subtitle="Appointments that should already have been handled"
            items={buckets.overdue}
            renderItem={(a) => (
              <AppointmentCard
                appt={a}
                onDone={() => toggleDone(a)}
                onEdit={() => beginEdit(a)}
                onDelete={() => remove(a)}
                onResched={(d) => reschedule(a, d)}
                disabled={!!busyAction}
              />
            )}
          />

          <Section
            title="Today"
            color={GOLD}
            subtitle="Appointments scheduled for today"
            items={buckets.today}
            renderItem={(a) => (
              <AppointmentCard
                appt={a}
                onDone={() => toggleDone(a)}
                onEdit={() => beginEdit(a)}
                onDelete={() => remove(a)}
                onResched={(d) => reschedule(a, d)}
                disabled={!!busyAction}
              />
            )}
          />

          <Section
            title="Next 7 Days"
            color={GREEN}
            subtitle="Upcoming appointments this week"
            items={buckets.next7}
            renderItem={(a) => (
              <AppointmentCard
                appt={a}
                onDone={() => toggleDone(a)}
                onEdit={() => beginEdit(a)}
                onDelete={() => remove(a)}
                onResched={(d) => reschedule(a, d)}
                disabled={!!busyAction}
              />
            )}
          />

          <Section
            title="Later"
            color={SUBTEXT}
            subtitle="Future appointments beyond 7 days"
            items={buckets.later}
            renderItem={(a) => (
              <AppointmentCard
                appt={a}
                onDone={() => toggleDone(a)}
                onEdit={() => beginEdit(a)}
                onDelete={() => remove(a)}
                onResched={(d) => reschedule(a, d)}
                disabled={!!busyAction}
              />
            )}
          />
        </>
      ) : (
        <Section
          title="Completed"
          color={GREEN}
          subtitle="Finished appointments"
          items={[...buckets.done].sort((a, b) => b.sortKey - a.sortKey)}
          renderItem={(a) => (
            <AppointmentCard
              appt={a}
              onDone={() => toggleDone(a)}
              onEdit={() => beginEdit(a)}
              onDelete={() => remove(a)}
              onResched={(d) => reschedule(a, d)}
              disabled={!!busyAction}
            />
          )}
        />
      )}

      {showModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "#000a",
            zIndex: 99,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div
            className="appointments-modal-card"
            style={{
              background: CARD,
              borderRadius: 18,
              padding: "28px 30px",
              minWidth: 420,
              maxWidth: 560,
              width: "92%",
              boxShadow: "0 2px 22px rgba(0,0,0,0.5)",
              border: `2px solid ${GOLD}`,
            }}
          >
            <h3 style={{ color: GOLD, fontWeight: 900, marginBottom: 16 }}>
              {editing ? "Edit Appointment" : "Add Appointment"}
            </h3>

            <div style={{ marginBottom: 14 }}>
              <label
                style={{
                  color: TEXT,
                  marginRight: 8,
                  fontWeight: 900,
                  display: "block",
                  marginBottom: 6,
                }}
              >
                Lead
              </label>
              <LiveLeadSearch
                leads={leads}
                value={form.leadId}
                onChange={(id) => setForm((f) => ({ ...f, leadId: id }))}
                disabled={!!editing?._backend}
              />
              {editing?._backend ? (
                <div className="appointments-field-hint">The customer cannot be changed after an appointment is created.</div>
              ) : null}
            </div>

            <Field label="Title">
              <input
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                style={inputStyle}
                placeholder="Appointment title"
              />
            </Field>

            <Field label="Date">
              <input
                type="date"
                value={form.date}
                onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                style={inputStyle}
              />
            </Field>

            <Field label="Time">
              <input
                type="time"
                value={form.time}
                onChange={(e) => setForm((f) => ({ ...f, time: e.target.value }))}
                style={inputStyle}
                required
              />
            </Field>

            <div className="appointments-timezone-note">
              Times are saved in {effectiveTimezone.replace(/_/g, " ")}.
            </div>

            <Field label="Notes">
              <textarea
                rows={4}
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                style={{
                  ...inputStyle,
                  resize: "vertical",
                  lineHeight: 1.45,
                }}
                placeholder="Optional appointment notes..."
              />
            </Field>

            <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
              <button
                onClick={handleSave}
                disabled={saving}
                style={{
                  background: GOLD,
                  color: "#232323",
                  fontWeight: 900,
                  border: "none",
                  borderRadius: 8,
                  padding: "11px 16px",
                  cursor: "pointer",
                  flex: 1,
                  opacity: saving ? 0.75 : 1,
                }}
              >
                {saving ? "Saving..." : editing ? "Save" : "Add"}
              </button>
              <button
                onClick={() => {
                  setShowModal(false);
                  setEditing(null);
                }}
                style={{
                  background: "transparent",
                  color: TEXT,
                  fontWeight: 900,
                  border: `1.3px solid ${GOLD}`,
                  borderRadius: 8,
                  padding: "11px 16px",
                  cursor: "pointer",
                  flex: 1,
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {noteAppointment && (
        <div className="visit-note-backdrop" role="dialog" aria-modal="true" aria-label="Add post-appointment note">
          <div className="visit-note-sheet">
            <div className="visit-note-handle" aria-hidden />
            <div className="visit-note-kicker">Visit complete</div>
            <h3>How did it go with {getLeadDisplayName(noteAppointment.lead)}?</h3>
            <p>Capture the useful details now. They will be added to the customer record and appointment.</p>

            <div className="visit-note-outcomes" aria-label="Visit outcome">
              {["Completed", "Needs follow-up", "No-show"].map((outcome) => (
                <button
                  type="button"
                  key={outcome}
                  className={visitNote.outcome === outcome ? "active" : ""}
                  onClick={() => setVisitNote((current) => ({ ...current, outcome }))}
                >
                  {outcome}
                </button>
              ))}
            </div>

            <label>
              What was done?
              <textarea
                rows={3}
                value={visitNote.details}
                onChange={(event) => setVisitNote((current) => ({ ...current, details: event.target.value }))}
                placeholder="Service provided, result, important context…"
              />
            </label>
            <label>
              Preferences to remember
              <input
                value={visitNote.preferences}
                onChange={(event) => setVisitNote((current) => ({ ...current, preferences: event.target.value }))}
                placeholder="Style, product, timing, communication preference…"
              />
            </label>
            <div className="visit-note-grid">
              <label>
                Follow-up
                <input
                  value={visitNote.followUp}
                  onChange={(event) => setVisitNote((current) => ({ ...current, followUp: event.target.value }))}
                  placeholder="Call tomorrow, send care tips…"
                />
              </label>
              <label>
                Recommend rebooking
                <input
                  type="date"
                  value={visitNote.rebook}
                  onChange={(event) => setVisitNote((current) => ({ ...current, rebook: event.target.value }))}
                />
                <span className="visit-note-recommendation">
                  Suggested for your business: {suggestedRebookWeeks} weeks
                  <button
                    type="button"
                    onClick={() => setVisitNote((current) => ({
                      ...current,
                       rebook: dateWeeksFromNow(suggestedRebookWeeks, effectiveTimezone),
                    }))}
                  >
                    Use suggestion
                  </button>
                </span>
              </label>
            </div>

            <div className="visit-note-actions">
              <button type="button" className="secondary" onClick={() => setNoteAppointment(null)}>Skip for now</button>
              <button type="button" className="primary" disabled={noteSaving} onClick={saveVisitNote}>
                {noteSaving ? "Saving…" : "Save to customer"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ===== UI Bits ===== */
function StatCard({ icon, label, value, color }) {
  return (
    <div
      style={{
        background: CARD,
        border: `1px solid ${BORDER}`,
        borderRadius: 14,
        padding: "13px 14px",
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: 12,
          display: "grid",
          placeItems: "center",
          background: SOFT,
          color,
          fontSize: 17,
          flex: "0 0 40px",
        }}
      >
        {icon}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ color: SUBTEXT, fontWeight: 800, fontSize: 12 }}>{label}</div>
        <div style={{ color: TEXT, fontWeight: 900, fontSize: 20 }}>{value}</div>
      </div>
    </div>
  );
}

function Section({ title, color, subtitle, items, renderItem }) {
  if (!items || items.length === 0) return null;

  return (
    <div style={{ marginTop: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          marginBottom: 10,
          paddingLeft: 2,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: color,
            display: "inline-block",
          }}
        />
        <div style={{ color: TEXT, fontWeight: 900 }}>{title}</div>
        <div style={{ color: SUBTEXT, fontWeight: 800, fontSize: 12 }}>({items.length})</div>
        {subtitle ? (
          <div style={{ color: SUBTEXT, fontSize: 12, marginLeft: 4 }}>{subtitle}</div>
        ) : null}
      </div>

      <div
        className="appointments-card-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))",
          gap: 14,
        }}
      >
        {items.map((a) => (
          <div key={keyFor(a)}>{renderItem(a)}</div>
        ))}
      </div>
    </div>
  );
}

function AppointmentCard({ appt, onDone, onEdit, onDelete, onResched, disabled = false }) {
  const meta = statusMeta(appt);

  return (
    <div
      className="appointment-card"
      style={{
        background: CARD,
        border: `1px solid ${BORDER}`,
        borderLeft: `6px solid ${meta.color}`,
        borderRadius: 14,
        padding: "15px 16px",
        minHeight: 112,
        display: "flex",
        gap: 14,
        alignItems: "center",
        boxShadow: "0 2px 18px rgba(0,0,0,0.25)",
        opacity: appt.done ? 0.7 : 1,
      }}
    >
      <div
        style={{
          width: 42,
          height: 42,
          borderRadius: 12,
          display: "grid",
          placeItems: "center",
          background: SOFT,
          flex: "0 0 42px",
        }}
      >
        <FaCalendarAlt color={GOLD} />
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            color: TEXT,
            fontWeight: 900,
            lineHeight: 1.15,
            fontSize: 16,
            wordBreak: "break-word",
          }}
        >
          {appt.title}
        </div>

        <div
          style={{
            color: SUBTEXT,
            marginTop: 4,
            fontWeight: 700,
            fontSize: 13,
          }}
        >
          {appt.lead?.name || getLeadDisplayName(appt.lead)}
          {appt.lead?.email ? (
            <span style={{ marginLeft: 8, color: "#7f8a92", fontWeight: 600 }}>
              {appt.lead.email}
            </span>
          ) : null}
        </div>

        <div
          style={{
            color: meta.color,
            fontWeight: 800,
            marginTop: 7,
            display: "flex",
            gap: 10,
            alignItems: "center",
            flexWrap: "wrap",
            fontSize: 13,
          }}
        >
          <span>{appt.time ? `${monthLabel(appt.date)} • ${appt.time}` : monthLabel(appt.date)}</span>
          <span
            style={{
              background: "rgba(255,255,255,0.04)",
              border: `1px solid ${BORDER}`,
              color: meta.color,
              borderRadius: 999,
              padding: "3px 8px",
              fontSize: 11,
              fontWeight: 900,
            }}
          >
            {meta.label}
          </span>
        </div>

        {appt.notes ? (
          <div
            style={{
              color: SUBTEXT,
              marginTop: 6,
              fontSize: 13,
              lineHeight: 1.45,
              wordBreak: "break-word",
            }}
          >
            {appt.notes}
          </div>
        ) : null}

        {!appt.done && (
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <Chip icon={<FaClock />} onClick={() => onResched(1)} disabled={disabled}>
              +1 day
            </Chip>
            <Chip onClick={() => onResched(3)} disabled={disabled}>+3 days</Chip>
            <Chip onClick={() => onResched(7)} disabled={disabled}>+1 week</Chip>
          </div>
        )}
      </div>

      <div className="appointment-card-actions" style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
        <button
          onClick={onDone}
          disabled={disabled}
          style={{
            background: appt.done ? GREEN : "transparent",
            color: appt.done ? "#172119" : GOLD,
            border: `2px solid ${GOLD}`,
            borderRadius: 8,
            padding: "7px 12px",
            fontWeight: 900,
            cursor: "pointer",
          }}
        >
          {appt.done ? "Undo" : "Done"}
        </button>

        <button
          onClick={onEdit}
          disabled={disabled}
          style={{
            background: "transparent",
            color: GOLD,
            border: `1.5px solid ${GOLD}`,
            borderRadius: 8,
            padding: "7px 10px",
            fontWeight: 800,
            cursor: "pointer",
          }}
        >
          Edit
        </button>

        <button
          onClick={onDelete}
          disabled={disabled}
          style={{
            background: "transparent",
            color: RED,
            border: `1.5px solid ${RED}`,
            borderRadius: 8,
            padding: "7px 10px",
            fontWeight: 800,
            cursor: "pointer",
          }}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function Chip({ children, onClick, icon, disabled = false }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: SOFT,
        color: TEXT,
        border: `1px solid ${BORDER}`,
        borderRadius: 999,
        padding: "5px 10px",
        fontWeight: 800,
        fontSize: 12,
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
    >
      {icon || null}
      {children}
    </button>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label
        style={{
          color: TEXT,
          marginRight: 8,
          fontWeight: 900,
          display: "block",
          marginBottom: 6,
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}

const inputStyle = {
  padding: "10px 12px",
  borderRadius: 8,
  fontWeight: 700,
  fontSize: "1.02em",
  background: BG,
  color: TEXT,
  border: `1.5px solid ${BORDER}`,
  width: "100%",
  boxSizing: "border-box",
};

function LiveLeadSearch({ leads, value, onChange, disabled = false }) {
  const [search, setSearch] = useState("");

  const selected = leads.find((l) => String(l.id) === String(value));

  const filtered = !search
    ? leads
    : leads.filter(
        (l) =>
          normText(l.name || "").includes(normText(search)) ||
          normText(l.email || "").includes(normText(search))
      );

  return (
    <>
      <input
        type="text"
        placeholder="Search lead name or email..."
        value={selected ? selected.name : search}
        onChange={(e) => {
          setSearch(e.target.value);
          onChange("");
        }}
        disabled={disabled}
        style={inputStyle}
      />

      <div
        style={{
          maxHeight: 160,
          overflowY: "auto",
          border: `1px solid ${BORDER}`,
          borderRadius: 8,
          background: BG,
          marginTop: 6,
        }}
      >
        {filtered.length === 0 && (
          <div style={{ color: GOLD, padding: 10, fontWeight: 700 }}>No leads found.</div>
        )}

        {filtered.map((l) => {
          const active = value === String(l.id);
          return (
            <div
              key={l.id}
              style={{
                padding: "9px 12px",
                color: active ? "#232323" : TEXT,
                background: active ? GOLD : "transparent",
                cursor: "pointer",
                fontWeight: 900,
              }}
              onClick={() => {
                if (disabled) return;
                onChange(String(l.id));
                setSearch(l.name || "");
              }}
            >
              {l.name || "Unnamed Lead"}
              <span
                style={{
                  color: active ? "#232323" : GOLD,
                  marginLeft: 7,
                  fontWeight: 700,
                  fontSize: 12,
                }}
              >
                {l.email}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}
