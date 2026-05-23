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
const API_BASE =
  (process.env.REACT_APP_API_BASE && process.env.REACT_APP_API_BASE.trim()) ||
  (process.env.REACT_APP_API_URL && process.env.REACT_APP_API_URL.trim()) ||
  window.location.origin.replace(/\/$/, "");

/* ===== Helpers ===== */
const pad2 = (n) => String(n).padStart(2, "0");

function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function isSameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
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

function normText(v) {
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

function normalizeBackend(raw) {
  const dt = parseDateSafe(raw?.appointment_time);
  if (!dt) return null;

  const y = dt.getFullYear();
  const m = pad2(dt.getMonth() + 1);
  const d = pad2(dt.getDate());
  const hh = pad2(dt.getHours());
  const mm = pad2(dt.getMinutes());

  return {
    _backend: raw,
    _rid: getRID(raw),
    title: raw.title || raw.lead_first_name || raw.business_name || "Appointment",
    date: `${y}-${m}-${d}`,
    time: `${hh}:${mm}`,
    done: !!(raw.done ?? raw.completed ?? raw.is_done),
    notes: raw.notes || "",
    lead: {
      id: raw.lead_id || `backend-${getRID(raw)}`,
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

function getAppointments(leads = [], backendRows = []) {
  const list = [];
  const now = new Date();

  (leads || []).forEach((lead) =>
    (lead.appointments || []).forEach((app, idx) => {
      const dt = new Date(`${app.date}T${app.time || "00:00"}`);
      list.push({
        ...app,
        _local: true,
        _localKey:
          app._localKey ||
          `${String(lead.id)}|${String(app.title)}|${String(app.date)}|${String(app.time || "")}|${idx}`,
        lead,
        sortKey: dt.getTime(),
        isOverdue: !app.done && dt < now,
      });
    })
  );

  (backendRows || []).forEach((a) => {
    const dt = new Date(`${a.date}T${a.time || "00:00"}`);
    list.push({
      ...a,
      sortKey: dt.getTime(),
      isOverdue: !a.done && dt < now,
    });
  });

  list.sort((a, b) => a.sortKey - b.sortKey);
  return list;
}

function categorize(appointments) {
  const buckets = { overdue: [], today: [], next7: [], later: [], done: [] };
  const now = new Date();

  appointments.forEach((a) => {
    const when = new Date(`${a.date}T${a.time || "00:00"}`);
    if (a.done) {
      buckets.done.push(a);
      return;
    }
    if (when < now) {
      buckets.overdue.push(a);
      return;
    }
    if (isSameDay(when, now)) {
      buckets.today.push(a);
      return;
    }
    const diff = Math.ceil((startOfDay(when) - startOfDay(now)) / 86400000);
    if (diff <= 7) buckets.next7.push(a);
    else buckets.later.push(a);
  });

  return buckets;
}

function monthLabel(dateStr) {
  const d = parseDateSafe(dateStr);
  if (!d) return "";
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function statusMeta(appt) {
  if (appt.done) return { label: "Done", color: GREEN };
  if (appt.isOverdue) return { label: "Overdue", color: RED };
  return { label: "Scheduled", color: GOLD };
}

function keyFor(a) {
  return `${a._rid ?? a._localKey ?? a.lead?.id ?? "x"}|${a.title}|${a.date}|${a.time || ""}`;
}

export default function Appointments({ user, leads = [], setLeads }) {
  const [backendAppointments, setBackendAppointments] = useState([]);
  const [hiddenIds, setHiddenIds] = useState({});
  const [doneOverride, setDoneOverride] = useState({});
  const [timeOverride, setTimeOverride] = useState({});
  const [slotMap, setSlotMap] = useState({});
  const slotMapRef = useRef({});

  const [search, setSearch] = useState("");
  const [showCompleted, setShowCompleted] = useState(false);
  const [saving, setSaving] = useState(false);

  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({
    leadId: "",
    title: "",
    date: "",
    time: "",
  });

  const userEmail = user?.org_id || user?.email || "";

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

  const fetchBackend = async () => {
    if (!user?.email) return;
    try {
      const r = await fetch(`${API_BASE}/api/appointments/${encodeURIComponent(user.email)}`, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const j = await r.json().catch(() => ({}));
      setBackendAppointments(Array.isArray(j?.appointments) ? j.appointments : []);
    } catch {
      setBackendAppointments([]);
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
  }, [user?.email]);

  const assignedBackend = useMemo(() => {
    return assignStableRIDs(backendAppointments || [], slotMapRef.current || {});
  }, [backendAppointments]);

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
    () => effectiveBackend.map((r) => normalizeBackend(r)).filter(Boolean),
    [effectiveBackend]
  );

  const allAppointments = useMemo(
    () => getAppointments(leads, normalizedBackend),
    [leads, normalizedBackend]
  );

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

  const withSeconds = (date, time) => `${date}T${time || "00:00"}:00`;
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
    if (!user?.email || !sid) return false;

    try {
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
      };

      const res = await fetch(
        `${API_BASE}/api/appointments/${encodeURIComponent(user.email)}/${encodeURIComponent(
          String(sid)
        )}`,
        {
          method: "PUT",
          credentials: "include",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(body),
        }
      );
      return res.ok;
    } catch {
      return false;
    }
  }

  async function apiDeleteBackend(appt) {
    const sid = serverIdOf(appt);
    if (!user?.email || !sid) return false;

    try {
      const res = await fetch(
        `${API_BASE}/api/appointments/${encodeURIComponent(user.email)}/${encodeURIComponent(
          String(sid)
        )}`,
        {
          method: "DELETE",
          credentials: "include",
        }
      );
      return res.ok;
    } catch {
      return false;
    }
  }

  async function persistLocalLeads(nextLeads) {
    if (!userEmail) return;
    try {
      await fetch(`${API_BASE}/api/leads`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-User-Email": userEmail,
        },
        body: JSON.stringify({ leads: nextLeads }),
      });
    } catch {
      // optimistic UI stays
    }
  }

  function updateLocalLeadAppointments(mutator) {
    setLeads((prev) => {
      const safePrev = Array.isArray(prev) ? prev : [];
      const next = mutator(safePrev);
      persistLocalLeads(next);
      return next;
    });
  }

  async function toggleDone(appt) {
    if (isBackend(appt)) {
      const newDone = !appt.done;
      updateDoneOverrides(appt, newDone);

      const ok = await apiUpdateBackend(appt, { done: newDone });
      if (serverIdOf(appt) && !ok) {
        rollbackDoneOverrides(appt, !newDone);
      }

      ping("appointments:changed");
      return;
    }

    updateLocalLeadAppointments((prev) =>
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
  }

  async function reschedule(appt, days) {
    if (isBackend(appt)) {
      const base = new Date(`${appt.date}T${appt.time || "00:00"}`);
      base.setDate(base.getDate() + days);

      const newDate = `${base.getFullYear()}-${pad2(base.getMonth() + 1)}-${pad2(base.getDate())}`;
      const newTime = `${pad2(base.getHours())}:${pad2(base.getMinutes())}`;
      const iso = withSeconds(newDate, newTime);

      updateTimeOverrides(appt, iso);

      const ok = await apiUpdateBackend(appt, { appointment_time: iso });
      if (serverIdOf(appt) && !ok) {
        removeTimeOverrides(appt);
      }

      ping("appointments:changed");
      return;
    }

    updateLocalLeadAppointments((prev) =>
      prev.map((l) => {
        if (String(l.id) !== String(appt.lead.id)) return l;

        return {
          ...l,
          appointments: (l.appointments || []).map((x) => {
            const localKey = x._localKey || `${l.id}|${x.title}|${x.date}|${x.time || ""}`;
            if (String(localKey) !== String(appt._localKey)) return x;

            const base = new Date(`${x.date}T${x.time || "00:00"}`);
            base.setDate(base.getDate() + days);

            const movedDate = `${base.getFullYear()}-${pad2(base.getMonth() + 1)}-${pad2(base.getDate())}`;
            const movedTime = `${pad2(base.getHours())}:${pad2(base.getMinutes())}`;

            return { ...x, date: movedDate, time: movedTime };
          }),
        };
      })
    );

    ping("appointments:changed");
  }

  async function remove(appt) {
    if (isBackend(appt)) {
      hideOverrides(appt);

      const ok = await apiDeleteBackend(appt);
      if (serverIdOf(appt) && !ok) {
        unhideOverrides(appt);
      }

      ping("appointments:changed");
      return;
    }

    updateLocalLeadAppointments((prev) =>
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
  }

  function beginEdit(appt) {
    setForm({
      leadId: String(appt.lead.id),
      title: appt.title,
      date: appt.date,
      time: appt.time || "",
    });
    setEditing(appt);
    setShowModal(true);
  }

  async function handleSave() {
    const { leadId, title, date, time } = form;
    if (!leadId || !title || !date) return;

    setSaving(true);

    try {
      if (editing && editing._backend) {
        const iso = `${date}T${time || "00:00"}:00`;

        updateTimeOverrides(editing, iso);

        const ok = await apiUpdateBackend(editing, {
          appointment_time: iso,
          title,
          notes: editing.notes || "",
        });

        if (serverIdOf(editing) && !ok) {
          removeTimeOverrides(editing);
        }

        ping("appointments:changed");
      } else if (editing) {
        updateLocalLeadAppointments((prev) => {
          return prev.map((l) => {
            if (String(l.id) !== String(leadId)) return l;

            const filtered = (l.appointments || []).filter((x) => {
              const localKey =
                x._localKey || `${l.id}|${x.title}|${x.date}|${x.time || ""}`;
              return String(localKey) !== String(editing._localKey);
            });

            return {
              ...l,
              appointments: [
                ...filtered,
                {
                  _localKey: editing._localKey,
                  title,
                  date,
                  time,
                  done: false,
                },
              ],
            };
          });
        });

        ping("appointments:changed");
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
          user_email: user?.email || "",
          business_name: user?.business || user?.businessType || "",
          appointment_time: `${date}T${time || "00:00"}:00`,
          appointment_location: selectedLead.location || user?.location || "",
          duration: 30,
          notes: "",
          status: "scheduled",
          title,
        };

        const res = await fetch(
          `${API_BASE}/api/appointments/${encodeURIComponent(user.email)}`,
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

        ping("appointments:changed");
      }
    } catch (err) {
      console.error(err);
      alert(err?.message || "Failed to save appointment.");
    } finally {
      setSaving(false);
      setShowModal(false);
      setEditing(null);
      setForm({ leadId: "", title: "", date: "", time: "" });
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
      style={{
        padding: "28px",
        background: BG,
        minHeight: "100vh",
        boxSizing: "border-box",
      }}
    >
      <div
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
            setForm({ leadId: "", title: "", date: "", time: "" });
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

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 18,
          alignItems: "center",
        }}
      >
        <div
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
            placeholder="Search by title, lead, email, date…"
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
            style={{
              background: CARD,
              borderRadius: 18,
              padding: "28px 30px",
              minWidth: 420,
              maxWidth: 520,
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
              />
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

function AppointmentCard({ appt, onDone, onEdit, onDelete, onResched }) {
  const meta = statusMeta(appt);

  return (
    <div
      style={{
        background: CARD,
        border: `1px solid ${BORDER}`,
        borderLeft: `6px solid ${meta.color}`,
        borderRadius: 14,
        padding: "15px 16px",
        minHeight: 104,
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
            fontSize: 15,
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
          {appt.lead?.name ? `${appt.lead.name}` : "No lead name"}
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

        {!appt.done && (
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <Chip icon={<FaClock />} onClick={() => onResched(1)}>
              +1 day
            </Chip>
            <Chip onClick={() => onResched(3)}>+3 days</Chip>
            <Chip onClick={() => onResched(7)}>+1 week</Chip>
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
        <button
          onClick={onDone}
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

function Chip({ children, onClick, icon }) {
  return (
    <button
      onClick={onClick}
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

function LiveLeadSearch({ leads, value, onChange }) {
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