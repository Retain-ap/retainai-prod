import React, { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  FaArrowRight,
  FaCalendarCheck,
  FaChartLine,
  FaClock,
  FaFire,
  FaHeart,
  FaRegLightbulb,
  FaUserCheck,
  FaUsers,
} from "react-icons/fa";
import { apiUrl } from "../apiBase";
import "./product-system.css";
import "./Insights.css";

const DAY = 86400000;
const HEALTH_COLORS = ["#57d38c", "#f7cb53", "#ff9f66", "#ff6b6b"];
const SOURCE_COLORS = ["#f7cb53", "#57d38c", "#70a7ff", "#b891ff", "#ff9f66", "#7d8797"];

function safeDate(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
}

function daysSince(value) {
  const date = safeDate(value);
  return date ? Math.max(0, Math.floor((Date.now() - date.getTime()) / DAY)) : null;
}

function contactName(contact) {
  return contact?.name || contact?.first_name || contact?.email || "Unnamed contact";
}

function contactLastActivity(contact) {
  return (
    contact?.last_reply_at ||
    contact?.last_inbound_at ||
    contact?.last_contacted ||
    contact?.lastContacted ||
    contact?.last_contact ||
    contact?.updated_at ||
    contact?.createdAt ||
    contact?.created_at
  );
}

function healthBucket(contact) {
  const age = daysSince(contactLastActivity(contact));
  const status = String(contact?.status || "").toLowerCase();
  if (["closed", "won", "active"].includes(status) || (age !== null && age <= 7)) return "Healthy";
  if (age !== null && age <= 14) return "Cooling";
  if (age !== null && age <= 30) return "At risk";
  return "Needs attention";
}

function monthKey(value) {
  const date = safeDate(value);
  if (!date) return null;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function shortMonth(key) {
  if (!key) return "";
  const [year, month] = key.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: "short" });
}

function appointmentDate(item) {
  return safeDate(item?.appointment_time || item?.start || item?.date);
}

function compactNumber(value) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value || 0);
}

function Metric({ icon, label, value, detail, tone = "" }) {
  return (
    <article className={`insights-metric ${tone}`}>
      <div className="insights-metric-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function EmptyState({ children }) {
  return <div className="insights-empty">{children}</div>;
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="insights-tooltip">
      <strong>{label}</strong>
      {payload.map((item) => (
        <span key={item.dataKey} style={{ color: item.color }}>
          {item.name}: {item.value}
        </span>
      ))}
    </div>
  );
}

export default function Insights({ leads = [], user }) {
  const [appointments, setAppointments] = useState([]);
  const [loadingAppointments, setLoadingAppointments] = useState(true);
  const workspaceEmail = user?.org_id || user?.orgOwnerEmail || user?.email || "";

  useEffect(() => {
    let cancelled = false;
    async function loadAppointments() {
      if (!user?.email) {
        setAppointments([]);
        setLoadingAppointments(false);
        return;
      }
      try {
        const response = await fetch(
          apiUrl(`appointments/${encodeURIComponent(user.email)}`),
          { credentials: "include", cache: "no-store", headers: { Accept: "application/json" } }
        );
        const data = await response.json().catch(() => ({}));
        if (!cancelled) setAppointments(Array.isArray(data?.appointments) ? data.appointments : []);
      } catch {
        if (!cancelled) setAppointments([]);
      } finally {
        if (!cancelled) setLoadingAppointments(false);
      }
    }
    loadAppointments();
    const refresh = () => loadAppointments();
    window.addEventListener("appointments:changed", refresh);
    return () => {
      cancelled = true;
      window.removeEventListener("appointments:changed", refresh);
    };
  }, [user?.email]);

  const analytics = useMemo(() => {
    const contacts = Array.isArray(leads) ? leads : [];
    const now = new Date();
    const upcoming = appointments
      .map((item) => ({ ...item, dateObj: appointmentDate(item) }))
      .filter((item) => item.dateObj && item.dateObj >= now && !item.done && item.status !== "cancelled")
      .sort((a, b) => a.dateObj - b.dateObj);

    const healthCounts = { Healthy: 0, Cooling: 0, "At risk": 0, "Needs attention": 0 };
    contacts.forEach((contact) => {
      healthCounts[healthBucket(contact)] += 1;
    });
    const healthData = Object.entries(healthCounts).map(([name, value]) => ({ name, value }));

    const sourceMap = {};
    contacts.forEach((contact) => {
      const source = String(contact?.source || "Direct").trim() || "Direct";
      sourceMap[source] = (sourceMap[source] || 0) + 1;
    });
    const sourceData = Object.entries(sourceMap)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 6);

    const months = new Map();
    const seed = new Date(now.getFullYear(), now.getMonth() - 5, 1);
    for (let index = 0; index < 6; index += 1) {
      const date = new Date(seed.getFullYear(), seed.getMonth() + index, 1);
      const key = monthKey(date);
      months.set(key, { key, month: shortMonth(key), contacts: 0, appointments: 0 });
    }
    contacts.forEach((contact) => {
      const key = monthKey(contact?.createdAt || contact?.created_at);
      if (months.has(key)) months.get(key).contacts += 1;
    });
    appointments.forEach((appointment) => {
      const key = monthKey(appointment?.appointment_time || appointment?.created_at);
      if (months.has(key)) months.get(key).appointments += 1;
    });

    const queue = contacts
      .map((contact) => {
        const bucket = healthBucket(contact);
        const age = daysSince(contactLastActivity(contact));
        const priority = bucket === "Needs attention" ? 4 : bucket === "At risk" ? 3 : bucket === "Cooling" ? 2 : 1;
        return {
          id: contact?.id || contact?.email || contactName(contact),
          name: contactName(contact),
          email: contact?.email || "",
          bucket,
          age,
          priority:
            priority +
            ((contact?.tags || []).some((tag) => String(tag).toLowerCase() === "vip") ? 1 : 0),
          suggestion:
            bucket === "Needs attention"
              ? "Send a personal win-back message"
              : bucket === "At risk"
              ? "Check in before the relationship cools"
              : "Keep the relationship moving",
        };
      })
      .filter((item) => item.priority >= 3)
      .sort((a, b) => b.priority - a.priority || (b.age || 0) - (a.age || 0))
      .slice(0, 6);

    const active = contacts.filter((contact) => {
      const age = daysSince(contactLastActivity(contact));
      return age !== null && age <= 14;
    }).length;
    const appointmentContactKeys = new Set(
      appointments
        .flatMap((item) => [item?.lead_id, String(item?.lead_email || "").toLowerCase()])
        .filter(Boolean)
    );
    const bookedContacts = contacts.filter(
      (contact) =>
        appointmentContactKeys.has(contact?.id) ||
        appointmentContactKeys.has(String(contact?.email || "").toLowerCase())
    ).length;

    return {
      total: contacts.length,
      active,
      atRisk: healthCounts["At risk"] + healthCounts["Needs attention"],
      upcoming,
      healthData,
      sourceData,
      trend: Array.from(months.values()),
      queue,
      bookingRate: contacts.length ? Math.round((bookedContacts / contacts.length) * 100) : 0,
    };
  }, [leads, appointments]);

  const headline =
    analytics.atRisk > 0
      ? `${analytics.atRisk} relationship${analytics.atRisk === 1 ? "" : "s"} need attention`
      : "Your customer relationships look healthy";

  return (
    <div className="product-page insights-page">
      <header className="product-hero insights-hero">
        <div>
          <div className="product-eyebrow">Relationship intelligence</div>
          <h1>Insights</h1>
          <p>{headline}. Use this page to decide who to contact and what to improve next.</p>
        </div>
        <div className="insights-workspace">
          <span>Workspace</span>
          <strong>{workspaceEmail || "Current account"}</strong>
          <small>Updated from live CRM activity</small>
        </div>
      </header>

      <section className="insights-metric-grid" aria-label="Key relationship metrics">
        <Metric icon={<FaUsers />} label="Total contacts" value={compactNumber(analytics.total)} detail="People in this workspace" />
        <Metric icon={<FaUserCheck />} label="Recently engaged" value={compactNumber(analytics.active)} detail="Activity in the last 14 days" tone="healthy" />
        <Metric icon={<FaFire />} label="Needs attention" value={compactNumber(analytics.atRisk)} detail="At-risk or inactive relationships" tone={analytics.atRisk ? "warning" : "healthy"} />
        <Metric icon={<FaCalendarCheck />} label="Upcoming bookings" value={compactNumber(analytics.upcoming.length)} detail="Scheduled appointments ahead" />
        <Metric icon={<FaChartLine />} label="Contact-to-booking" value={`${analytics.bookingRate}%`} detail="Contacts with an appointment" />
      </section>

      <section className="insights-primary-grid">
        <article className="product-card insights-chart-card">
          <div className="product-card-header">
            <div>
              <div className="product-eyebrow">Six-month movement</div>
              <h2>Growth and bookings</h2>
              <p className="product-card-copy">New contacts compared with appointments created.</p>
            </div>
          </div>
          <div className="insights-chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={analytics.trend} margin={{ top: 10, right: 6, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="contactsFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f7cb53" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#f7cb53" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,.06)" vertical={false} />
                <XAxis dataKey="month" stroke="#7d8797" tickLine={false} axisLine={false} />
                <YAxis stroke="#7d8797" tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} />
                <Area type="monotone" dataKey="contacts" name="New contacts" stroke="#f7cb53" fill="url(#contactsFill)" strokeWidth={3} />
                <Area type="monotone" dataKey="appointments" name="Appointments" stroke="#57d38c" fill="transparent" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="product-card">
          <div className="product-card-header">
            <div>
              <div className="product-eyebrow">Customer health</div>
              <h2>Relationship mix</h2>
              <p className="product-card-copy">Based on the recency of each customer interaction.</p>
            </div>
          </div>
          {analytics.total ? (
            <>
              <div className="insights-donut">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={analytics.healthData} dataKey="value" nameKey="name" innerRadius={64} outerRadius={92} paddingAngle={3}>
                      {analytics.healthData.map((entry, index) => <Cell key={entry.name} fill={HEALTH_COLORS[index]} />)}
                    </Pie>
                    <Tooltip content={<ChartTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
                <div><strong>{analytics.total}</strong><span>contacts</span></div>
              </div>
              <div className="insights-legend">
                {analytics.healthData.map((item, index) => (
                  <div key={item.name}><i style={{ background: HEALTH_COLORS[index] }} /><span>{item.name}</span><strong>{item.value}</strong></div>
                ))}
              </div>
            </>
          ) : <EmptyState>Import contacts to see relationship health.</EmptyState>}
        </article>
      </section>

      <section className="insights-secondary-grid">
        <article className="product-card">
          <div className="product-card-header">
            <div>
              <div className="product-eyebrow">Recommended next actions</div>
              <h2>Retention queue</h2>
              <p className="product-card-copy">The relationships most likely to benefit from attention now.</p>
            </div>
          </div>
          <div className="insights-action-list">
            {analytics.queue.map((item) => (
              <div className="insights-action-row" key={item.id}>
                <div className="insights-avatar">{item.name.slice(0, 2).toUpperCase()}</div>
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.suggestion}</span>
                  <small>{item.age === null ? "No previous activity" : `${item.age} days since activity`}</small>
                </div>
                <span className={`status-pill ${item.bucket === "Needs attention" ? "past_due" : "trial"}`}>{item.bucket}</span>
                <button className="insights-icon-button" title="Open Contacts" onClick={() => window.dispatchEvent(new CustomEvent("retainai:navigate", { detail: "dashboard" }))}>
                  <FaArrowRight />
                </button>
              </div>
            ))}
            {!analytics.queue.length && <EmptyState>No urgent follow-ups right now.</EmptyState>}
          </div>
        </article>

        <article className="product-card">
          <div className="product-card-header">
            <div>
              <div className="product-eyebrow">Acquisition</div>
              <h2>Where contacts come from</h2>
              <p className="product-card-copy">Use reliable sources to decide where to focus marketing.</p>
            </div>
          </div>
          {analytics.sourceData.length ? (
            <div className="insights-source-chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analytics.sourceData} layout="vertical" margin={{ top: 0, right: 18, left: 0, bottom: 0 }}>
                  <XAxis type="number" hide allowDecimals={false} />
                  <YAxis dataKey="name" type="category" width={90} stroke="#9aa3ab" axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="value" name="Contacts" radius={[0, 7, 7, 0]}>
                    {analytics.sourceData.map((item, index) => <Cell key={item.name} fill={SOURCE_COLORS[index]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyState>Contact-source data will appear after import.</EmptyState>}
        </article>
      </section>

      <section className="insights-bottom-grid">
        <article className="product-card">
          <div className="product-card-header">
            <div>
              <div className="product-eyebrow">Schedule</div>
              <h2>Upcoming appointments</h2>
              <p className="product-card-copy">The next customer commitments across your workspace.</p>
            </div>
          </div>
          <div className="insights-appointment-list">
            {analytics.upcoming.slice(0, 6).map((appointment) => (
              <div key={appointment.id || `${appointment.lead_email}-${appointment.dateObj}`}>
                <div className="insights-calendar-icon"><FaCalendarCheck /></div>
                <div>
                  <strong>{appointment.lead_full_name || appointment.lead_first_name || appointment.lead_email || "Customer appointment"}</strong>
                  <span>{appointment.title || appointment.service || "Appointment"}</span>
                </div>
                <time>{appointment.dateObj.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</time>
              </div>
            ))}
            {!analytics.upcoming.length && <EmptyState>{loadingAppointments ? "Loading appointments..." : "No upcoming appointments."}</EmptyState>}
          </div>
        </article>

        <article className="product-card insights-briefing">
          <div className="insights-briefing-icon"><FaRegLightbulb /></div>
          <div>
            <div className="product-eyebrow">AI owner briefing</div>
            <h2>{headline}</h2>
            <p>
              {analytics.atRisk
                ? "Start with the retention queue, send one personal message, and record the outcome. Small daily follow-ups compound into stronger retention."
                : "Keep your momentum by confirming upcoming appointments and asking recent customers for referrals or reviews."}
            </p>
          </div>
          <div className="insights-briefing-facts">
            <span><FaHeart /> {analytics.active} engaged contacts</span>
            <span><FaClock /> {analytics.upcoming.length} upcoming bookings</span>
          </div>
        </article>
      </section>
    </div>
  );
}
