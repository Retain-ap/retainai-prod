// src/components/Calendar.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";

/* === THEME (aligned with Drawer / Analytics) === */
const BG = "#181a1b";
const CARD = "#232323";
const SOFT = "#1e2326";
const BORDER = "#2b2f33";
const TEXT = "#f3f4f5";
const SUBTEXT = "#9aa3ab";
const GOLD = "#f7cb53";

const APPT = "#30b46c";
const NOTE = "#ffd966";
const GOOGLE = "#4885ed";
const BDAY = "#f7cb53";

/* --- API base --- */
const API_BASE =
  (process.env.REACT_APP_API_BASE && process.env.REACT_APP_API_BASE.trim()) ||
  (process.env.REACT_APP_API_URL && process.env.REACT_APP_API_URL.trim()) ||
  window.location.origin.replace(/\/$/, "");

/* --- Helpers --- */
function getLocalISO(dateObj) {
  const y = dateObj.getFullYear();
  const m = String(dateObj.getMonth() + 1).padStart(2, "0");
  const d = String(dateObj.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function getCalendarGrid(year, month) {
  const first = new Date(year, month, 1);
  const daysIn = new Date(year, month + 1, 0).getDate();
  const start = first.getDay();
  const days = [];

  for (let i = 0; i < start; i++) days.push(null);
  for (let d = 1; d <= daysIn; d++) days.push(new Date(year, month, d));
  while (days.length % 7 !== 0) days.push(null);
  while (days.length < 42) days.push(null);

  return days;
}

function parseDateSafe(v) {
  if (!v) return null;
  try {
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

/* === Local storage keys (shared with Appointments) === */
const LS_KEYS = (email) => ({
  hidden: `appt_hidden_${email || "anon"}`,
  done: `appt_done_${email || "anon"}`,
  time: `appt_time_${email || "anon"}`,
  slots: `appt_slots_${email || "anon"}`,
  notes: `calendar_notes_${email || "anon"}`,
});

const loadJSON = (k, fallback = {}) => {
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

/** Match Appointments.jsx RID logic */
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

const safe = (v) => (v == null ? "" : String(v));

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

const hasRealId = (r) => Boolean(getRealIdField(r));
const getRID = (r) => String(r?._rid ?? r?._client_uid ?? getRealIdField(r) ?? "");

/** Assign stable client RIDs using the same slot map as Appointments.jsx */
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

  const uuid = () =>
    "xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const n = (Math.random() * 16) | 0;
      const v = c === "x" ? n : (n & 0x3) | 0x8;
      return v.toString(16);
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

/** Apply overrides (hide, done flag, rescheduled time) */
function applyOverrides(rows = [], email) {
  const K = LS_KEYS(email);
  const hidden = loadJSON(K.hidden, {});
  const doneMap = loadJSON(K.done, {});
  const timeMap = loadJSON(K.time, {});

  return (rows || [])
    .map((r) => {
      const id = getRID(r);
      if (!id) return r;

      let out = r;
      if (timeMap[id]) out = { ...out, appointment_time: timeMap[id] };
      if (typeof doneMap[id] === "boolean") out = { ...out, done: doneMap[id] };
      return out;
    })
    .filter((r) => !hidden[getRID(r)]);
}

// Normalize backend appointment using LOCAL time
function normalizeAppt(appt) {
  const dt = parseDateSafe(appt?.appointment_time);
  if (!dt) return null;

  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const d = String(dt.getDate()).padStart(2, "0");
  const hh = String(dt.getHours()).padStart(2, "0");
  const mm = String(dt.getMinutes()).padStart(2, "0");

  return {
    type: "appointment",
    date: `${y}-${m}-${d}`,
    time: `${hh}:${mm}`,
    title: appt.title || appt.lead_first_name || appt.business_name || "Appointment",
    notes: appt.notes || "",
    ...appt,
  };
}

/** Normalize external events prop from parent */
function normalizeExternalEvent(ev) {
  if (!ev) return null;

  // Appointment-like item
  if (ev.type === "appointment" || ev.appointment_time || ev.date) {
    if (ev.appointment_time) {
      const normalized = normalizeAppt(ev);
      if (normalized) return normalized;
    }

    if (ev.date) {
      return {
        type: ev.type === "note" ? "note" : "appointment",
        title: ev.title || "Appointment",
        date: ev.date,
        time: ev.time || "",
        notes: ev.notes || "",
        ...ev,
      };
    }
  }

  // Note-like item
  if (ev.type === "note") {
    return {
      type: "note",
      title: ev.title || "Note",
      date: ev.date,
      time: ev.time || "",
      notes: ev.notes || "",
      ...ev,
    };
  }

  return null;
}

function formatGoogleEventTime(ev) {
  if (!ev) return "";

  if (ev.start?.date && !ev.start?.dateTime) {
    return "All day";
  }

  if (ev.start?.dateTime) {
    const s = new Date(ev.start.dateTime);
    if (ev.end?.dateTime) {
      const e = new Date(ev.end.dateTime);
      return `${s.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })} - ${e.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })}`;
    }

    return s.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  return "";
}

/* --- Birthday helpers (year-agnostic) --- */
function parseBirthdayStr(s) {
  if (!s) return null;
  const t = String(s).trim();

  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) {
    return { month: Number(t.slice(5, 7)), day: Number(t.slice(8, 10)) };
  }

  if (/^\d{2}\/\d{2}(\/\d{2,4})?$/.test(t)) {
    const [m, d] = t.split("/");
    return { month: Number(m), day: Number(d) };
  }

  return null;
}

function isLeadBirthdayOnDate(lead, dateObj) {
  const bd = parseBirthdayStr(lead?.birthday);
  if (!bd) return false;
  return bd.month === dateObj.getMonth() + 1 && bd.day === dateObj.getDate();
}

function getBirthdayItems(leads, dateObj) {
  return (leads || [])
    .filter((lead) => isLeadBirthdayOnDate(lead, dateObj))
    .map((lead) => ({
      type: "birthday",
      lead,
      title: `${lead.name || lead.email || "Lead"} Birthday`,
      date: getLocalISO(dateObj),
      time: "",
      notes: "",
    }));
}

function dedupeItems(items = []) {
  const seen = new Set();
  const out = [];

  items.forEach((item) => {
    const key =
      item.type === "google"
        ? `google|${item.google?.id || item.google?.summary || ""}|${item.google?.start?.dateTime || item.google?.start?.date || ""}`
        : item.type === "birthday"
        ? `birthday|${item.lead?.email || item.lead?.name || ""}|${item.date || ""}`
        : `${item.type}|${item.title || ""}|${item.date || ""}|${item.time || ""}|${item.notes || ""}|${item.id || item._rid || ""}`;

    if (seen.has(key)) return;
    seen.add(key);
    out.push(item);
  });

  return out;
}

function getCellEvents(dateObj, externalEvents, leads, googleEvents, appointments, localNotes) {
  const dayISO = getLocalISO(dateObj);
  const cellEvents = [];

  (appointments || []).forEach((a) => {
    const norm = normalizeAppt(a);
    if (norm && norm.date === dayISO) cellEvents.push(norm);
  });

  (externalEvents || []).forEach((ev) => {
    const norm = normalizeExternalEvent(ev);
    if (norm && norm.date === dayISO) cellEvents.push(norm);
  });

  (localNotes || []).forEach((ev) => {
    if (ev?.date === dayISO) cellEvents.push({ type: "note", ...ev });
  });

  (googleEvents || []).forEach((ev) => {
    const evStart = ev.start?.dateTime || ev.start?.date;
    if (evStart && evStart.slice(0, 10) === dayISO) {
      cellEvents.push({ type: "google", google: ev });
    }
  });

  getBirthdayItems(leads, dateObj).forEach((b) => cellEvents.push(b));

  return dedupeItems(cellEvents);
}

function getPanelEvents(dateObj, externalEvents, leads, googleEvents, appointments, localNotes) {
  if (!dateObj) return [];

  const dayISO = getLocalISO(dateObj);
  const out = [];

  (appointments || []).forEach((a) => {
    const norm = normalizeAppt(a);
    if (norm && norm.date === dayISO) out.push(norm);
  });

  (externalEvents || []).forEach((ev) => {
    const norm = normalizeExternalEvent(ev);
    if (norm && norm.date === dayISO) out.push(norm);
  });

  (localNotes || []).forEach((ev) => {
    if (ev?.date === dayISO) out.push({ type: "note", ...ev });
  });

  (googleEvents || []).forEach((ev) => {
    const s = ev.start?.dateTime || ev.start?.date;
    if (s && s.slice(0, 10) === dayISO) out.push({ type: "google", google: ev });
  });

  getBirthdayItems(leads, dateObj).forEach((b) => out.push(b));

  const deduped = dedupeItems(out);

  return deduped.sort((a, b) => {
    const ta = a.type === "google" ? formatGoogleEventTime(a.google) : a.time || "";
    const tb = b.type === "google" ? formatGoogleEventTime(b.google) : b.time || "";
    return String(ta).localeCompare(String(tb));
  });
}

/* tiny count pill for day cells */
function CountPill({ color, count, title, icon }) {
  if (!count) return null;

  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 4,
        minWidth: 18,
        height: 18,
        padding: "0 6px",
        borderRadius: 9,
        fontSize: 11,
        fontWeight: 900,
        background: color,
        color: "#111",
        lineHeight: 1,
      }}
    >
      {icon ? <span style={{ fontSize: 12 }}>{icon}</span> : null}
      {count}
    </span>
  );
}

export default function Calendar({
  user,
  leads = [],
  events = [],
  googleEvents = [],
  selectedDate,
  setSelectedDate,
  onDayClick,
}) {
  const today = new Date();
  const [month, setMonth] = useState(today.getMonth());
  const [year, setYear] = useState(today.getFullYear());
  const [showAddEvent, setShowAddEvent] = useState(false);
  const [addEventDate, setAddEventDate] = useState(null);

  // local note events only
  const [localNotes, setLocalNotes] = useState([]);

  // backend appointments
  const [appointments, setAppointments] = useState([]);

  // same RID slot map as Appointments.jsx
  const [slotMap, setSlotMap] = useState({});
  const slotMapRef = useRef({});

  // bump when overrides change
  const [overrideBump, setOverrideBump] = useState(0);

  useEffect(() => {
    const savedSlots = loadJSON(LS_KEYS(user?.email).slots, {});
    slotMapRef.current = savedSlots;
    setSlotMap(savedSlots);

    const savedNotes = loadJSON(LS_KEYS(user?.email).notes, []);
    setLocalNotes(Array.isArray(savedNotes) ? savedNotes : []);
  }, [user?.email]);

  const fetchAppointments = async () => {
    if (!user?.email) return;
    try {
      const r = await fetch(`${API_BASE}/api/appointments/${encodeURIComponent(user.email)}`, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const j = await r.json().catch(() => ({}));
      setAppointments(Array.isArray(j?.appointments) ? j.appointments : []);
    } catch {
      setAppointments([]);
    }
  };

  useEffect(() => {
    fetchAppointments();

    const onChanged = () => fetchAppointments();
    const onOverrides = () => setOverrideBump((x) => x + 1);

    window.addEventListener("appointments:changed", onChanged);
    window.addEventListener("appointments:overrides-updated", onOverrides);

    return () => {
      window.removeEventListener("appointments:changed", onChanged);
      window.removeEventListener("appointments:overrides-updated", onOverrides);
    };
  }, [user?.email]);

  const assignedAppointments = useMemo(() => {
    const result = assignStableRIDs(appointments || [], slotMapRef.current || {});
    return result;
  }, [appointments]);

  useEffect(() => {
    const oldStr = JSON.stringify(slotMapRef.current || {});
    const newStr = JSON.stringify(assignedAppointments.nextSlots || {});

    if (oldStr !== newStr) {
      slotMapRef.current = assignedAppointments.nextSlots || {};
      setSlotMap(assignedAppointments.nextSlots || {});
      saveJSON(LS_KEYS(user?.email).slots, assignedAppointments.nextSlots || {});
    }
  }, [assignedAppointments.nextSlots, user?.email]);

  const effectiveAppointments = useMemo(
    () => applyOverrides(assignedAppointments.rows, user?.email),
    [assignedAppointments.rows, user?.email, overrideBump]
  );

  const calendarGrid = useMemo(() => getCalendarGrid(year, month), [year, month]);
  const currMonthStr = new Date(year, month).toLocaleString("default", {
    month: "long",
    year: "numeric",
  });

  const dayEvents = useMemo(
    () =>
      getPanelEvents(
        selectedDate,
        events,
        leads,
        googleEvents,
        effectiveAppointments,
        localNotes
      ),
    [selectedDate, events, leads, googleEvents, effectiveAppointments, localNotes]
  );

  function changeMonth(delta) {
    let m = month + delta;
    let y = year;

    if (m < 0) {
      m = 11;
      y -= 1;
    }
    if (m > 11) {
      m = 0;
      y += 1;
    }

    setMonth(m);
    setYear(y);
    setSelectedDate && setSelectedDate(null);
  }

  function handleAddEventClick(dateObj) {
    setAddEventDate(dateObj);
    setShowAddEvent(true);
    setSelectedDate && setSelectedDate(dateObj);
  }

  function handleAddEventSave(newEvent) {
    const next = [
      ...localNotes,
      {
        id: `note_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        title: newEvent.title,
        date: getLocalISO(addEventDate),
        time: newEvent.time,
        notes: newEvent.notes,
        type: "note",
      },
    ];

    setLocalNotes(next);
    saveJSON(LS_KEYS(user?.email).notes, next);
    setShowAddEvent(false);
    setAddEventDate(null);
  }

  function handleCellClick(day) {
    if (!day) return;
    setSelectedDate && setSelectedDate(day);
  }

  function handleCellDoubleClick(day) {
    if (!day) return;
    if (typeof onDayClick === "function") {
      onDayClick(day);
    } else {
      handleAddEventClick(day);
    }
  }

  const googleCountThisMonth = useMemo(() => {
    const currentMonth = `${year}-${String(month + 1).padStart(2, "0")}`;
    return (googleEvents || []).filter((ev) => {
      const s = ev?.start?.dateTime || ev?.start?.date;
      return s && String(s).slice(0, 7) === currentMonth;
    }).length;
  }, [googleEvents, month, year]);

  const apptCountThisMonth = useMemo(() => {
    const currentMonth = `${year}-${String(month + 1).padStart(2, "0")}`;
    return (effectiveAppointments || []).filter((a) => {
      const dt = normalizeAppt(a);
      return dt && dt.date.slice(0, 7) === currentMonth;
    }).length;
  }, [effectiveAppointments, month, year]);

  return (
    <div
      style={{
        padding: "28px",
        background: BG,
        minHeight: "100vh",
        boxSizing: "border-box",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 18 }}>
        {/* Calendar card */}
        <div
          style={{
            background: CARD,
            padding: 22,
            borderRadius: 18,
            minWidth: 630,
            flex: "0 0 650px",
            border: `1px solid ${BORDER}`,
            boxShadow: "0 2px 28px rgba(0,0,0,0.35)",
          }}
        >
          {/* Header */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              marginBottom: 14,
              gap: 18,
            }}
          >
            <div>
              <div style={{ fontWeight: 900, fontSize: 22, color: TEXT }}>Calendar</div>
              <div style={{ color: SUBTEXT, fontSize: 13, marginTop: 4 }}>
                View appointments, Google events, birthdays, and internal notes in one place.
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button onClick={() => changeMonth(-1)} style={monthBtnStyle}>
                &lt;
              </button>
              <span
                style={{
                  fontSize: 18,
                  fontWeight: 900,
                  color: GOLD,
                  minWidth: 170,
                  textAlign: "center",
                }}
              >
                {currMonthStr}
              </span>
              <button onClick={() => changeMonth(1)} style={monthBtnStyle}>
                &gt;
              </button>
            </div>
          </div>

          {/* Mini summary */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
              gap: 10,
              marginBottom: 16,
            }}
          >
            <MiniMetric label="Backend appointments" value={apptCountThisMonth} />
            <MiniMetric label="Google events" value={googleCountThisMonth} />
            <MiniMetric
              label="Birthdays"
              value={(leads || []).filter((lead) => parseBirthdayStr(lead?.birthday)).length}
            />
          </div>

          {/* DOW */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(7, 1fr)",
              gap: 8,
              width: "100%",
              marginBottom: 6,
            }}
          >
            {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
              <div
                key={d}
                style={{
                  textAlign: "center",
                  color: GOLD,
                  fontWeight: 900,
                  fontSize: 14,
                }}
              >
                {d}
              </div>
            ))}
          </div>

          {/* Grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(7, 1fr)",
              gap: 8,
              width: "100%",
              minHeight: 420,
            }}
          >
            {calendarGrid.map((d, i) => {
              if (!d) return <div key={i} />;

              const isToday = d.toDateString() === today.toDateString();
              const isSelected = selectedDate && d.toDateString() === selectedDate.toDateString();

              const evs = getCellEvents(
                d,
                events,
                leads,
                googleEvents,
                effectiveAppointments,
                localNotes
              );

              const counts = evs.reduce(
                (acc, e) => {
                  acc[e.type] = (acc[e.type] || 0) + 1;
                  return acc;
                },
                { appointment: 0, google: 0, note: 0, birthday: 0 }
              );

              const tooltip = [
                counts.appointment
                  ? `${counts.appointment} appointment${counts.appointment > 1 ? "s" : ""}`
                  : null,
                counts.google ? `${counts.google} Google event${counts.google > 1 ? "s" : ""}` : null,
                counts.note ? `${counts.note} note${counts.note > 1 ? "s" : ""}` : null,
                counts.birthday
                  ? `${counts.birthday} birthday${counts.birthday > 1 ? "s" : ""}`
                  : null,
              ]
                .filter(Boolean)
                .join(" • ");

              return (
                <div
                  key={`${d.getTime()}-${i}`}
                  onClick={() => handleCellClick(d)}
                  onDoubleClick={() => handleCellDoubleClick(d)}
                  title={tooltip}
                  style={{
                    minHeight: 72,
                    borderRadius: 14,
                    border: isSelected
                      ? `2px solid ${GOLD}`
                      : isToday
                      ? `2px solid ${TEXT}`
                      : `1px solid ${BORDER}`,
                    background: isSelected ? SOFT : BG,
                    textAlign: "center",
                    cursor: "pointer",
                    paddingTop: 8,
                    boxShadow: isSelected ? "0 2px 16px rgba(247,203,83,0.22)" : "",
                    transition: "all .12s ease",
                  }}
                >
                  <div
                    style={{
                      color: isSelected ? GOLD : TEXT,
                      fontWeight: 900,
                      fontSize: 14,
                      marginBottom: 8,
                    }}
                  >
                    {d.getDate()}
                  </div>

                  <div
                    style={{
                      display: "flex",
                      justifyContent: "center",
                      gap: 6,
                      flexWrap: "wrap",
                      padding: "0 4px",
                    }}
                  >
                    <CountPill color={APPT} count={counts.appointment} title="Appointments" />
                    <CountPill color={GOOGLE} count={counts.google} title="Google events" />
                    <CountPill color={NOTE} count={counts.note} title="Notes" />
                    <CountPill color={BDAY} count={counts.birthday} title="Birthdays" icon="🎂" />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Legend */}
          <div
            style={{
              display: "flex",
              gap: 16,
              marginTop: 14,
              alignItems: "center",
              color: SUBTEXT,
              fontWeight: 800,
              flexWrap: "wrap",
            }}
          >
            <LegendDot color={APPT} label="Appointment" />
            <LegendDot color={NOTE} label="Note" />
            <LegendDot color={GOOGLE} label="Google" outlined />
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span>🎂</span>
              <span style={{ color: SUBTEXT, fontWeight: 800, fontSize: 12 }}>Birthday</span>
            </div>
            <span style={{ color: SUBTEXT, fontSize: 12, marginLeft: "auto" }}>
              Double-click a day to quick add
            </span>
          </div>
        </div>

        {/* Right panel */}
        <div
          style={{
            flex: 1,
            minWidth: 360,
            background: CARD,
            borderRadius: 18,
            padding: "22px 20px",
            color: TEXT,
            border: `1px solid ${BORDER}`,
            boxShadow: "0 2px 28px rgba(0,0,0,0.35)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              marginBottom: 14,
              gap: 12,
            }}
          >
            <div>
              <h3
                style={{
                  fontWeight: 900,
                  fontSize: 18,
                  color: GOLD,
                  margin: 0,
                }}
              >
                {selectedDate
                  ? selectedDate.toLocaleDateString(undefined, {
                      weekday: "long",
                      month: "long",
                      day: "numeric",
                    })
                  : "Select a date"}
              </h3>
              <div style={{ color: SUBTEXT, fontSize: 13, marginTop: 5 }}>
                {selectedDate
                  ? "Daily timeline for CRM activity and Google Calendar events."
                  : "Choose a date to inspect activity."}
              </div>
            </div>

            {selectedDate && (
              <button
                style={{
                  background: GOLD,
                  color: "#191a1d",
                  fontWeight: 900,
                  border: "none",
                  borderRadius: 10,
                  padding: "9px 14px",
                  cursor: "pointer",
                  boxShadow: "0 1.5px 8px rgba(247,203,83,0.3)",
                }}
                onClick={() => handleAddEventClick(selectedDate)}
              >
                + Add Note
              </button>
            )}
          </div>

          {!selectedDate && (
            <EmptyState
              title="Nothing selected"
              text="Pick a day on the calendar to review appointments, Google events, notes, and birthdays."
            />
          )}

          {selectedDate && (!dayEvents || dayEvents.length === 0) && (
            <EmptyState
              title="No events for this day"
              text="This date is currently clear. You can still add an internal note."
            />
          )}

          {selectedDate &&
            dayEvents.map((ev, i) => {
              const eventType = ev.type;
              const icon =
                eventType === "birthday"
                  ? "🎂"
                  : eventType === "google"
                  ? "🗓️"
                  : eventType === "note"
                  ? "📝"
                  : "📅";

              const color =
                eventType === "appointment"
                  ? APPT
                  : eventType === "google"
                  ? GOOGLE
                  : eventType === "birthday"
                  ? GOLD
                  : NOTE;

              const title =
                ev.title || ev.google?.summary || ev.lead?.name || "Calendar Item";

              const subline =
                eventType === "birthday"
                  ? "Birthday"
                  : eventType === "google"
                  ? formatGoogleEventTime(ev.google)
                  : ev.time
                  ? ev.time
                  : "No time set";

              const detail =
                eventType === "google"
                  ? ev.google?.description || ev.google?.location || ""
                  : ev.notes || "";

              return (
                <div
                  key={`${eventType}-${i}-${title}`}
                  style={{
                    background: "#191919",
                    borderRadius: 14,
                    marginBottom: 12,
                    padding: 14,
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 12,
                    borderLeft: `6px solid ${color}`,
                    border: `1px solid ${BORDER}`,
                  }}
                >
                  <span
                    style={{
                      fontSize: 24,
                      color,
                      lineHeight: 1,
                      marginTop: 2,
                    }}
                  >
                    {icon}
                  </span>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        color: TEXT,
                        fontWeight: 900,
                        fontSize: 15,
                        marginBottom: 4,
                      }}
                    >
                      {title}
                    </div>

                    <div
                      style={{
                        color: color === GOLD ? GOLD : GOLD,
                        fontWeight: 800,
                        marginBottom: detail ? 4 : 0,
                        fontSize: 13,
                      }}
                    >
                      {subline}
                    </div>

                    {!!detail && (
                      <div
                        style={{
                          color: SUBTEXT,
                          fontSize: 13,
                          lineHeight: 1.45,
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {detail}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
        </div>
      </div>

      {showAddEvent && (
        <AddEventModal
          onSave={handleAddEventSave}
          onClose={() => setShowAddEvent(false)}
          date={addEventDate}
        />
      )}
    </div>
  );
}

/* Legend chip */
function LegendDot({ color, label, outlined }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          width: 12,
          height: 12,
          borderRadius: "50%",
          background: color,
          outline: outlined ? `2px solid ${color}` : "none",
        }}
      />
      <span style={{ color: SUBTEXT, fontWeight: 800, fontSize: 12 }}>{label}</span>
    </div>
  );
}

function MiniMetric({ label, value }) {
  return (
    <div
      style={{
        background: SOFT,
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        padding: "10px 12px",
      }}
    >
      <div style={{ color: SUBTEXT, fontSize: 12, fontWeight: 700 }}>{label}</div>
      <div style={{ color: TEXT, fontWeight: 900, fontSize: 22, marginTop: 2 }}>{value}</div>
    </div>
  );
}

function EmptyState({ title, text }) {
  return (
    <div
      style={{
        color: TEXT,
        background: "#191919",
        borderRadius: 12,
        padding: 16,
        border: `1px solid ${BORDER}`,
      }}
    >
      <div style={{ fontWeight: 900, marginBottom: 6 }}>{title}</div>
      <div style={{ color: SUBTEXT, lineHeight: 1.5 }}>{text}</div>
    </div>
  );
}

/* Add Event Modal (local note only) */
function AddEventModal({ onSave, onClose, date }) {
  const [title, setTitle] = useState("");
  const [time, setTime] = useState("");
  const [notes, setNotes] = useState("");

  return (
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
        style={{
          background: CARD,
          borderRadius: 18,
          padding: "26px 24px",
          minWidth: 360,
          maxWidth: 520,
          width: "92%",
          boxShadow: "0 2px 22px rgba(0,0,0,0.5)",
          border: `2px solid ${GOLD}`,
        }}
      >
        <h3 style={{ color: GOLD, fontWeight: 900, marginBottom: 14 }}>
          Add Calendar Note ({date?.toLocaleDateString()})
        </h3>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSave({ title, time, notes });
          }}
        >
          <Field label="Title">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              style={inputStyle}
              placeholder="Event title"
              required
            />
          </Field>

          <Field label="Time">
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              style={inputStyle}
            />
          </Field>

          <Field label="Notes">
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              style={{ ...inputStyle, resize: "vertical" }}
              placeholder="Notes"
            />
          </Field>

          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <button
              type="submit"
              style={{
                background: GOLD,
                color: "#232323",
                fontWeight: 900,
                border: "none",
                borderRadius: 8,
                padding: "11px 16px",
                cursor: "pointer",
                flex: 1,
              }}
            >
              Save
            </button>

            <button
              type="button"
              onClick={onClose}
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
        </form>
      </div>
    </div>
  );
}

/* Shared UI bits */
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

const monthBtnStyle = {
  background: CARD,
  color: GOLD,
  border: `1.5px solid ${BORDER}`,
  borderRadius: 8,
  padding: "8px 14px",
  fontWeight: 900,
  fontSize: "1.02em",
  cursor: "pointer",
};