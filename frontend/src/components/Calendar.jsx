// src/components/Calendar.jsx
import React, { useEffect, useMemo, useState } from "react";
import {
  FaChevronLeft,
  FaChevronRight,
  FaCalendarAlt,
  FaStickyNote,
  FaBirthdayCake,
  FaGoogle,
  FaPlus,
  FaEdit,
  FaTrash,
} from "react-icons/fa";

/* ===== THEME ===== */
const BG = "#181a1b";
const CARD = "#232323";
const SOFT = "#1e2326";
const BORDER = "#2b2f33";
const TEXT = "#f3f4f5";
const SUBTEXT = "#9aa3ab";
const GOLD = "#f7cb53";
const GREEN = "#30b46c";
const BLUE = "#5b8def";
const CAKE = "#d19a66";

/* ===== API ===== */
const API_BASE =
  (process.env.REACT_APP_API_BASE && process.env.REACT_APP_API_BASE.trim()) ||
  (process.env.REACT_APP_API_URL && process.env.REACT_APP_API_URL.trim()) ||
  window.location.origin.replace(/\/$/, "");

/* ===== HELPERS ===== */
function pad2(n) {
  return String(n).padStart(2, "0");
}

function normEmail(v) {
  return String(v || "").trim().toLowerCase();
}

function safeDate(v) {
  if (!v) return null;
  try {
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

function startOfMonth(d) {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function endOfMonth(d) {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0);
}

function sameDay(a, b) {
  return (
    a &&
    b &&
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function dateKey(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function monthTitle(d) {
  return d.toLocaleDateString([], { month: "long", year: "numeric" });
}

function weekdayShort() {
  return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
}

function getLeadName(lead) {
  return lead?.name || lead?.email || "Lead";
}

function noteStorageKey(email) {
  return `retainai_calendar_notes_${normEmail(email) || "anon"}`;
}

function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function saveJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

/* ===== NORMALIZERS ===== */
function normalizeBackendAppointment(raw) {
  const dt = safeDate(raw?.appointment_time);
  if (!dt) return null;

  return {
    kind: "appointment",
    source: "backend",
    id:
      raw?.id ||
      raw?._id ||
      raw?.appointment_id ||
      raw?.appointmentId ||
      `backend-${raw?.lead_email || raw?.lead_id || dt.toISOString()}`,
    title: raw?.title || raw?.lead_first_name || raw?.business_name || "Appointment",
    leadName:
      raw?.lead_full_name ||
      [raw?.lead_first_name, raw?.lead_last_name].filter(Boolean).join(" ") ||
      raw?.lead_email ||
      "",
    leadEmail: raw?.lead_email || "",
    note: raw?.notes || "",
    dateObj: dt,
    done: !!(raw?.done ?? raw?.completed ?? raw?.is_done),
  };
}

function normalizeLocalAppointments(leads = []) {
  const out = [];

  (leads || []).forEach((lead) => {
    (lead.appointments || []).forEach((appt, idx) => {
      const dt = safeDate(`${appt.date}T${appt.time || "00:00"}`);
      if (!dt) return;

      out.push({
        kind: "appointment",
        source: "local",
        id: appt._localKey || `${lead.id || lead.email || "lead"}-${idx}-${appt.title || "appt"}`,
        title: appt.title || "Appointment",
        leadName: getLeadName(lead),
        leadEmail: lead?.email || "",
        note: appt?.notes || "",
        dateObj: dt,
        done: !!appt?.done,
      });
    });
  });

  return out;
}

function normalizeGoogleEvents(events = []) {
  return (events || [])
    .map((evt, idx) => {
      const start =
        evt?.start?.dateTime ||
        (evt?.start?.date ? `${evt.start.date}T00:00:00` : null);
      const dt = safeDate(start);
      if (!dt) return null;

      return {
        kind: "google",
        source: "google",
        id: evt?.id || `google-${idx}-${dt.toISOString()}`,
        title: evt?.summary || "Google event",
        leadName: "",
        leadEmail: "",
        note: evt?.location || evt?.description || "",
        dateObj: dt,
        done: false,
      };
    })
    .filter(Boolean);
}

function normalizeBirthdays(leads = [], monthDate) {
  const out = [];
  const year = monthDate.getFullYear();

  (leads || []).forEach((lead, idx) => {
    if (!lead?.birthday) return;

    const parts = String(lead.birthday).split("-");
    if (parts.length !== 3) return;

    const month = Number(parts[1]);
    const day = Number(parts[2]);
    if (!month || !day) return;

    const dt = new Date(year, month - 1, day, 12, 0, 0);
    if (Number.isNaN(dt.getTime())) return;

    out.push({
      kind: "birthday",
      source: "birthday",
      id: `birthday-${lead.id || idx}-${year}`,
      title: `${getLeadName(lead)} birthday`,
      leadName: getLeadName(lead),
      leadEmail: lead?.email || "",
      note: "",
      dateObj: dt,
      done: false,
    });
  });

  return out;
}

function mergeAndSortItems(items = []) {
  return [...items].sort((a, b) => a.dateObj.getTime() - b.dateObj.getTime());
}

function itemTimeLabel(item) {
  if (item.kind === "birthday") return "All day";
  return item.dateObj.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function itemMeta(item) {
  if (item.kind === "appointment") {
    return {
      icon: <FaCalendarAlt />,
      color: GREEN,
      label: item.done ? "Completed appointment" : "Appointment",
    };
  }
  if (item.kind === "google") {
    return {
      icon: <FaGoogle />,
      color: BLUE,
      label: "Google event",
    };
  }
  if (item.kind === "birthday") {
    return {
      icon: <FaBirthdayCake />,
      color: CAKE,
      label: "Birthday",
    };
  }
  return {
    icon: <FaStickyNote />,
    color: GOLD,
    label: "Note",
  };
}

export default function Calendar({
  user,
  leads = [],
  googleEvents = [],
  selectedDate,
  setSelectedDate,
  onDayClick,
}) {
  const [monthDate, setMonthDate] = useState(() => {
    const base = selectedDate ? safeDate(selectedDate) : new Date();
    return base || new Date();
  });

  const [backendAppointments, setBackendAppointments] = useState([]);
  const [notesMap, setNotesMap] = useState({});
  const [noteModalOpen, setNoteModalOpen] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [editingNoteId, setEditingNoteId] = useState(null);

  const userEmail = user?.org_id || user?.email || "";

  useEffect(() => {
    setNotesMap(loadJSON(noteStorageKey(userEmail), {}));
  }, [userEmail]);

  useEffect(() => {
    saveJSON(noteStorageKey(userEmail), notesMap);
  }, [notesMap, userEmail]);

  useEffect(() => {
    let cancelled = false;

    async function loadBackendAppointments() {
      if (!user?.email) {
        if (!cancelled) setBackendAppointments([]);
        return;
      }

      try {
        const res = await fetch(`${API_BASE}/api/appointments/${encodeURIComponent(user.email)}`, {
          credentials: "include",
          headers: { Accept: "application/json" },
        });
        const data = await res.json().catch(() => ({}));
        if (!cancelled) {
          setBackendAppointments(Array.isArray(data?.appointments) ? data.appointments : []);
        }
      } catch {
        if (!cancelled) setBackendAppointments([]);
      }
    }

    loadBackendAppointments();

    const refresh = () => loadBackendAppointments();
    window.addEventListener("appointments:changed", refresh);
    document.addEventListener("visibilitychange", refresh);

    return () => {
      cancelled = true;
      window.removeEventListener("appointments:changed", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [user?.email]);

  const normalizedBackendAppointments = useMemo(
    () => (backendAppointments || []).map((raw) => normalizeBackendAppointment(raw)).filter(Boolean),
    [backendAppointments]
  );

  const normalizedLocalAppointments = useMemo(
    () => normalizeLocalAppointments(leads),
    [leads]
  );

  const normalizedGoogleEvents = useMemo(
    () => normalizeGoogleEvents(googleEvents),
    [googleEvents]
  );

  const normalizedBirthdays = useMemo(
    () => normalizeBirthdays(leads, monthDate),
    [leads, monthDate]
  );

  const selectedDay =
    selectedDate && safeDate(selectedDate) ? safeDate(selectedDate) : null;

  const dayNotes = useMemo(() => {
    if (!selectedDay) return [];
    const key = dateKey(selectedDay);
    return Array.isArray(notesMap[key]) ? notesMap[key] : [];
  }, [notesMap, selectedDay]);

  const selectedDayItems = useMemo(() => {
    if (!selectedDay) return [];

    const key = dateKey(selectedDay);

    const notes = (notesMap[key] || []).map((n) => ({
      kind: "note",
      source: "note",
      id: n.id,
      title: n.title || "Note",
      leadName: n.leadName || "",
      leadEmail: n.leadEmail || "",
      note: n.text || "",
      dateObj: safeDate(n.createdAt) || selectedDay,
      done: false,
    }));

    return mergeAndSortItems([
      ...normalizedBackendAppointments.filter((a) => sameDay(a.dateObj, selectedDay)),
      ...normalizedLocalAppointments.filter((a) => sameDay(a.dateObj, selectedDay)),
      ...normalizedGoogleEvents.filter((a) => sameDay(a.dateObj, selectedDay)),
      ...normalizedBirthdays.filter((a) => sameDay(a.dateObj, selectedDay)),
      ...notes,
    ]);
  }, [
    selectedDay,
    notesMap,
    normalizedBackendAppointments,
    normalizedLocalAppointments,
    normalizedGoogleEvents,
    normalizedBirthdays,
  ]);

  const monthGrid = useMemo(() => {
    const first = startOfMonth(monthDate);
    const last = endOfMonth(monthDate);
    const start = new Date(first);
    start.setDate(first.getDate() - first.getDay());

    const end = new Date(last);
    end.setDate(last.getDate() + (6 - last.getDay()));

    const days = [];
    const cursor = new Date(start);

    while (cursor <= end) {
      days.push(new Date(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }

    return days;
  }, [monthDate]);

  const countsByDate = useMemo(() => {
    const map = {};

    const add = (d, type) => {
      const key = dateKey(d);
      if (!map[key]) map[key] = { appointment: 0, google: 0, birthday: 0, note: 0 };
      map[key][type] = (map[key][type] || 0) + 1;
    };

    normalizedBackendAppointments.forEach((a) => add(a.dateObj, "appointment"));
    normalizedLocalAppointments.forEach((a) => add(a.dateObj, "appointment"));
    normalizedGoogleEvents.forEach((a) => add(a.dateObj, "google"));
    normalizedBirthdays.forEach((a) => add(a.dateObj, "birthday"));

    Object.entries(notesMap || {}).forEach(([key, notes]) => {
      const d = safeDate(`${key}T12:00:00`);
      if (!d) return;
      if (!Array.isArray(notes)) return;
      notes.forEach(() => add(d, "note"));
    });

    return map;
  }, [
    normalizedBackendAppointments,
    normalizedLocalAppointments,
    normalizedGoogleEvents,
    normalizedBirthdays,
    notesMap,
  ]);

  function openNewNote() {
    if (!selectedDay) return;
    setEditingNoteId(null);
    setNoteText("");
    setNoteModalOpen(true);
  }

  function openEditNote(noteItem) {
    setEditingNoteId(noteItem.id);
    setNoteText(noteItem.note || "");
    setNoteModalOpen(true);
  }

  function saveNote() {
    if (!selectedDay) return;
    const key = dateKey(selectedDay);
    const existing = Array.isArray(notesMap[key]) ? [...notesMap[key]] : [];

    if (editingNoteId) {
      const next = existing.map((n) =>
        n.id === editingNoteId ? { ...n, text: noteText, updatedAt: new Date().toISOString() } : n
      );
      setNotesMap((prev) => ({ ...prev, [key]: next }));
    } else {
      const newNote = {
        id: `note_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        title: "Day note",
        text: noteText,
        leadName: "",
        leadEmail: "",
        createdAt: new Date().toISOString(),
      };
      setNotesMap((prev) => ({ ...prev, [key]: [...existing, newNote] }));
    }

    setNoteModalOpen(false);
    setEditingNoteId(null);
    setNoteText("");
  }

  function deleteNote(noteItem) {
    if (!selectedDay) return;
    const key = dateKey(selectedDay);
    const existing = Array.isArray(notesMap[key]) ? [...notesMap[key]] : [];
    const next = existing.filter((n) => n.id !== noteItem.id);
    setNotesMap((prev) => ({ ...prev, [key]: next }));
  }

  const currentMonthStats = useMemo(() => {
    const inMonth = (d) =>
      d.getFullYear() === monthDate.getFullYear() &&
      d.getMonth() === monthDate.getMonth();

    return {
      backendAppointments: normalizedBackendAppointments.filter((a) => inMonth(a.dateObj)).length,
      googleEvents: normalizedGoogleEvents.filter((a) => inMonth(a.dateObj)).length,
      birthdays: normalizedBirthdays.filter((a) => inMonth(a.dateObj)).length,
    };
  }, [monthDate, normalizedBackendAppointments, normalizedGoogleEvents, normalizedBirthdays]);

  return (
    <div style={{ padding: 28, background: BG, minHeight: "100vh", boxSizing: "border-box" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.35fr", gap: 18 }}>
        {/* LEFT */}
        <div
          style={{
            ...card,
            padding: 18,
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          <div>
            <div style={{ color: TEXT, fontWeight: 900, fontSize: 18 }}>Calendar</div>
            <div style={{ color: SUBTEXT, marginTop: 6, lineHeight: 1.45, fontSize: 13 }}>
              View appointments, Google events, birthdays, and internal notes in one place.
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 10,
            }}
          >
            <MiniStat label="Backend appointments" value={currentMonthStats.backendAppointments} />
            <MiniStat label="Google events" value={currentMonthStats.googleEvents} />
            <MiniStat label="Birthdays" value={currentMonthStats.birthdays} />
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "40px 1fr 40px",
              alignItems: "center",
              gap: 12,
            }}
          >
            <NavBtn onClick={() => setMonthDate(new Date(monthDate.getFullYear(), monthDate.getMonth() - 1, 1))}>
              <FaChevronLeft />
            </NavBtn>

            <div
              style={{
                color: GOLD,
                fontWeight: 900,
                textAlign: "center",
                fontSize: 18,
              }}
            >
              {monthTitle(monthDate)}
            </div>

            <NavBtn onClick={() => setMonthDate(new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 1))}>
              <FaChevronRight />
            </NavBtn>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(7, 1fr)",
              gap: 8,
              alignItems: "center",
            }}
          >
            {weekdayShort().map((day) => (
              <div
                key={day}
                style={{
                  textAlign: "center",
                  color: GOLD,
                  fontWeight: 800,
                  fontSize: 13,
                  paddingBottom: 4,
                }}
              >
                {day}
              </div>
            ))}

            {monthGrid.map((day) => {
              const key = dateKey(day);
              const counts = countsByDate[key] || {
                appointment: 0,
                google: 0,
                birthday: 0,
                note: 0,
              };
              const inMonth =
                day.getMonth() === monthDate.getMonth() &&
                day.getFullYear() === monthDate.getFullYear();
              const isSelected = selectedDay && sameDay(day, selectedDay);

              return (
                <button
                  key={key}
                  onClick={() => setSelectedDate && setSelectedDate(day)}
                  onDoubleClick={() => onDayClick && onDayClick(day)}
                  style={{
                    minHeight: 62,
                    background: isSelected ? "#23262a" : "#181b1e",
                    border: `2px solid ${isSelected ? GOLD : BORDER}`,
                    borderRadius: 14,
                    color: inMonth ? TEXT : "#5e666d",
                    padding: "8px 8px 6px",
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                    alignItems: "flex-end",
                  }}
                >
                  <div style={{ fontWeight: 800, fontSize: 14 }}>{day.getDate()}</div>

                  <div
                    style={{
                      display: "flex",
                      gap: 5,
                      alignSelf: "flex-end",
                      flexWrap: "wrap",
                      justifyContent: "flex-end",
                    }}
                  >
                    {counts.appointment > 0 && <DotBadge color={GREEN} text={counts.appointment} />}
                    {counts.note > 0 && <DotBadge color={GOLD} text={counts.note} />}
                    {counts.google > 0 && <DotBadge color={BLUE} text={counts.google} />}
                    {counts.birthday > 0 && <DotBadge color={CAKE} text={counts.birthday} />}
                  </div>
                </button>
              );
            })}
          </div>

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 14,
              alignItems: "center",
              justifyContent: "space-between",
              marginTop: 4,
            }}
          >
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              <LegendPill color={GREEN} label="Appointment" />
              <LegendPill color={GOLD} label="Note" />
              <LegendPill color={BLUE} label="Google" />
              <LegendPill color={CAKE} label="Birthday" />
            </div>

            <div style={{ color: SUBTEXT, fontSize: 12, fontWeight: 700 }}>
              Double-click a day to quick add
            </div>
          </div>
        </div>

        {/* RIGHT */}
        <div
          style={{
            ...card,
            padding: 18,
            display: "flex",
            flexDirection: "column",
            minHeight: 560,
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 12,
              alignItems: "start",
              marginBottom: 16,
            }}
          >
            <div>
              <div style={{ color: GOLD, fontWeight: 900, fontSize: 18 }}>
                {selectedDay
                  ? selectedDay.toLocaleDateString([], {
                      weekday: "long",
                      month: "long",
                      day: "numeric",
                    })
                  : "Select a date"}
              </div>
              <div style={{ color: SUBTEXT, marginTop: 6, fontSize: 13 }}>
                {selectedDay
                  ? "Daily timeline for CRM activity and Google Calendar events."
                  : "Choose a date to inspect activity."}
              </div>
            </div>

            <button
              onClick={openNewNote}
              disabled={!selectedDay}
              style={{
                background: GOLD,
                color: "#191919",
                border: "none",
                borderRadius: 10,
                fontWeight: 900,
                padding: "10px 16px",
                cursor: selectedDay ? "pointer" : "not-allowed",
                opacity: selectedDay ? 1 : 0.6,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <FaPlus />
              Add Note
            </button>
          </div>

          {!selectedDay ? (
            <div
              style={{
                background: "#17191b",
                border: `1px solid ${BORDER}`,
                borderRadius: 14,
                padding: 16,
                color: SUBTEXT,
              }}
            >
              <div style={{ color: TEXT, fontWeight: 800, marginBottom: 6 }}>Nothing selected</div>
              Pick a day on the calendar to review appointments, Google events, notes, and birthdays.
            </div>
          ) : selectedDayItems.length === 0 ? (
            <div
              style={{
                background: "#17191b",
                border: `1px solid ${BORDER}`,
                borderRadius: 14,
                padding: 16,
                color: SUBTEXT,
              }}
            >
              <div style={{ color: TEXT, fontWeight: 800, marginBottom: 6 }}>No activity yet</div>
              There is nothing scheduled or recorded for this day yet.
            </div>
          ) : (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              {selectedDayItems.map((item) => (
                <TimelineCard
                  key={item.id}
                  item={item}
                  onEditNote={item.kind === "note" ? () => openEditNote(item) : null}
                  onDeleteNote={item.kind === "note" ? () => deleteNote(item) : null}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {noteModalOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "#000a",
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              width: "92%",
              maxWidth: 540,
              background: CARD,
              border: `2px solid ${GOLD}`,
              borderRadius: 18,
              padding: 24,
              boxShadow: "0 12px 30px rgba(0,0,0,0.45)",
            }}
          >
            <div style={{ color: GOLD, fontWeight: 900, fontSize: 20, marginBottom: 14 }}>
              {editingNoteId ? "Edit note" : "Add note"}
            </div>

            <textarea
              rows={8}
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Write your note for this day..."
              style={{
                width: "100%",
                resize: "vertical",
                boxSizing: "border-box",
                background: BG,
                color: TEXT,
                border: `1px solid ${BORDER}`,
                borderRadius: 12,
                padding: 14,
                outline: "none",
                fontSize: 14,
                lineHeight: 1.5,
              }}
            />

            <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
              <button
                onClick={saveNote}
                style={{
                  flex: 1,
                  background: GOLD,
                  color: "#191919",
                  border: "none",
                  borderRadius: 10,
                  fontWeight: 900,
                  padding: "12px 16px",
                  cursor: "pointer",
                }}
              >
                Save
              </button>

              <button
                onClick={() => {
                  setNoteModalOpen(false);
                  setEditingNoteId(null);
                  setNoteText("");
                }}
                style={{
                  flex: 1,
                  background: "transparent",
                  color: TEXT,
                  border: `1.5px solid ${GOLD}`,
                  borderRadius: 10,
                  fontWeight: 900,
                  padding: "12px 16px",
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ===== SMALL UI ===== */
const card = {
  background: CARD,
  borderRadius: 18,
  border: `1px solid ${BORDER}`,
  boxShadow: "0 2px 18px rgba(0,0,0,0.35)",
};

function MiniStat({ label, value }) {
  return (
    <div
      style={{
        background: SOFT,
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        padding: 12,
      }}
    >
      <div style={{ color: SUBTEXT, fontWeight: 700, fontSize: 12 }}>{label}</div>
      <div style={{ color: TEXT, fontWeight: 900, fontSize: 18, marginTop: 4 }}>{value}</div>
    </div>
  );
}

function NavBtn({ children, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: 36,
        height: 36,
        borderRadius: 10,
        background: "#1d2023",
        color: GOLD,
        border: `1px solid ${BORDER}`,
        cursor: "pointer",
        display: "grid",
        placeItems: "center",
      }}
    >
      {children}
    </button>
  );
}

function DotBadge({ color, text }) {
  return (
    <span
      style={{
        minWidth: 18,
        height: 18,
        borderRadius: 999,
        background: color,
        color: "#111",
        fontSize: 11,
        fontWeight: 900,
        display: "grid",
        placeItems: "center",
        padding: "0 4px",
      }}
    >
      {text}
    </span>
  );
}

function LegendPill({ color, label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: color,
          display: "inline-block",
        }}
      />
      <span style={{ color: SUBTEXT, fontSize: 13, fontWeight: 700 }}>{label}</span>
    </div>
  );
}

function TimelineCard({ item, onEditNote, onDeleteNote }) {
  const meta = itemMeta(item);

  return (
    <div
      style={{
        background: "#17191b",
        border: `1px solid ${BORDER}`,
        borderRadius: 14,
        padding: 14,
        display: "grid",
        gridTemplateColumns: "28px 1fr auto",
        gap: 12,
        alignItems: "start",
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 8,
          background: SOFT,
          color: meta.color,
          display: "grid",
          placeItems: "center",
          marginTop: 2,
        }}
      >
        {meta.icon}
      </div>

      <div>
        <div style={{ color: TEXT, fontWeight: 900, fontSize: 16 }}>{item.title}</div>
        <div style={{ color: meta.color, fontWeight: 800, fontSize: 13, marginTop: 4 }}>
          {itemTimeLabel(item)}
        </div>

        {item.leadName ? (
          <div style={{ color: TEXT, fontWeight: 700, fontSize: 13, marginTop: 6 }}>
            Lead: {item.leadName}
            {item.leadEmail ? (
              <span style={{ color: SUBTEXT, marginLeft: 8, fontWeight: 600 }}>
                {item.leadEmail}
              </span>
            ) : null}
          </div>
        ) : null}

        {item.note ? (
          <div style={{ color: SUBTEXT, marginTop: 6, lineHeight: 1.5, fontSize: 13 }}>
            {item.note}
          </div>
        ) : null}

        {item.kind === "appointment" && item.done ? (
          <div style={{ color: GREEN, marginTop: 6, fontSize: 12, fontWeight: 800 }}>
            Completed
          </div>
        ) : null}
      </div>

      {item.kind === "note" ? (
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={onEditNote}
            style={tinyBtn(GOLD, "transparent")}
            title="Edit note"
          >
            <FaEdit />
          </button>
          <button
            onClick={onDeleteNote}
            style={tinyBtn("#e66565", "transparent")}
            title="Delete note"
          >
            <FaTrash />
          </button>
        </div>
      ) : (
        <div
          style={{
            color: SUBTEXT,
            fontSize: 12,
            fontWeight: 700,
            whiteSpace: "nowrap",
          }}
        >
          {meta.label}
        </div>
      )}
    </div>
  );
}

function tinyBtn(color, bg) {
  return {
    width: 34,
    height: 34,
    borderRadius: 10,
    background: bg,
    color,
    border: `1px solid ${color}`,
    cursor: "pointer",
    display: "grid",
    placeItems: "center",
  };
}