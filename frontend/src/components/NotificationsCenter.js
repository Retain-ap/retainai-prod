import React, { useEffect, useMemo, useState } from "react";
import { API_BASE } from "../config";
import "./NotificationsCenter.css";

const ping = (name) => window.dispatchEvent(new Event(name));

function normalizeNotification(n, idx) {
  const subject =
    n.subject ||
    n.title ||
    n.type ||
    "Notification";

  const message =
    n.message ||
    n.body ||
    n.text ||
    "";

  const timestamp =
    n.timestamp ||
    n.created_at ||
    n.time ||
    "";

  const channel =
    (n.channel || n.type || "").toLowerCase();

  return {
    ...n,
    subject,
    message,
    timestamp,
    channel,
    lead_email: n.lead_email || n.leadEmail || n.email || "",
    lead_name: n.lead_name || n.leadName || "",
    read: n.read ?? false,
    _id: String(n.id ?? n._id ?? n.uuid ?? idx),
    _idx: idx,
  };
}

function iconForNotification(notif) {
  const s = String(notif.subject || "").toLowerCase();
  const c = String(notif.channel || "").toLowerCase();

  if (c.includes("whatsapp") || s.includes("whatsapp")) return "💬";
  if (c.includes("email") || s.includes("email")) return "📧";
  if (s.includes("appointment") || s.includes("calendar")) return "📅";
  if (s.includes("reminder")) return "🔔";
  if (s.includes("automation")) return "⚙️";
  return "📩";
}

function labelForNotification(notif) {
  const c = String(notif.channel || "").toLowerCase();
  if (c.includes("whatsapp")) return "WhatsApp";
  if (c.includes("email")) return "Email";
  if (c.includes("automation")) return "Automation";
  if (c.includes("appointment")) return "Appointment";
  return "App";
}

export default function NotificationsCenter({ user }) {
  const API = (() => {
    const env = (v) => (v && v.trim()) || "";
    const fromEnv =
      env(process.env.REACT_APP_API_URL) ||
      env(process.env.REACT_APP_API_BASE);
    if (fromEnv) return fromEnv.replace(/\/$/, "");
    return API_BASE;
  })();

  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");

  const load = async () => {
    if (!user?.email) return;
    setLoading(true);

    try {
      const res = await fetch(
        `${API}/api/notifications/${encodeURIComponent(user.email)}`
      );

      const data = await res.json().catch(() => ({}));
      const rows = Array.isArray(data?.notifications)
        ? data.notifications
        : [];

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
  }, [API, user?.email]);

  const markAsRead = async (notif) => {
    setNotifications((ns) =>
      ns.map((n) => (n._id === notif._id ? { ...n, read: true } : n))
    );

    const idParam = notif.id ?? notif._id ?? notif.uuid ?? notif._idx;

    try {
      await fetch(
        `${API}/api/notifications/${encodeURIComponent(
          user.email
        )}/${encodeURIComponent(idParam)}/mark_read`,
        { method: "POST" }
      );
    } catch {
      // keep optimistic state
    }

    ping("notifications:changed");
  };

  const visible = useMemo(() => {
    const list =
      filter === "all"
        ? notifications
        : notifications.filter((n) =>
            filter === "unread" ? !n.read : n.read
          );

    return [...list].sort(
      (a, b) =>
        new Date(b.timestamp || 0).getTime() -
        new Date(a.timestamp || 0).getTime()
    );
  }, [notifications, filter]);

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

  return (
    <div className="notif-root">
      <div className="notif-header">
        <div className="notif-title-row">
          <h2 className="notif-title">Notifications</h2>
          {unreadCount > 0 && (
            <span className="notif-badge" title="Unread">
              {unreadCount}
            </span>
          )}
        </div>

        <p className="notif-subtitle">
          All RetainAI activity appears here, including emails, WhatsApp activity,
          reminders, automations, and appointment updates.
        </p>

        <div className="notif-filters">
          {["all", "unread", "read"].map((f) => (
            <button
              key={f}
              className={`notif-filter-btn ${filter === f ? "active" : ""}`}
              onClick={() => setFilter(f)}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="notif-empty">Loading notifications…</div>
      ) : visible.length === 0 ? (
        <div className="notif-empty">No notifications found.</div>
      ) : (
        <ul className="notif-list">
          {visible.map((notif) => (
            <li
              key={notif._id}
              className={`notif-item ${notif.read ? "read" : "unread"}`}
            >
              <div className="notif-icon" aria-hidden>
                {iconForNotification(notif)}
              </div>

              <div className="notif-body">
                <div className="notif-subject-row">
                  <div className="notif-subject">{notif.subject || "—"}</div>
                  <span className="notif-channel-pill">
                    {labelForNotification(notif)}
                  </span>
                </div>

                {notif.message && (
                  <div className="notif-message">{notif.message}</div>
                )}

                <div className="notif-meta">
                  {(notif.lead_name || notif.lead_email) && (
                    <span className="notif-lead">
                      Lead: <b>{notif.lead_name || notif.lead_email}</b>
                    </span>
                  )}
                  <span className="notif-time">
                    {notif.timestamp
                      ? new Date(notif.timestamp).toLocaleString()
                      : ""}
                  </span>
                </div>
              </div>

              {!notif.read && (
                <button
                  className="notif-mark-read"
                  onClick={() => markAsRead(notif)}
                >
                  Mark as Read
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}