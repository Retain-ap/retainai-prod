import React, { useEffect, useMemo, useState } from "react";
import { API_BASE } from "../config";
import "./NotificationsCenter.css";

const PAGE_SIZE = 12;

function safeStr(v) {
  return v == null ? "" : String(v);
}

function looksLikeIsoNoZone(s) {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(String(s || "").trim());
}

function parsePossiblyLocalDate(raw) {
  const s = safeStr(raw).trim();
  if (!s) return null;

  if (looksLikeIsoNoZone(s)) {
    const [datePart, timePart] = s.split("T");
    const [y, m, d] = datePart.split("-").map(Number);
    const [hh, mm, ss = "0"] = timePart.split(":");
    return new Date(y, (m || 1) - 1, d || 1, Number(hh || 0), Number(mm || 0), Number(ss || 0));
  }

  const dt = new Date(s);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function formatDateTime(raw) {
  const dt = parsePossiblyLocalDate(raw);
  if (!dt) return "";
  return dt.toLocaleString([], {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function extractScheduledTimeFromMessage(message) {
  const text = safeStr(message);

  const match =
    text.match(/\bfor\s+([A-Za-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s*[AP]M)\b/i) ||
    text.match(/\b([A-Za-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s*[AP]M)\b/i);

  return match?.[1] || "";
}

function iconForNotification(notif) {
  const s = safeStr(notif.subject).toLowerCase();
  const c = safeStr(notif.channel).toLowerCase();

  if (c.includes("whatsapp") || s.includes("whatsapp")) return "💬";
  if (c.includes("email") || s.includes("email")) return "📧";
  if (s.includes("appointment") || s.includes("calendar")) return "📅";
  if (s.includes("reminder")) return "🔔";
  if (s.includes("automation")) return "⚙️";
  return "📩";
}

function labelForNotification(notif) {
  const c = safeStr(notif.channel).toLowerCase();
  if (c.includes("whatsapp")) return "WhatsApp";
  if (c.includes("email")) return "Email";
  if (c.includes("automation")) return "Automation";
  if (c.includes("appointment")) return "Appointment";
  if (c.includes("reminder")) return "Reminder";
  return "App";
}

function normalizeNotification(n, idx) {
  const subject = n.subject || n.title || n.type || "Notification";
  const message = n.message || n.body || n.text || "";
  const rawTimestamp = n.timestamp || n.created_at || n.time || "";
  const channel = safeStr(n.channel || n.type || "").toLowerCase();
  const subjectLower = safeStr(subject).toLowerCase();
  const messageLower = safeStr(message).toLowerCase();

  const scheduledTime =
    subjectLower.includes("appointment") || messageLower.includes("appointment")
      ? extractScheduledTimeFromMessage(message)
      : "";

  const displayTime = scheduledTime || formatDateTime(rawTimestamp);

  return {
    ...n,
    subject,
    message,
    rawTimestamp,
    displayTime,
    channel,
    lead_email: n.lead_email || n.leadEmail || n.email || "",
    lead_name: n.lead_name || n.leadName || "",
    read: n.read ?? false,
    _id: String(n.id ?? n._id ?? n.uuid ?? idx),
    _idx: idx,
    _sortTime: parsePossiblyLocalDate(rawTimestamp)?.getTime() || 0,
  };
}

function startOfToday() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

function startOfWeek() {
  const d = startOfToday();
  const day = d.getDay();
  const diff = (day + 6) % 7;
  d.setDate(d.getDate() - diff);
  return d;
}

function groupNotifications(items) {
  const todayStart = startOfToday().getTime();
  const weekStart = startOfWeek().getTime();

  const groups = {
    today: [],
    week: [],
    older: [],
  };

  items.forEach((n) => {
    const t = n._sortTime || 0;
    if (t >= todayStart) groups.today.push(n);
    else if (t >= weekStart) groups.week.push(n);
    else groups.older.push(n);
  });

  return groups;
}

function StatCard({ label, value, accent }) {
  return (
    <div className={`notif-stat-card ${accent ? "accent" : ""}`}>
      <div className="notif-stat-label">{label}</div>
      <div className="notif-stat-value">{value}</div>
    </div>
  );
}

function Section({ title, items, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);

  if (!items.length) return null;

  return (
    <section className="notif-section">
      <button className="notif-section-header" onClick={() => setOpen((v) => !v)} type="button">
        <div className="notif-section-title-wrap">
          <span className="notif-section-dot" />
          <span className="notif-section-title">{title}</span>
          <span className="notif-section-count">{items.length}</span>
        </div>
        <span className="notif-section-toggle">{open ? "−" : "+"}</span>
      </button>
      {open && <ul className="notif-list">{children}</ul>}
    </section>
  );
}

function NotificationRow({ notif, onMarkAsRead }) {
  return (
    <li className={`notif-item ${notif.read ? "read" : "unread"}`}>
      <div className="notif-icon" aria-hidden>
        {iconForNotification(notif)}
      </div>

      <div className="notif-body">
        <div className="notif-subject-row">
          <div className="notif-subject">{notif.subject || "—"}</div>
          <span className="notif-channel-pill">{labelForNotification(notif)}</span>
        </div>

        {notif.message ? <div className="notif-message">{notif.message}</div> : null}

        <div className="notif-meta">
          {notif.lead_name || notif.lead_email ? (
            <span className="notif-lead">
              Lead: <b>{notif.lead_name || notif.lead_email}</b>
            </span>
          ) : null}
          <span className="notif-time">{notif.displayTime}</span>
        </div>
      </div>

      {!notif.read ? (
        <button className="notif-mark-read" onClick={() => onMarkAsRead(notif)} type="button">
          Mark as Read
        </button>
      ) : null}
    </li>
  );
}

export default function NotificationsCenter({ user }) {
  const API = (() => {
    const env = (v) => (v && v.trim()) || "";
    const fromEnv = env(process.env.REACT_APP_API_URL) || env(process.env.REACT_APP_API_BASE);
    if (fromEnv) return fromEnv.replace(/\/$/, "");
    return API_BASE;
  })();

  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const load = async () => {
    if (!user?.email) return;
    setLoading(true);

    try {
      const res = await fetch(`${API}/api/notifications/${encodeURIComponent(user.email)}`);
      const data = await res.json().catch(() => ({}));
      const rows = Array.isArray(data?.notifications) ? data.notifications : [];
      setNotifications(rows.map((n, idx) => normalizeNotification(n, idx)));
    } catch {
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const onChanged = () => load();
    window.addEventListener("notifications:changed", onChanged);
    return () => window.removeEventListener("notifications:changed", onChanged);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, user?.email]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [filter, query]);

  const markAsRead = async (notif) => {
    setNotifications((ns) => ns.map((n) => (n._id === notif._id ? { ...n, read: true } : n)));

    const idParam = notif.id ?? notif._id ?? notif.uuid ?? notif._idx;

    try {
      await fetch(
        `${API}/api/notifications/${encodeURIComponent(user.email)}/${encodeURIComponent(idParam)}/mark_read`,
        { method: "POST" }
      );
    } catch {
      // keep optimistic state
    }
  };

  const markAllVisibleAsRead = async (items) => {
    for (const notif of items.filter((n) => !n.read)) {
      // eslint-disable-next-line no-await-in-loop
      await markAsRead(notif);
    }
  };

  const filtered = useMemo(() => {
    let list =
      filter === "all"
        ? notifications
        : notifications.filter((n) => (filter === "unread" ? !n.read : n.read));

    const q = safeStr(query).trim().toLowerCase();
    if (q) {
      list = list.filter((n) =>
        [n.subject, n.message, n.lead_name, n.lead_email, n.channel, labelForNotification(n)]
          .join(" ")
          .toLowerCase()
          .includes(q)
      );
    }

    return [...list].sort((a, b) => b._sortTime - a._sortTime);
  }, [notifications, filter, query]);

  const visible = filtered.slice(0, visibleCount);
  const grouped = useMemo(() => groupNotifications(visible), [visible]);

  if (!user?.email) {
    return (
      <div className="notif-root">
        <div className="notif-header">
          <h2 className="notif-title">Notifications</h2>
          <p className="notif-subtitle">Please log in to view notifications.</p>
        </div>
      </div>
    );
  }

  const unreadCount = notifications.filter((n) => !n.read).length;
  const appointmentCount = notifications.filter(
    (n) =>
      safeStr(n.subject).toLowerCase().includes("appointment") ||
      safeStr(n.channel).toLowerCase().includes("appointment")
  ).length;
  const whatsappCount = notifications.filter(
    (n) =>
      safeStr(n.channel).toLowerCase().includes("whatsapp") ||
      safeStr(n.subject).toLowerCase().includes("whatsapp")
  ).length;

  return (
    <div className="notif-root">
      <div className="notif-header">
        <div className="notif-title-row">
          <h2 className="notif-title">Notifications</h2>
          {unreadCount > 0 ? (
            <span className="notif-badge" title="Unread">
              {unreadCount}
            </span>
          ) : null}
        </div>

        <p className="notif-subtitle">
          All RetainAI activity appears here, including emails, WhatsApp activity, reminders,
          automations, and appointment updates.
        </p>

        <div className="notif-stats">
          <StatCard label="Total" value={notifications.length} />
          <StatCard label="Unread" value={unreadCount} accent />
          <StatCard label="Appointments" value={appointmentCount} />
          <StatCard label="WhatsApp" value={whatsappCount} />
        </div>

        <div className="notif-toolbar">
          <div className="notif-filters">
            {["all", "unread", "read"].map((f) => (
              <button
                key={f}
                className={`notif-filter-btn ${filter === f ? "active" : ""}`}
                onClick={() => setFilter(f)}
                type="button"
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>

          <div className="notif-toolbar-right">
            <input
              className="notif-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search subject, lead, or message..."
            />
            {visible.filter((n) => !n.read).length ? (
              <button className="notif-mark-all" onClick={() => markAllVisibleAsRead(visible)} type="button">
                Mark visible as read
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="notif-empty">Loading notifications...</div>
      ) : filtered.length === 0 ? (
        <div className="notif-empty">No notifications found.</div>
      ) : (
        <>
          <Section title="Today" items={grouped.today}>
            {grouped.today.map((notif) => (
              <NotificationRow key={notif._id} notif={notif} onMarkAsRead={markAsRead} />
            ))}
          </Section>

          <Section title="Earlier This Week" items={grouped.week}>
            {grouped.week.map((notif) => (
              <NotificationRow key={notif._id} notif={notif} onMarkAsRead={markAsRead} />
            ))}
          </Section>

          <Section title="Older" items={grouped.older} defaultOpen={false}>
            {grouped.older.map((notif) => (
              <NotificationRow key={notif._id} notif={notif} onMarkAsRead={markAsRead} />
            ))}
          </Section>

          {visibleCount < filtered.length ? (
            <div className="notif-load-more-wrap">
              <button className="notif-load-more" onClick={() => setVisibleCount((v) => v + PAGE_SIZE)} type="button">
                Load More
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}