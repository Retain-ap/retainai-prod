// src/components/CrmDashboard.jsx
import React, { useState, useEffect, useCallback } from "react";
import Sidebar from "./Sidebar";
import LeadsDashboard from "./LeadsDashboard";
import LeadModal from "./LeadModal";
import Calendar from "./Calendar";
import Appointments from "./Appointments";
import Messages from "./Messages";
import NotificationsCenter from "./NotificationsCenter";
import Notifications from "./Notifications";
import AiPromptsDashboard from "./AiPromptsDashboard";
import Settings from "./Settings";
import logo from "../assets/logo.png";
import Analytics from "./Analytics";
import Invoices from "./Invoices";
import { useNavigate, useLocation } from "react-router-dom";
import { useSettings } from "./SettingsContext";
import Automations from "./Automations";
import InviteTeamModal from "./InviteTeamModal";

const DEFAULT_TAGS = [
  "VIP","New","Repeat","Upsell","Needs Attention","Appointment Set",
  "Waiting on Reply","Invoice Sent","Birthday","Long Term","Happy","Upset"
];

function getAppointmentsFromLeads(leads) {
  let out = [];
  (leads || []).forEach(lead => {
    (lead.appointments || []).forEach(app => {
      out.push({ ...app, type: "appointment", lead, checked: !!app.done });
    });
  });
  return out;
}

function extractTags(leads, userTags) {
  const tagSet = new Set([...DEFAULT_TAGS, ...(userTags || [])]);
  (leads || []).forEach(lead => (lead.tags || []).forEach(tag => tagSet.add(tag)));
  return Array.from(tagSet);
}

function CrmDashboard() {
  const navigate = useNavigate();
  const location = useLocation();
  const { settings, setUser } = useSettings();

  useEffect(() => {
    const storedUser = JSON.parse(localStorage.getItem("user"));
    if (!storedUser) navigate("/login", { replace: true });
    // eslint-disable-next-line
  }, []);

  // When routed to /app/import, auto-open Settings → Imports
  const [settingsTab, setSettingsTab] = useState(null);
  const [section, setSection] = useState("dashboard");

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (location.pathname === "/app/import" || params.get("open") === "imports") {
      setSettingsTab("imports");
      setSection("settings");
    }
  }, [location.pathname, location.search]);

  const [user, setUserState] = useState(() => {
    try {
      const u = JSON.parse(localStorage.getItem("user"));
      if (u && typeof u === "object") {
        return {
          ...u,
          lineOfBusiness: u.lineOfBusiness || u.businessType || u.business || "",
          name: u.name || "",
          logo: u.logo || "",
          email: u.email || "",
        };
      }
      return null;
    } catch {
      return null;
    }
  });

  // keep local user in sync with any external changes
  useEffect(() => {
    const interval = setInterval(() => {
      const stored = JSON.parse(localStorage.getItem("user"));
      if (stored && JSON.stringify(stored) !== JSON.stringify(user)) {
        setUserState(stored);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [user]);

  useEffect(() => {
    if (settings?.user && settings.user.email && (!user || settings.user.email !== user.email)) {
      setUserState(settings.user);
    }
    // eslint-disable-next-line
  }, [settings.user]);

  const [leads, setLeads] = useState([]);
  const [userTags, setUserTags] = useState(() => {
    try { return JSON.parse(localStorage.getItem("userTags") || "[]"); } catch { return []; }
  });
  const [tags, setTags] = useState([]);
  const [showLeadModal, setShowLeadModal] = useState(false);
  const [editLead, setEditLead] = useState(null);
  const [calendarView, setCalendarView] = useState("calendar");
  const [draftNotification, setDraftNotification] = useState(null);
  const [highlightLeadIds, setHighlightLeadIds] = useState([]);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [drawerLead, setDrawerLead] = useState(null);

  // Google Calendar bits
  const [googleEvents, setGoogleEvents] = useState([]);
  const [gcalStatus, setGcalStatus] = useState(""); // "ok" | "disconnected" | "unauthorized" | "unavailable" | "error: <code>"
  const [gcalConnected, setGcalConnected] = useState(false);

  const [selectedDate, setSelectedDate] = useState(null);
  const [showQuickAdd, setShowQuickAdd] = useState(false);
  const [quickAddDate, setQuickAddDate] = useState(null);
  const [showInviteModal, setShowInviteModal] = useState(false);

  // Load leads
  useEffect(() => {
    if (user && user.email) {
      setLoadingLeads(true);
      fetch(`/api/leads/${encodeURIComponent(user.email)}`)
        .then(res => res.json())
        .then(data => {
          const ls = Array.isArray(data.leads) ? data.leads : [];
          setLeads(ls);
          setTags(extractTags(ls, userTags));
          localStorage.setItem("leads", JSON.stringify(ls));
        })
        .catch(() => setLeads([]))
        .finally(() => setLoadingLeads(false));
    } else {
      setLeads([]);
      setTags([...DEFAULT_TAGS, ...userTags]);
    }
  }, [user, userTags]);

  const saveLeadsToBackend = (newLeads) => {
    if (user && user.email) {
      fetch(`/api/leads/${encodeURIComponent(user.email)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ leads: newLeads }),
      });
      localStorage.setItem("leads", JSON.stringify(newLeads));
      setTags(extractTags(newLeads, userTags));
    }
  };

  const handleUpdateLead = useCallback((updated) => {
    if (!updated) return;

    setLeads(prev => {
      const match = (a, b) =>
        String(a?.id ?? a?.email) === String(b?.id ?? b?.email);

    const exists = prev.some(l => match(l, updated));
      const next = exists
        ? prev.map(l => (match(l, updated) ? { ...l, ...updated } : l))
        : [updated, ...prev];

      saveLeadsToBackend(next);
      return next;
    });

    setDrawerLead(prev => {
      if (!prev) return prev;
      const same =
        String(prev?.id ?? prev?.email) === String(updated?.id ?? updated?.email);
      return same ? { ...prev, ...updated } : prev;
    });
  }, []); // saveLeadsToBackend ok here

  useEffect(() => {
    if (highlightLeadIds.length > 0) {
      const timer = setTimeout(() => setHighlightLeadIds([]), 3200);
      return () => clearTimeout(timer);
    }
  }, [highlightLeadIds]);

  const handleSaveLead = (lead) => {
    let newLeads;
    if (lead.id) {
      newLeads = leads.map((l) => (l.id === lead.id ? lead : l));
    } else {
      const now = new Date().toISOString();
      lead.id = Date.now();
      lead.createdAt = now;
      lead.last_contacted = now;
      newLeads = [lead, ...leads];
    }
    setLeads(newLeads);
    saveLeadsToBackend(newLeads);
    setShowLeadModal(false);
    setEditLead(null);
    if (lead.tags && Array.isArray(lead.tags)) {
      lead.tags.forEach((tag) => {
        if (tag && !DEFAULT_TAGS.includes(tag) && !userTags.includes(tag)) {
          const updated = [...userTags, tag];
          setUserTags(updated);
          localStorage.setItem("userTags", JSON.stringify(updated));
        }
      });
    }
  };

  const handleDeleteLead = (id) => {
    const newLeads = leads.filter((l) => l.id !== id);
    setLeads(newLeads);
    saveLeadsToBackend(newLeads);
  };

  const handleLeadContacted = async (lead) => {
    if (!user || !user.email || !lead.id) return;
    await fetch(`/api/leads/${encodeURIComponent(user.email)}/${lead.id}/contacted`, {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });
    fetch(`/api/leads/${encodeURIComponent(user.email)}`)
      .then(res => res.json())
      .then(data => setLeads(Array.isArray(data.leads) ? data.leads : []));
  };

  const handleLogout = () => {
    setUser(null);
    setUserState(null);
    localStorage.removeItem("user");
    setSection("dashboard");
    navigate("/login", { replace: true });
  };

  function handleSendNotification(lead, aiResponse) {
    setDraftNotification({
      subject: `Follow-up with ${lead.name || "Lead"}`,
      message: aiResponse,
      leadId: lead.id,
      leadEmail: lead.email,
      userEmail: user.email
    });
    setSection("notification-send");
  }
  function handleAfterSendNotification(leadId) {
    if (leadId) setHighlightLeadIds([leadId]);
    setSection("messages");
  }

  async function handleSendAIPromptEmail(lead, aiResponse, aiSubject = "Message from RetainAI", promptType = "") {
    if (!lead || !lead.email || !aiResponse) {
      alert("Missing recipient or message");
      return;
    }
    const body = {
      leadEmail: lead.email,
      userEmail: user.email,
      leadName: lead.name || "",
      message: aiResponse,
      subject: aiSubject,
      promptType: promptType || "",
    };
    try {
      const res = await fetch("/api/send-ai-message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if (res.ok) {
        setHighlightLeadIds([lead.id]);
        alert("AI prompt email sent!");
      } else {
        const err = await res.json();
        alert("Failed to send: " + (err.error || "Unknown error"));
      }
    } catch (e) {
      alert("Error sending AI prompt: " + e.message);
    }
  }

  const handleRefreshUser = useCallback(async () => {
    if (!user || !user.email) return;
    const res = await fetch(`/api/user/${encodeURIComponent(user.email)}`);
    if (res.ok) {
      const data = await res.json();
      setUserState(prev =>
        prev
          ? {
              ...prev,
              ...data,
              lineOfBusiness:
                data.lineOfBusiness ||
                data.businessType ||
                data.business ||
                prev.lineOfBusiness ||
                prev.businessType ||
                prev.business ||
                "",
            }
          : data
      );
      setUser(data);
      localStorage.setItem("user", JSON.stringify(data));
    }
  }, [user, setUser]);

  const crmAppointments = getAppointmentsFromLeads(leads);
  const SIDEBAR_WIDTH = sidebarCollapsed ? 60 : 245;

  // --- Check if Google Calendar is connected BEFORE fetching events
  const checkGoogleConnection = useCallback(async () => {
    if (!user || !user.email) return false;
    try {
      const res = await fetch(`/api/google/status/${encodeURIComponent(user.email)}`);
      if (!res.ok) {
        setGcalConnected(false);
        setGcalStatus("unavailable");
        return false;
      }
      const data = await res.json();
      const connected = !!data.connected;
      setGcalConnected(connected);
      setGcalStatus(connected ? "ok" : "disconnected");
      return connected;
    } catch (e) {
      setGcalConnected(false);
      setGcalStatus("unavailable");
      return false;
    }
  }, [user]);

  const openImports = useCallback(() => {
    setSettingsTab("imports");
    setSection("settings");
  }, []);

  const getGoogleEvents = useCallback(async () => {
    if (!user || !user.email) return;
    try {
      const res = await fetch(`/api/google/events/${encodeURIComponent(user.email)}`);
      if (!res.ok) {
        let msg = "";
        try {
          const err = await res.json();
          msg = err?.error || err?.message || "";
        } catch {
          try { msg = await res.text(); } catch { msg = ""; }
        }
        // If unauthorized, mark as such and don't keep retrying blindly
        if (res.status === 401) {
          setGcalStatus("unauthorized");
          setGoogleEvents([]);
          return;
        }
        setGcalStatus(`error: ${res.status}`);
        setGoogleEvents([]);
        console.warn("Google events fetch failed:", res.status, msg);
        return;
      }
      const data = await res.json();
      setGoogleEvents(Array.isArray(data.items) ? data.items : []);
      setGcalStatus("ok");
    } catch (e) {
      console.warn("Google events fetch error:", e);
      setGcalStatus("unavailable");
      setGoogleEvents([]);
    }
  }, [user]);

  // Only try to fetch events when in calendar/appointments AND connected.
  useEffect(() => {
    (async () => {
      if (!user?.email) return;
      if (section === "calendar" || section === "appointments") {
        const connected = await checkGoogleConnection();
        if (connected) {
          await getGoogleEvents();
        } else {
          setGoogleEvents([]);
        }
      } else {
        setGoogleEvents([]);
      }
    })();
  }, [section, user, checkGoogleConnection, getGoogleEvents]);

  function handleQuickAdd(day) {
    setQuickAddDate(day);
    setShowQuickAdd(true);
  }
  function handleQuickAddSave({ leadId, title, time }) {
    if (!leadId || !title || !quickAddDate) return;
    setLeads(prev =>
      prev.map(l =>
        String(l.id) === String(leadId)
          ? {
              ...l,
              appointments: [
                ...(l.appointments || []),
                { title, date: quickAddDate.toISOString().slice(0, 10), time, done: false }
              ]
            }
          : l
      )
    );
    setShowQuickAdd(false);
    setQuickAddDate(null);
  }

  useEffect(() => {
    window.RetainAI = window.RetainAI || {};
    window.RetainAI.openImports = openImports;
    window.RetainAI.openTeam = () => { setSettingsTab("team"); setSection("settings"); };
  }, [openImports]);

  if (!user) return null;

  return (
    <div
      className="crm-root"
      style={{
        minHeight: "100vh",
        width: "100vw",
        overflowX: "hidden",
        background: "#181a1b",
      }}
    >
      <Sidebar
        logo={logo}
        onLogout={handleLogout}
        user={user}
        setSection={setSection}
        section={section}
        collapsed={sidebarCollapsed}
        setCollapsed={setSidebarCollapsed}
        onInviteTeam={() => setShowInviteModal(true)}
        onImportLeads={openImports}
      />

      <div
        className="crm-main-content"
        style={{
          minHeight: "100vh",
          marginLeft: SIDEBAR_WIDTH,
          transition: "margin-left 0.25s cubic-bezier(.77,.2,.2,1)",
          display: "flex",
          flexDirection: "column",
          width: `calc(100vw - ${SIDEBAR_WIDTH}px)`,
          padding: "24px",
          boxSizing: "border-box",
        }}
      >
        {section === "dashboard" && (
          <>
            <LeadsDashboard
              leads={leads}
              loading={loadingLeads}
              user={user}
              onAddLead={() => { setEditLead(null); setShowLeadModal(true); }}
              onEditLead={lead => { setEditLead(lead); setShowLeadModal(true); }}
              onDeleteLead={handleDeleteLead}
              drawerLead={drawerLead}
              setDrawerLead={setDrawerLead}
              onContactedLead={handleLeadContacted}
              onImportLeads={openImports}
              onUpdateLead={handleUpdateLead}
            />
            {showLeadModal && (
              <LeadModal
                lead={editLead}
                tags={tags}
                onClose={() => { setShowLeadModal(false); setEditLead(null); }}
                onSave={handleSaveLead}
              />
            )}
          </>
        )}

        {section === "calendar" && (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <button
                style={{
                  background: calendarView === "calendar" ? "#191919" : "#141414",
                  color: "#f7cb53",
                  border: "1px solid #222",
                  borderRight: "none",
                  borderRadius: "10px 0 0 10px",
                  padding: "10px 18px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
                onClick={() => setCalendarView("calendar")}
              >
                Calendar
              </button>
              <button
                style={{
                  background: calendarView === "appointments" ? "#191919" : "#141414",
                  color: "#f7cb53",
                  border: "1px solid #222",
                  borderRadius: "0 10px 10px 0",
                  padding: "10px 18px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
                onClick={() => setCalendarView("appointments")}
              >
                Appointments
              </button>

              <button
                style={{
                  marginLeft: 10,
                  background: "#2d7ef7",
                  color: "#fff",
                  border: "none",
                  borderRadius: 8,
                  padding: "10px 16px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
                onClick={async () => {
                  const connected = await checkGoogleConnection();
                  if (connected) {
                    await getGoogleEvents();
                  } else {
                    setGcalStatus("disconnected");
                    setGoogleEvents([]);
                    openImports();
                  }
                }}
              >
                Refresh Google events
              </button>
            </div>

            {/* Inline status/CTA when not connected or unauthorized */}
            {gcalStatus && gcalStatus !== "ok" && (
              <div
                style={{
                  marginBottom: 12,
                  padding: "10px 12px",
                  borderRadius: 8,
                  border: "1px solid #444",
                  background: "#232323",
                  color: "#ddd",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 10
                }}
              >
                <span>
                  Google Calendar:{" "}
                  {gcalStatus === "disconnected" && "not connected"}
                  {gcalStatus === "unauthorized" && "token expired/unauthorized"}
                  {gcalStatus.startsWith("error:") && gcalStatus}
                  {gcalStatus === "unavailable" && "service unavailable"}
                </span>
                <button
                  onClick={openImports}
                  style={{ background: "#f7cb53", color: "#232323", border: "none", borderRadius: 8, padding: "8px 12px", fontWeight: 800, cursor: "pointer" }}
                >
                  Connect Calendar
                </button>
              </div>
            )}

            {calendarView === "calendar" ? (
              <Calendar
                user={user}
                leads={leads}
                events={crmAppointments}
                googleEvents={googleEvents}
                selectedDate={selectedDate}
                setSelectedDate={setSelectedDate}
                onDayClick={handleQuickAdd}
              />
            ) : (
              <Appointments
                user={user}
                leads={leads}
                setLeads={setLeads}
                events={crmAppointments}
                googleEvents={googleEvents}
              />
            )}

            {showQuickAdd && (
              <div
                style={{
                  position: "fixed", left: 0, top: 0, width: "100vw", height: "100vh",
                  background: "#000a", zIndex: 99,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}
              >
                <div
                  style={{
                    background: "#232323",
                    borderRadius: 16,
                    padding: "24px 26px",
                    minWidth: 340,
                    maxWidth: 440,
                    width: "92vw",
                    border: "1px solid #444",
                    boxShadow: "0 2px 22px #0008",
                  }}
                >
                  <h3 style={{ color: "#f7cb53", fontWeight: 800, marginBottom: 12, fontSize: "1.05rem" }}>
                    Add Appointment ({quickAddDate?.toLocaleDateString()})
                  </h3>
                  <QuickAddForm
                    leads={leads}
                    onSave={handleQuickAddSave}
                    onCancel={() => { setShowQuickAdd(false); setQuickAddDate(null); }}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {section === "settings" && (
          <Settings
            googleEvents={googleEvents}
            setGoogleEvents={setGoogleEvents}
            gcalStatus={gcalStatus}
            setGcalStatus={setGcalStatus}
            user={user}
            sidebarCollapsed={sidebarCollapsed}
            refreshUser={handleRefreshUser}
            initialTab={settingsTab}
          />
        )}

        {section === "messages" && (
          <Messages leads={leads} highlightLeadIds={highlightLeadIds} user={user} />
        )}

        {section === "notifications" && <NotificationsCenter user={user} />}

        {section === "notification-send" && (
          <Notifications
            user={user}
            draft={draftNotification}
            clearDraft={() => setDraftNotification(null)}
            leads={leads}
            setSection={setSection}
            afterSend={handleAfterSendNotification}
          />
        )}

        {section === "ai-prompts" && (
          <AiPromptsDashboard
            leads={leads}
            user={user}
            onSendAIPromptEmail={handleSendAIPromptEmail}
          />
        )}

        {section === "analytics" && (
          <Analytics leads={leads} events={crmAppointments} user={user} />
        )}

        {section === "invoices" && (
          <Invoices user={user} leads={leads} refreshUser={handleRefreshUser} />
        )}

        {section === "automations" && <Automations user={user} />}
      </div>

      {showInviteModal && (
        <InviteTeamModal user={user} onClose={() => setShowInviteModal(false)} />
      )}
    </div>
  );
}

// Quick Add Appointment form (unchanged, robust id compare)
function QuickAddForm({ leads, onSave, onCancel }) {
  const [leadId, setLeadId] = useState("");
  const [title, setTitle] = useState("");
  const [time, setTime] = useState("");

  return (
    <form
      onSubmit={e => {
        e.preventDefault();
        onSave({ leadId, title, time });
      }}
    >
      <div style={{ marginBottom: 14 }}>
        <label style={{ color: "#fff", fontWeight: 700, display: "block", marginBottom: 6 }}>Lead</label>
        <select
          value={leadId}
          onChange={e => setLeadId(e.target.value)}
          style={{ padding: "10px 12px", borderRadius: 8, background: "#181a1b", color: "#fff", border: "1px solid #444", width: "100%" }}
          required
        >
          <option value="">Select Lead</option>
          {leads.map(lead => (
            <option value={lead.id} key={lead.id}>{lead.name}</option>
          ))}
        </select>
      </div>
      <div style={{ marginBottom: 14 }}>
        <label style={{ color: "#fff", fontWeight: 700, display: "block", marginBottom: 6 }}>Title</label>
        <input
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="Appointment title"
          style={{ padding: "10px 12px", borderRadius: 8, background: "#181a1b", color: "#fff", border: "1px solid #444", width: "100%" }}
          required
        />
      </div>
      <div style={{ marginBottom: 14 }}>
        <label style={{ color: "#fff", fontWeight: 700, display: "block", marginBottom: 6 }}>Time</label>
        <input
          type="time"
          value={time}
          onChange={e => setTime(e.target.value)}
          style={{ padding: "10px 12px", borderRadius: 8, background: "#181a1b", color: "#fff", border: "1px solid #444", width: "100%" }}
        />
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <button
          type="submit"
          style={{ background: "#f7cb53", color: "#232323", fontWeight: 800, border: "none", borderRadius: 8, padding: "11px 0", cursor: "pointer", width: "50%" }}
        >
          Add
        </button>
        <button
          type="button"
          onClick={onCancel}
          style={{ background: "#232323", color: "#fff", fontWeight: 800, border: "1px solid #444", borderRadius: 8, padding: "11px 0", cursor: "pointer", width: "50%" }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default CrmDashboard;
