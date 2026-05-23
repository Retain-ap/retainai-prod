// src/components/Analytics.jsx
import React, { useEffect, useMemo, useState } from "react";
import {
  FunnelChart,
  Funnel,
  LabelList,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
  AreaChart,
  Area,
} from "recharts";
import {
  FaStar,
  FaFire,
  FaLightbulb,
  FaCheckCircle,
  FaCalendarAlt,
  FaUsers,
  FaPhoneAlt,
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
const RED = "#e66565";
const BLUE = "#5b8def";

const N1 = "#cfd5db";
const N2 = "#8b949e";
const N3 = "#495056";

/* ===== API ===== */
const API_BASE =
  (process.env.REACT_APP_API_BASE && process.env.REACT_APP_API_BASE.trim()) ||
  (process.env.REACT_APP_API_URL && process.env.REACT_APP_API_URL.trim()) ||
  window.location.origin.replace(/\/$/, "");

/* ===== HELPERS ===== */
function normEmail(v) {
  return String(v || "").trim().toLowerCase();
}

function pad2(n) {
  return String(n).padStart(2, "0");
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

function daysBetween(a, b) {
  return Math.floor((a.getTime() - b.getTime()) / 86400000);
}

function monthKey(dateValue) {
  const d = safeDate(dateValue);
  if (!d) return null;
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function titleCaseTag(s) {
  const t = String(s || "").trim();
  if (!t) return "";
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function hasTag(lead, targets) {
  const tags = (lead?.tags || []).map((t) => String(t || "").trim().toLowerCase());
  return targets.some((target) => tags.includes(String(target).toLowerCase()));
}

function appointmentDateObj(appt) {
  if (appt?.appointment_time) return safeDate(appt.appointment_time);
  if (appt?.date) {
    return safeDate(`${appt.date}T${appt.time || "00:00"}`);
  }
  return null;
}

function getLeadDisplayName(lead) {
  return lead?.name || lead?.email || "Unnamed Lead";
}

/* ===== APPOINTMENT MERGE ===== */
function normalizeBackendAppointment(raw) {
  const dt = safeDate(raw?.appointment_time);
  if (!dt) return null;

  return {
    source: "backend",
    id:
      raw?.id ||
      raw?._id ||
      raw?.appointment_id ||
      raw?.appointmentId ||
      raw?.appointmentID ||
      `backend-${raw?.lead_email || raw?.lead_id || dt.toISOString()}`,
    lead_id: raw?.lead_id || "",
    lead_email: normEmail(raw?.lead_email || ""),
    lead_name:
      raw?.lead_full_name ||
      [raw?.lead_first_name, raw?.lead_last_name].filter(Boolean).join(" ") ||
      raw?.lead_email ||
      "Client",
    title: raw?.title || raw?.lead_first_name || raw?.business_name || "Appointment",
    dateObj: dt,
    done: !!(raw?.done ?? raw?.completed ?? raw?.is_done),
  };
}

function normalizeLocalAppointmentsFromLeads(leads = []) {
  const out = [];

  (leads || []).forEach((lead) => {
    (lead.appointments || []).forEach((appt, idx) => {
      const dt = safeDate(`${appt.date}T${appt.time || "00:00"}`);
      if (!dt) return;

      out.push({
        source: "local",
        id: appt._localKey || `${lead.id || lead.email || "lead"}-${idx}-${appt.title || "appt"}`,
        lead_id: lead?.id || "",
        lead_email: normEmail(lead?.email || ""),
        lead_name: getLeadDisplayName(lead),
        title: appt?.title || "Appointment",
        dateObj: dt,
        done: !!appt?.done,
      });
    });
  });

  return out;
}

function dedupeAppointments(appointments = []) {
  const seen = new Set();
  const out = [];

  appointments.forEach((appt) => {
    const key = [
      appt.lead_id || "",
      appt.lead_email || "",
      appt.title || "",
      appt.dateObj ? appt.dateObj.toISOString() : "",
    ].join("|");

    if (seen.has(key)) return;
    seen.add(key);
    out.push(appt);
  });

  return out;
}

/* ===== CORE ANALYTICS ===== */
function getConversionStats(leads = [], appointments = []) {
  const total = leads.length;

  const contacted = leads.filter(
    (l) => !!l.last_contacted || !!l.lastContacted
  ).length;

  const apptLeadKeys = new Set(
    appointments.map((a) => a.lead_id || a.lead_email).filter(Boolean)
  );
  const appointmentSet = leads.filter((lead) =>
    apptLeadKeys.has(lead?.id || "") || apptLeadKeys.has(normEmail(lead?.email || ""))
  ).length;

  const closed = leads.filter((l) =>
    hasTag(l, ["closed", "won", "completed"])
  ).length;

  return [
    { stage: "Total Leads", value: total },
    { stage: "Contacted", value: contacted },
    { stage: "Appointment Set", value: appointmentSet },
    { stage: "Closed", value: closed },
  ];
}

function getFunnelRates(stats) {
  const out = [];
  for (let i = 1; i < stats.length; ++i) {
    const prev = stats[i - 1].value;
    const curr = stats[i].value;
    out.push(prev === 0 ? 0 : Math.round((curr / prev) * 100));
  }
  return out;
}

function getSentimentByMonth(leads = []) {
  const map = {};
  leads.forEach((l) => {
    const m =
      monthKey(l.last_contacted || l.lastContacted || l.createdAt) ||
      monthKey(new Date());
    const tag =
      (l.tags || []).find((t) =>
        ["happy", "upset", "neutral"].includes(String(t || "").trim().toLowerCase())
      ) || "Neutral";

    const key = titleCaseTag(tag);
    if (!map[m]) map[m] = { month: m, Happy: 0, Upset: 0, Neutral: 0 };
    if (!map[m][key]) map[m][key] = 0;
    map[m][key]++;
  });

  return Object.values(map).sort((a, b) => a.month.localeCompare(b.month));
}

function getSourceBreakdown(leads = []) {
  const counts = {};
  const PALETTE = [GOLD, N1, N2, N3, "#343a40", "#5a626a"];

  leads.forEach((l) => {
    const src = l.source || "Other";
    counts[src] = (counts[src] || 0) + 1;
  });

  return Object.entries(counts).map(([name, value], i) => ({
    name,
    value,
    color: PALETTE[i % PALETTE.length],
  }));
}

function getVipLeads(leads = []) {
  return leads.filter((l) => hasTag(l, ["vip"]));
}

function getColdLeads(leads = [], days = 14) {
  const now = Date.now();
  return leads.filter((l) => {
    const dt = safeDate(l.last_contacted || l.lastContacted || l.createdAt || Date.now());
    if (!dt) return false;
    return now - dt.getTime() > days * 86400000;
  });
}

function getAITip(leads = []) {
  const coldVIPs = leads.filter(
    (l) =>
      hasTag(l, ["vip"]) &&
      (!l.last_contacted ||
        Date.now() - new Date(l.last_contacted).getTime() > 10 * 86400000)
  );

  if (coldVIPs.length) {
    return `You have ${coldVIPs.length} VIP${coldVIPs.length > 1 ? "s" : ""} who need follow-up this week.`;
  }

  return "Your VIP leads look up to date. Keep momentum on follow-ups.";
}

function getNextAction(leads = []) {
  const cold = getColdLeads(leads);
  if (cold.length) return `Reach out to ${getLeadDisplayName(cold[0])}. It has been a while.`;
  return "No urgent follow-up risk detected right now.";
}

function getAppointmentsSummary(appointments = []) {
  const now = new Date();
  const startToday = new Date(now);
  startToday.setHours(0, 0, 0, 0);

  const endToday = new Date(now);
  endToday.setHours(23, 59, 59, 999);

  const sevenDays = new Date(startToday);
  sevenDays.setDate(sevenDays.getDate() + 7);

  let overdue = 0;
  let today = 0;
  let next7 = 0;
  let later = 0;
  let done = 0;

  appointments.forEach((appt) => {
    const dt = appt.dateObj;
    if (!dt) return;

    if (appt.done) {
      done++;
      return;
    }

    if (dt < now) {
      overdue++;
      return;
    }

    if (dt >= startToday && dt <= endToday) {
      today++;
      return;
    }

    if (dt > endToday && dt <= sevenDays) {
      next7++;
      return;
    }

    later++;
  });

  return { overdue, today, next7, later, done };
}

function getLeaderboard(leads = [], appointments = []) {
  const countMap = {};

  appointments.forEach((appt) => {
    const key = appt.lead_id || appt.lead_email;
    if (!key) return;
    countMap[key] = (countMap[key] || 0) + 1;
  });

  const arr = leads.map((l) => {
    const key = l.id || normEmail(l.email);
    return {
      name: getLeadDisplayName(l),
      count: countMap[key] || 0,
    };
  });

  arr.sort((a, b) => b.count - a.count);
  return arr.filter((x) => x.count > 0).slice(0, 5);
}

function getLeadsByMonth(leads = []) {
  const map = {};
  leads.forEach((l) => {
    const m = monthKey(l.createdAt) || monthKey(new Date());
    map[m] = (map[m] || 0) + 1;
  });

  return Object.keys(map)
    .sort()
    .map((month) => ({ month, count: map[month] }));
}

function getAvgDaysSinceContact(leads = []) {
  const now = new Date();
  const diffs = leads
    .map((l) => {
      const last = l.last_contacted || l.lastContacted || l.createdAt;
      const d = safeDate(last);
      return d ? daysBetween(now, d) : 0;
    })
    .filter((n) => Number.isFinite(n));

  if (!diffs.length) return 0;
  return Math.round(diffs.reduce((a, b) => a + b, 0) / diffs.length);
}

function getTopTags(leads = [], limit = 8) {
  const counts = {};
  leads.forEach((l) =>
    (l.tags || []).forEach((t) => {
      const key = titleCaseTag(String(t || "").trim());
      if (!key) return;
      counts[key] = (counts[key] || 0) + 1;
    })
  );

  const arr = Object.entries(counts).map(([tag, value]) => ({ tag, value }));
  arr.sort((a, b) => b.value - a.value);
  return arr.slice(0, limit);
}

/* ===== HEATMAP ===== */
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HOURS = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);

function getHeatmapMatrix(appointments = []) {
  const matrix = Array(7)
    .fill(0)
    .map(() => Array(24).fill(0));

  appointments.forEach((appt) => {
    const d = appt.dateObj;
    if (!d) return;
    const day = d.getDay();
    const hour = d.getHours();
    if (day >= 0 && day <= 6 && hour >= 0 && hour < 24) matrix[day][hour]++;
  });

  return matrix;
}

function AppointmentsHeatmap({ appointments }) {
  const matrix = getHeatmapMatrix(appointments);
  return (
    <div style={{ ...card, alignSelf: "start" }}>
      <div style={cardTitle}>
        Appointments Heatmap{" "}
        <span style={{ color: SUBTEXT, fontWeight: 700, fontSize: 12 }}>
          (all scheduled appointments)
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={{ width: 36 }} />
              {HOURS.map((h) => (
                <th
                  key={h}
                  style={{ color: SUBTEXT, fontWeight: 700, fontSize: 12, padding: "2px 6px" }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => (
              <tr key={DAYS[i]}>
                <td style={{ color: TEXT, fontWeight: 800, paddingRight: 8 }}>{DAYS[i]}</td>
                {row.map((count, h) => (
                  <td
                    key={h}
                    style={{
                      minWidth: 30,
                      minHeight: 26,
                      borderRadius: 8,
                      textAlign: "center",
                      fontWeight: 900,
                      color: count > 0 ? GOLD : TEXT,
                      background: count > 0 ? "#1e2326" : BG,
                      border: `1.4px solid ${count > 0 ? GOLD : BORDER}`,
                    }}
                  >
                    {count > 0 ? count : ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ===== SHARED STYLES ===== */
const card = {
  background: CARD,
  borderRadius: 16,
  padding: 18,
  border: `1px solid ${BORDER}`,
  boxShadow: "0 2px 18px rgba(0,0,0,0.35)",
};

const cardTitle = { fontWeight: 900, color: TEXT, marginBottom: 10 };

const pill = {
  ...card,
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "12px 14px",
};

const goldChip = {
  background: GOLD,
  color: "#111",
  fontWeight: 800,
  borderRadius: 10,
  padding: "3px 10px",
};

const RAD = Math.PI / 180;
const renderPieLabel = ({ cx, cy, midAngle, outerRadius, percent, name }) => {
  const r = outerRadius + 20;
  const x = cx + r * Math.cos(-midAngle * RAD);
  const y = cy + r * Math.sin(-midAngle * RAD);
  return (
    <text
      x={x}
      y={y}
      fill={TEXT}
      textAnchor={x > cx ? "start" : "end"}
      dominantBaseline="central"
      style={{ fontWeight: 800, fontSize: 12 }}
    >
      {`${name} (${Math.round(percent * 100)}%)`}
    </text>
  );
};

export default function Analytics({ leads = [], user }) {
  const [backendAppointments, setBackendAppointments] = useState([]);
  const effectiveEmail = user?.org_id || user?.email || "";

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

  const allAppointments = useMemo(() => {
    const localAppointments = normalizeLocalAppointmentsFromLeads(leads);
    const backendNormalized = (backendAppointments || [])
      .map((raw) => normalizeBackendAppointment(raw))
      .filter(Boolean);

    return dedupeAppointments([...localAppointments, ...backendNormalized]);
  }, [leads, backendAppointments]);

  const funnelStats = useMemo(() => getConversionStats(leads, allAppointments), [leads, allAppointments]);
  const funnelRates = useMemo(() => getFunnelRates(funnelStats), [funnelStats]);
  const sentimentData = useMemo(() => getSentimentByMonth(leads), [leads]);
  const sourceData = useMemo(() => getSourceBreakdown(leads), [leads]);
  const vipLeads = useMemo(() => getVipLeads(leads), [leads]);
  const coldLeads = useMemo(() => getColdLeads(leads), [leads]);
  const apptSummary = useMemo(() => getAppointmentsSummary(allAppointments), [allAppointments]);
  const leadsByMonth = useMemo(() => getLeadsByMonth(leads), [leads]);
  const avgDaysSinceContact = useMemo(() => getAvgDaysSinceContact(leads), [leads]);
  const leaderboard = useMemo(() => getLeaderboard(leads, allAppointments), [leads, allAppointments]);
  const topTags = useMemo(() => getTopTags(leads), [leads]);

  return (
    <div style={{ padding: 28, background: BG, minHeight: "100vh", boxSizing: "border-box" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          alignItems: "center",
          gap: 24,
          padding: "0 0 18px 0",
          borderBottom: `1px solid ${BORDER}`,
        }}
      >
        <h2
          style={{
            color: TEXT,
            fontWeight: 900,
            margin: 0,
            fontSize: 28,
            letterSpacing: "-0.5px",
          }}
        >
          Analytics & Insights
        </h2>
        <div style={{ color: SUBTEXT, fontSize: 12 }}>
          {effectiveEmail ? `Account: ${effectiveEmail}` : ""}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.2fr 1fr 1fr",
          gap: 18,
          alignItems: "stretch",
          marginTop: 18,
        }}
      >
        <div style={card}>
          <div style={cardTitle}>Lead Conversion Funnel</div>
          <div style={{ width: "100%", display: "flex", justifyContent: "center" }}>
            <FunnelChart width={340} height={220}>
              <Funnel dataKey="value" data={funnelStats} isAnimationActive fill={GOLD} stroke={BORDER}>
                <LabelList dataKey="stage" position="inside" style={{ fill: "#ffffff", fontWeight: 900 }} />
              </Funnel>
            </FunnelChart>
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              marginTop: 6,
              color: SUBTEXT,
              fontWeight: 700,
            }}
          >
            {funnelRates.map((rate, idx) => (
              <span key={idx} style={{ color: GOLD }}>
                ↓ {rate}%
              </span>
            ))}
          </div>
        </div>

        <div style={card}>
          <div style={cardTitle}>Client Sentiment Over Time</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={sentimentData}>
              <XAxis dataKey="month" tick={{ fill: SUBTEXT, fontWeight: 600 }} stroke={BORDER} />
              <YAxis tick={{ fill: SUBTEXT, fontWeight: 600 }} stroke={BORDER} allowDecimals={false} />
              <Tooltip contentStyle={{ background: CARD, border: `1px solid ${BORDER}`, color: TEXT }} />
              <Legend wrapperStyle={{ color: TEXT }} />
              <Bar dataKey="Happy" stackId="a" fill={GOLD} />
              <Bar dataKey="Neutral" stackId="a" fill={N1} />
              <Bar dataKey="Upset" stackId="a" fill={N3} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={card}>
          <div style={cardTitle}>Lead Source Breakdown</div>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
              <Pie
                data={sourceData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="42%"
                outerRadius={72}
                label={renderPieLabel}
                labelLine
              >
                {sourceData.map((entry, idx) => (
                  <Cell key={`cell-${idx}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: CARD, border: `1px solid ${BORDER}`, color: TEXT }} />
              <Legend
                verticalAlign="bottom"
                align="center"
                iconType="circle"
                iconSize={10}
                wrapperStyle={{
                  color: TEXT,
                  marginTop: 36,
                  lineHeight: "16px",
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 18,
          marginTop: 18,
          alignItems: "start",
        }}
      >
        <div style={{ display: "grid", gap: 18, alignItems: "start" }}>
          <AppointmentsHeatmap appointments={allAppointments} />

          <div style={card}>
            <div style={cardTitle}>New Leads by Month</div>
            <ResponsiveContainer width="100%" height={170}>
              <AreaChart data={leadsByMonth}>
                <defs>
                  <linearGradient id="goldFade" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={GOLD} stopOpacity={0.9} />
                    <stop offset="100%" stopColor={GOLD} stopOpacity={0.15} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="month" tick={{ fill: SUBTEXT }} stroke={BORDER} />
                <YAxis tick={{ fill: SUBTEXT }} stroke={BORDER} allowDecimals={false} />
                <Tooltip contentStyle={{ background: CARD, border: `1px solid ${BORDER}`, color: TEXT }} />
                <Area type="monotone" dataKey="count" stroke={GOLD} fill="url(#goldFade)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div style={card}>
            <div style={cardTitle}>Top Tags</div>
            <ResponsiveContainer width="100%" height={170}>
              <BarChart data={topTags}>
                <XAxis dataKey="tag" tick={{ fill: SUBTEXT }} stroke={BORDER} />
                <YAxis tick={{ fill: SUBTEXT }} stroke={BORDER} allowDecimals={false} />
                <Tooltip contentStyle={{ background: CARD, border: `1px solid ${BORDER}`, color: TEXT }} />
                <Bar dataKey="value" fill={GOLD} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div style={{ display: "grid", gap: 14, alignItems: "start" }}>
          <div style={card}>
            <div style={cardTitle}>Top 5 Engaged Leads</div>
            {leaderboard.length === 0 ? (
              <div style={{ color: SUBTEXT, fontWeight: 700 }}>No leads with appointments yet.</div>
            ) : (
              leaderboard.map((l, i) => (
                <div
                  key={`${l.name}-${i}`}
                  style={{
                    fontWeight: 900,
                    color: TEXT,
                    marginBottom: 10,
                    display: "flex",
                    alignItems: "center",
                    lineHeight: 1.2,
                  }}
                >
                  <span style={{ color: GOLD, marginRight: 10 }}>{i + 1}.</span>
                  <div style={{ flex: 1 }}>{l.name}</div>
                  {l.count > 0 && <span style={goldChip}>{l.count} appt</span>}
                </div>
              ))
            )}
          </div>

          <div style={pill}>
            <FaUsers style={{ color: GOLD }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Lead Health</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14 }}>
                {coldLeads.length ? `${coldLeads.length} cold lead(s)` : "No cold leads detected"}
              </div>
            </div>
          </div>

          <div style={pill}>
            <FaPhoneAlt style={{ color: GOLD }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Avg Days Since Contact</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14 }}>
                {avgDaysSinceContact} day(s)
              </div>
            </div>
          </div>

          <div style={pill}>
            <FaLightbulb style={{ color: GOLD }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Tip of the Week</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14 }}>{getAITip(leads)}</div>
            </div>
          </div>

          <div style={pill}>
            <FaStar style={{ color: GOLD }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Top VIPs</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14 }}>
                {vipLeads.length ? vipLeads.map((l) => l.name).join(", ") : "No VIPs yet."}
              </div>
            </div>
          </div>

          <div style={pill}>
            <FaFire style={{ color: GOLD }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Leads Going Cold</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14 }}>
                {coldLeads.length ? coldLeads.map((l) => l.name).join(", ") : "All leads active"}
              </div>
            </div>
          </div>

          <div style={pill}>
            <FaCheckCircle style={{ color: GOLD }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Next Best Action</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14 }}>{getNextAction(leads)}</div>
            </div>
          </div>

          <div style={pill}>
            <FaCalendarAlt style={{ color: GOLD }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Appointment Workload</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14 }}>
                {apptSummary.overdue} overdue · {apptSummary.today} today · {apptSummary.next7} next 7 days · {apptSummary.done} done
              </div>
            </div>
          </div>

          <div style={card}>
            <div style={cardTitle}>Pipeline Summary</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <Metric label="Total" value={funnelStats[0].value} />
              <Metric label="Contacted" value={funnelStats[1].value} />
              <Metric label="Appt Set" value={funnelStats[2].value} />
              <Metric label="Closed" value={funnelStats[3].value} />
              <Metric label="Overdue appts" value={apptSummary.overdue} small />
              <Metric label="Completed appts" value={apptSummary.done} small />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, small }) {
  return (
    <div
      style={{
        background: "#1e2326",
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        padding: "10px 12px",
      }}
    >
      <div style={{ color: SUBTEXT, fontSize: 12, fontWeight: 700 }}>{label}</div>
      <div style={{ color: TEXT, fontWeight: 900, fontSize: small ? 18 : 24 }}>{value}</div>
    </div>
  );
}