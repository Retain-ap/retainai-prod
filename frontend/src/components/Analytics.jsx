import React, { useMemo } from "react";
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
  FaBell,
  FaCalendarAlt,
  FaUsers,
  FaChartLine,
} from "react-icons/fa";

/* ===== THEME ===== */
const BG = "#181a1b";
const CARD = "#232323";
const SOFT = "#1e2326";
const BORDER = "#2b2f33";
const TEXT = "#f3f4f5";
const SUBTEXT = "#9aa3ab";
const GOLD = "#f7cb53";
const GREEN = "#1bc982";
const RED = "#e66565";
const WARN = "#f7cb53";

const N1 = "#cfd5db";
const N2 = "#8b949e";
const N3 = "#495056";

/* ===== SAFE HELPERS ===== */
function toArray(v) {
  return Array.isArray(v) ? v : [];
}

function norm(s) {
  return String(s || "").trim().toLowerCase();
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

function startOfToday() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

function daysBetween(a, b) {
  return Math.floor((a.getTime() - b.getTime()) / 86400000);
}

function getCreatedDate(lead) {
  return (
    parseDateSafe(lead?.createdAt) ||
    parseDateSafe(lead?.created_at) ||
    parseDateSafe(lead?.updated_at) ||
    parseDateSafe(lead?.last_contacted) ||
    parseDateSafe(lead?.lastContacted) ||
    null
  );
}

function getLastContactDate(lead) {
  return (
    parseDateSafe(lead?.last_contacted) ||
    parseDateSafe(lead?.lastContacted) ||
    parseDateSafe(lead?.last_activity_at) ||
    parseDateSafe(lead?.updated_at) ||
    getCreatedDate(lead)
  );
}

function getLeadStatus(lead) {
  const explicit = norm(lead?.status);
  if (explicit === "cold" || explicit === "warning" || explicit === "active") {
    return explicit;
  }

  const dt = getLastContactDate(lead);
  if (!dt) return "cold";

  const age = daysBetween(new Date(), dt);
  if (age >= 14) return "cold";
  if (age >= 7) return "warning";
  return "active";
}

function isClosedLead(lead) {
  const tags = toArray(lead?.tags).map(norm);
  return tags.some((t) =>
    ["closed", "won", "completed", "complete", "converted", "booked"].includes(t)
  );
}

function isVipLead(lead) {
  return toArray(lead?.tags).map(norm).includes("vip");
}

function getAppointmentsForLead(lead) {
  return toArray(lead?.appointments);
}

function getAppointmentDate(app) {
  if (app?.appointment_time) return parseDateSafe(app.appointment_time);

  if (app?.date && app?.time) return parseDateSafe(`${app.date}T${app.time}`);
  if (app?.date) return parseDateSafe(app.date);

  return null;
}

function getLeadSource(lead) {
  return (
    lead?.source ||
    lead?.leadSource ||
    lead?.referral_source ||
    lead?.referralSource ||
    "Other"
  );
}

function getSentimentTag(lead) {
  const tags = toArray(lead?.tags).map(norm);
  if (tags.includes("happy")) return "Happy";
  if (tags.includes("upset")) return "Upset";
  return "Neutral";
}

function monthKeyFromDate(d) {
  if (!d) return "";
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

function formatMonthLabel(k) {
  if (!k || !k.includes("-")) return k || "—";
  const [year, month] = k.split("-");
  const d = new Date(Number(year), Number(month) - 1, 1);
  return d.toLocaleDateString([], { month: "short", year: "2-digit" });
}

/* ===== DATA HELPERS ===== */
function getConversionStats(leads = []) {
  const total = leads.length;

  const contacted = leads.filter((l) => !!getLastContactDate(l)).length;

  const appointment = leads.filter(
    (l) =>
      getAppointmentsForLead(l).length > 0 ||
      toArray(l?.tags).map(norm).includes("appointment set")
  ).length;

  const closed = leads.filter(isClosedLead).length;

  return [
    { stage: "Total Leads", value: total },
    { stage: "Contacted", value: contacted },
    { stage: "Appointment Set", value: appointment },
    { stage: "Closed", value: closed },
  ];
}

function getFunnelRates(stats) {
  const out = [];
  for (let i = 1; i < stats.length; i += 1) {
    const prev = stats[i - 1]?.value || 0;
    const curr = stats[i]?.value || 0;
    out.push(prev === 0 ? 0 : Math.round((curr / prev) * 100));
  }
  return out;
}

function getSentimentByMonth(leads = []) {
  const map = {};
  leads.forEach((lead) => {
    const month = monthKeyFromDate(getLastContactDate(lead) || getCreatedDate(lead));
    if (!month) return;
    const tag = getSentimentTag(lead);

    if (!map[month]) {
      map[month] = { month, Happy: 0, Upset: 0, Neutral: 0 };
    }
    map[month][tag] += 1;
  });

  return Object.values(map)
    .sort((a, b) => a.month.localeCompare(b.month))
    .map((r) => ({ ...r, monthLabel: formatMonthLabel(r.month) }));
}

function getSourceBreakdown(leads = []) {
  const counts = {};
  const PALETTE = [GOLD, N1, N2, N3, "#343a40", "#5a626a"];

  leads.forEach((lead) => {
    const src = getLeadSource(lead);
    counts[src] = (counts[src] || 0) + 1;
  });

  return Object.entries(counts).map(([name, value], i) => ({
    name,
    value,
    color: PALETTE[i % PALETTE.length],
  }));
}

function getVipLeads(leads = []) {
  return leads.filter(isVipLead);
}

function getColdLeads(leads = [], days = 14) {
  return leads.filter((lead) => {
    const explicit = norm(lead?.status);
    if (explicit === "cold") return true;
    if (explicit === "active" || explicit === "warning") return false;

    const dt = getLastContactDate(lead);
    if (!dt) return true;
    return daysBetween(new Date(), dt) >= days;
  });
}

function getWarningLeads(leads = []) {
  return leads.filter((lead) => getLeadStatus(lead) === "warning");
}

function getAITip(leads = []) {
  const coldVIPs = leads.filter((lead) => {
    if (!isVipLead(lead)) return false;
    return getLeadStatus(lead) !== "active";
  });

  if (coldVIPs.length) {
    return `You have ${coldVIPs.length} VIP${coldVIPs.length > 1 ? "s" : ""} that should be prioritized for follow-up.`;
  }

  const warnings = getWarningLeads(leads);
  if (warnings.length) {
    return `${warnings.length} lead${warnings.length > 1 ? "s are" : " is"} approaching cold status. A quick follow-up now can protect your pipeline.`;
  }

  return "Your pipeline looks healthy. Focus on consistency and closing momentum.";
}

function getNextAction(leads = []) {
  const cold = getColdLeads(leads);
  if (cold.length) {
    return `Reach out to ${cold[0]?.name || "a cold lead"} first — they are your highest follow-up priority.`;
  }

  const warning = getWarningLeads(leads);
  if (warning.length) {
    return `Follow up with ${warning[0]?.name || "a warm lead"} before they go cold.`;
  }

  return "No urgent follow-up risk right now. Keep maintaining your active leads.";
}

function getRemindersDue(leads = [], days = 7) {
  const now = startOfToday();
  const inDays = new Date(now.getTime() + days * 86400000);

  let count = 0;
  leads.forEach((lead) => {
    toArray(lead?.reminders).forEach((r) => {
      if (r?.done) return;
      const d = parseDateSafe(r?.date);
      if (d && d >= now && d <= inDays) count += 1;
    });
  });

  return count;
}

function getAppointmentsThisMonth(leads = []) {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();

  let count = 0;
  leads.forEach((lead) => {
    getAppointmentsForLead(lead).forEach((a) => {
      const d = getAppointmentDate(a);
      if (!d) return;
      if (d.getFullYear() === year && d.getMonth() === month) count += 1;
    });
  });

  return count;
}

function getLeaderboard(leads = []) {
  const arr = leads.map((lead) => ({
    name: lead?.name || lead?.email || "Unnamed Lead",
    count: getAppointmentsForLead(lead).length,
  }));

  arr.sort((a, b) => b.count - a.count);
  return arr.filter((x) => x.count > 0).slice(0, 5);
}

function getLeadsByMonth(leads = []) {
  const map = {};
  leads.forEach((lead) => {
    const created = getCreatedDate(lead) || new Date();
    const month = monthKeyFromDate(created);
    map[month] = (map[month] || 0) + 1;
  });

  return Object.keys(map)
    .sort()
    .map((month) => ({
      month,
      monthLabel: formatMonthLabel(month),
      count: map[month],
    }));
}

function getAvgDaysSinceContact(leads = []) {
  const now = new Date();
  const diffs = leads
    .map((lead) => {
      const last = getLastContactDate(lead);
      return last ? daysBetween(now, last) : null;
    })
    .filter((n) => Number.isFinite(n));

  if (!diffs.length) return 0;
  return Math.round(diffs.reduce((a, b) => a + b, 0) / diffs.length);
}

function getTopTags(leads = [], limit = 8) {
  const counts = {};
  leads.forEach((lead) => {
    toArray(lead?.tags).forEach((tag) => {
      counts[tag] = (counts[tag] || 0) + 1;
    });
  });

  const arr = Object.entries(counts).map(([tag, value]) => ({ tag, value }));
  arr.sort((a, b) => b.value - a.value);
  return arr.slice(0, limit);
}

function getStatusBreakdown(leads = []) {
  let active = 0;
  let warning = 0;
  let cold = 0;

  leads.forEach((lead) => {
    const s = getLeadStatus(lead);
    if (s === "cold") cold += 1;
    else if (s === "warning") warning += 1;
    else active += 1;
  });

  return [
    { name: "Active", value: active, color: GREEN },
    { name: "Follow Up", value: warning, color: WARN },
    { name: "Cold", value: cold, color: RED },
  ];
}

/* ===== HEATMAP ===== */
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HOURS = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);

function getHeatmapMatrix(leads = []) {
  const matrix = Array(7)
    .fill(0)
    .map(() => Array(24).fill(0));

  leads.forEach((lead) => {
    getAppointmentsForLead(lead).forEach((app) => {
      const d = getAppointmentDate(app);
      if (!d) return;
      const day = d.getDay();
      const hour = d.getHours();
      if (day >= 0 && day <= 6 && hour >= 0 && hour < 24) {
        matrix[day][hour] += 1;
      }
    });
  });

  return matrix;
}

function AppointmentsHeatmap({ leads }) {
  const matrix = getHeatmapMatrix(leads);

  return (
    <div style={{ ...card, alignSelf: "start" }}>
      <div style={cardHeader}>
        <div style={cardTitle}>Appointments Heatmap</div>
        <div style={cardSub}>By weekday and hour</div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "separate", borderSpacing: "4px", width: "100%" }}>
          <thead>
            <tr>
              <th style={{ width: 42 }} />
              {HOURS.map((h) => (
                <th
                  key={h}
                  style={{
                    color: SUBTEXT,
                    fontWeight: 700,
                    fontSize: 11,
                    padding: "2px 4px",
                    whiteSpace: "nowrap",
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => (
              <tr key={DAYS[i]}>
                <td
                  style={{
                    color: TEXT,
                    fontWeight: 800,
                    paddingRight: 8,
                    fontSize: 12,
                  }}
                >
                  {DAYS[i]}
                </td>
                {row.map((count, h) => (
                  <td
                    key={h}
                    style={{
                      minWidth: 28,
                      height: 30,
                      borderRadius: 8,
                      textAlign: "center",
                      fontWeight: 900,
                      fontSize: 12,
                      color: count > 0 ? GOLD : SUBTEXT,
                      background: count > 0 ? "#1f2427" : BG,
                      border: `1px solid ${count > 0 ? "rgba(247,203,83,0.45)" : BORDER}`,
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

/* ===== STYLES ===== */
const card = {
  background: CARD,
  borderRadius: 18,
  padding: 18,
  border: `1px solid ${BORDER}`,
  boxShadow: "0 2px 18px rgba(0,0,0,0.35)",
};

const cardHeader = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 12,
  marginBottom: 12,
};

const cardTitle = {
  fontWeight: 900,
  color: TEXT,
  fontSize: 16,
};

const cardSub = {
  color: SUBTEXT,
  fontSize: 12,
  fontWeight: 700,
};

const pill = {
  ...card,
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "14px 15px",
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

export default function Analytics({ leads = [] }) {
  const funnelStats = useMemo(() => getConversionStats(leads), [leads]);
  const funnelRates = useMemo(() => getFunnelRates(funnelStats), [funnelStats]);
  const sentimentData = useMemo(() => getSentimentByMonth(leads), [leads]);
  const sourceData = useMemo(() => getSourceBreakdown(leads), [leads]);
  const statusData = useMemo(() => getStatusBreakdown(leads), [leads]);
  const vipLeads = useMemo(() => getVipLeads(leads), [leads]);
  const coldLeads = useMemo(() => getColdLeads(leads), [leads]);
  const remindersDue = useMemo(() => getRemindersDue(leads, 7), [leads]);
  const apptsThisMonth = useMemo(() => getAppointmentsThisMonth(leads), [leads]);
  const leadsByMonth = useMemo(() => getLeadsByMonth(leads), [leads]);
  const avgDaysSinceContact = useMemo(() => getAvgDaysSinceContact(leads), [leads]);
  const leaderboard = useMemo(() => getLeaderboard(leads), [leads]);
  const topTags = useMemo(() => getTopTags(leads), [leads]);

  const totalLeads = leads.length;
  const activeCount = statusData.find((x) => x.name === "Active")?.value || 0;
  const followUpCount = statusData.find((x) => x.name === "Follow Up")?.value || 0;
  const coldCount = statusData.find((x) => x.name === "Cold")?.value || 0;
  const closeRate = funnelStats[0]?.value
    ? Math.round(((funnelStats[3]?.value || 0) / (funnelStats[0]?.value || 1)) * 100)
    : 0;

  return (
    <div
      style={{
        padding: 28,
        background: BG,
        minHeight: "100vh",
        boxSizing: "border-box",
      }}
    >
      {/* Top bar */}
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
        <div>
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
          <div style={{ color: SUBTEXT, marginTop: 6, fontWeight: 600 }}>
            Executive view of pipeline health, follow-up risk, and lead activity.
          </div>
        </div>
        <div />
      </div>

      {/* Executive summary */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 16,
          marginTop: 18,
        }}
      >
        <SummaryCard
          icon={<FaUsers />}
          label="Total Leads"
          value={totalLeads}
          helper="All leads currently in CRM"
        />
        <SummaryCard
          icon={<FaChartLine />}
          label="Close Rate"
          value={`${closeRate}%`}
          helper="Closed leads out of total leads"
        />
        <SummaryCard
          icon={<FaCalendarAlt />}
          label="Appointments This Month"
          value={apptsThisMonth}
          helper="Scheduled from lead records"
        />
        <SummaryCard
          icon={<FaBell />}
          label="Reminders Due"
          value={remindersDue}
          helper="Open reminders due within 7 days"
        />
      </div>

      {/* Row 1 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.2fr 1fr 1fr",
          gap: 18,
          alignItems: "stretch",
          marginTop: 18,
        }}
      >
        {/* Funnel */}
        <div style={card}>
          <div style={cardHeader}>
            <div style={cardTitle}>Lead Conversion Funnel</div>
            <div style={cardSub}>Total → Contacted → Appointment → Closed</div>
          </div>

          <div style={{ width: "100%", display: "flex", justifyContent: "center" }}>
            <FunnelChart width={340} height={220}>
              <Funnel
                dataKey="value"
                data={funnelStats}
                isAnimationActive
                fill={GOLD}
                stroke={BORDER}
              >
                <LabelList
                  dataKey="stage"
                  position="inside"
                  style={{ fill: "#ffffff", fontWeight: 900 }}
                />
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
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            {funnelRates.map((rate, idx) => (
              <span key={idx} style={{ color: GOLD }}>
                Step {idx + 1} → {idx + 2}: {rate}%
              </span>
            ))}
          </div>
        </div>

        {/* Sentiment */}
        <div style={card}>
          <div style={cardHeader}>
            <div style={cardTitle}>Client Sentiment Over Time</div>
            <div style={cardSub}>Based on lead tags</div>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={sentimentData}>
              <XAxis dataKey="monthLabel" tick={{ fill: SUBTEXT, fontWeight: 600 }} stroke={BORDER} />
              <YAxis tick={{ fill: SUBTEXT, fontWeight: 600 }} stroke={BORDER} allowDecimals={false} />
              <Tooltip contentStyle={{ background: CARD, border: `1px solid ${BORDER}`, color: TEXT }} />
              <Legend wrapperStyle={{ color: TEXT }} />
              <Bar dataKey="Happy" stackId="a" fill={GOLD} />
              <Bar dataKey="Neutral" stackId="a" fill={N1} />
              <Bar dataKey="Upset" stackId="a" fill={N3} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Source */}
        <div style={card}>
          <div style={cardHeader}>
            <div style={cardTitle}>Lead Source Breakdown</div>
            <div style={cardSub}>Where leads are coming from</div>
          </div>
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

      {/* Row 2 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 18,
          marginTop: 18,
          alignItems: "start",
        }}
      >
        {/* LEFT */}
        <div style={{ display: "grid", gap: 18, alignItems: "start" }}>
          <AppointmentsHeatmap leads={leads} />

          <div style={card}>
            <div style={cardHeader}>
              <div style={cardTitle}>New Leads by Month</div>
              <div style={cardSub}>Lead creation trend</div>
            </div>
            <ResponsiveContainer width="100%" height={170}>
              <AreaChart data={leadsByMonth}>
                <defs>
                  <linearGradient id="goldFade" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={GOLD} stopOpacity={0.9} />
                    <stop offset="100%" stopColor={GOLD} stopOpacity={0.15} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="monthLabel" tick={{ fill: SUBTEXT }} stroke={BORDER} />
                <YAxis tick={{ fill: SUBTEXT }} stroke={BORDER} allowDecimals={false} />
                <Tooltip contentStyle={{ background: CARD, border: `1px solid ${BORDER}`, color: TEXT }} />
                <Area type="monotone" dataKey="count" stroke={GOLD} fill="url(#goldFade)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div style={card}>
            <div style={cardHeader}>
              <div style={cardTitle}>Top Tags</div>
              <div style={cardSub}>Most common lead labels</div>
            </div>
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

        {/* RIGHT */}
        <div style={{ display: "grid", gap: 14, alignItems: "start" }}>
          <div style={card}>
            <div style={cardHeader}>
              <div style={cardTitle}>Most Scheduled Leads</div>
              <div style={cardSub}>Top 5 by appointment count</div>
            </div>
            {leaderboard.length === 0 ? (
              <div style={{ color: SUBTEXT, fontWeight: 700 }}>No scheduled leads yet.</div>
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
                  <span style={goldChip}>{l.count} appt</span>
                </div>
              ))
            )}
          </div>

          <div style={pill}>
            <FaLightbulb style={{ color: GOLD, fontSize: 18 }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Tip of the Week</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14, lineHeight: 1.45 }}>
                {getAITip(leads)}
              </div>
            </div>
          </div>

          <div style={pill}>
            <FaStar style={{ color: GOLD, fontSize: 18 }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Top VIPs</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14, lineHeight: 1.45 }}>
                {vipLeads.length
                  ? vipLeads.slice(0, 4).map((l) => l.name || l.email).join(", ")
                  : "No VIPs tagged yet."}
              </div>
            </div>
          </div>

          <div style={pill}>
            <FaFire style={{ color: GOLD, fontSize: 18 }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Leads Going Cold</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14, lineHeight: 1.45 }}>
                {coldLeads.length
                  ? coldLeads.slice(0, 4).map((l) => l.name || l.email).join(", ")
                  : "All leads currently look healthy."}
              </div>
            </div>
          </div>

          <div style={pill}>
            <FaCheckCircle style={{ color: GOLD, fontSize: 18 }} />
            <div>
              <div style={{ fontWeight: 800, color: TEXT, fontSize: 15 }}>Next Best Action</div>
              <div style={{ color: GOLD, fontWeight: 700, fontSize: 14, lineHeight: 1.45 }}>
                {getNextAction(leads)}
              </div>
            </div>
          </div>

          <div style={card}>
            <div style={cardHeader}>
              <div style={cardTitle}>Pipeline Summary</div>
              <div style={cardSub}>Current CRM health snapshot</div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <Metric label="Total" value={funnelStats[0].value} />
              <Metric label="Contacted" value={funnelStats[1].value} />
              <Metric label="Appt Set" value={funnelStats[2].value} />
              <Metric label="Closed" value={funnelStats[3].value} />
              <Metric label="Active" value={activeCount} small />
              <Metric label="Follow Up" value={followUpCount} small />
              <Metric label="Cold" value={coldCount} small />
              <Metric label="Avg days since contact" value={avgDaysSinceContact} small />
            </div>
          </div>

          <div style={card}>
            <div style={cardHeader}>
              <div style={cardTitle}>Lead Status Mix</div>
              <div style={cardSub}>Status-based distribution</div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={statusData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={74}
                  label={renderPieLabel}
                  labelLine
                >
                  {statusData.map((entry, idx) => (
                    <Cell key={`status-${idx}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: CARD, border: `1px solid ${BORDER}`, color: TEXT }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ icon, label, value, helper }) {
  return (
    <div
      style={{
        background: CARD,
        border: `1px solid ${BORDER}`,
        borderRadius: 16,
        padding: "16px 18px",
        display: "flex",
        alignItems: "center",
        gap: 14,
        boxShadow: "0 2px 18px rgba(0,0,0,0.30)",
      }}
    >
      <div
        style={{
          width: 46,
          height: 46,
          borderRadius: 14,
          display: "grid",
          placeItems: "center",
          background: "rgba(247,203,83,0.14)",
          color: GOLD,
          fontSize: 18,
          flex: "0 0 46px",
        }}
      >
        {icon}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ color: SUBTEXT, fontSize: 12, fontWeight: 700 }}>{label}</div>
        <div style={{ color: TEXT, fontWeight: 900, fontSize: 26, lineHeight: 1.1 }}>{value}</div>
        <div style={{ color: SUBTEXT, fontSize: 12, marginTop: 4 }}>{helper}</div>
      </div>
    </div>
  );
}

function Metric({ label, value, small }) {
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
      <div style={{ color: TEXT, fontWeight: 900, fontSize: small ? 18 : 24 }}>{value}</div>
    </div>
  );
}