// File: src/components/CrmDashboard.jsx
import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
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
import Insights from "./Insights";
import Invoices from "./Invoices";
import { useNavigate, useLocation } from "react-router-dom";
import { useSettings } from "./SettingsContext";
import Automations from "./Automations";
import InviteTeamModal from "./InviteTeamModal";
import { apiUrl } from "../apiBase";
import { FaBars } from "react-icons/fa";
import RetentionCommandCenter from "./RetentionCommandCenter";
import OwnerConsole from "./OwnerConsole";
import CommandPalette from "./CommandPalette";
import TrialCommandBar from "./TrialCommandBar";
import OnboardingGuide from "./OnboardingGuide";
import "./AppSectionShell.css";
import { getWorkspaceCapabilities } from "../workspaceIdentity";
import {
  appointmentDateTimeParts,
  buildAppointmentTimestamp,
  dateKeyFromParts,
  getBrowserTimeZone,
  localDateKey,
  parseAppointmentDateTime,
  timeKeyFromParts,
} from "./appointmentDateTime";

const SECTION_LABELS = {
  overview: "Overview",
  dashboard: "Contacts",
  analytics: "Insights",
  calendar: "Calendar",
  messages: "Messages",
  notifications: "Notifications",
  automations: "Automations",
  "ai-prompts": "AI Studio",
  invoices: "Invoices",
  settings: "Settings",
  owner: "Owner Console",
};

const SECTION_META = {
  dashboard: ["Customer workspace", "Contacts", "Search, organize, and act on every customer relationship."],
  calendar: ["Schedule", "Calendar", "Keep appointments, availability, and customer follow-ups aligned."],
  messages: ["Conversations", "Messages", "Manage WhatsApp conversations and thoughtful AI-assisted replies."],
  notifications: ["Activity centre", "Notifications", "Review customer activity, reminders, and workflow updates."],
  "notification-send": ["Customer outreach", "Send notification", "Send a clear, targeted update to the right contacts."],
  "ai-prompts": ["Message intelligence", "AI Studio", "Create thoughtful customer outreach using relationship context and your brand voice."],
  invoices: ["Revenue", "Invoices", "Create invoices, track payment status, and follow up without losing context."],
  automations: ["Playbooks", "Automations", "Build reliable customer journeys with visible triggers and outcomes."],
};

const DEFAULT_TAGS = [
  "VIP",
  "New",
  "Repeat",
  "Upsell",
  "Needs Attention",
  "Appointment Set",
  "Waiting on Reply",
  "Invoice Sent",
  "Birthday",
  "Long Term",
  "Happy",
  "Upset",
  "Closed",
  "Won",
];

function normEmail(v) {
  return String(v || "").trim().toLowerCase();
}

function getEffectiveEmail(u) {
  const org = normEmail(u?.org_id);
  const email = normEmail(u?.email);
  return org || email;
}

function leadsKey(email) {
  return `retainai_leads_${normEmail(email)}`;
}
function tagsKey(email) {
  return `retainai_userTags_${normEmail(email)}`;
}

function safeParseJSON(s, fallback) {
  try {
    const v = JSON.parse(s);
    return v ?? fallback;
  } catch {
    return fallback;
  }
}

function getAppointmentsFromLeads(leads) {
  const out = [];
  (leads || []).forEach((lead) => {
    (lead.appointments || []).forEach((app) => {
      out.push({ ...app, type: "appointment", lead, checked: !!app.done });
    });
  });
  return out;
}

function appointmentSignature(appointment) {
  const lead = appointment?.lead || {};
  const appointmentTime = String(
    appointment?.date
      ? `${appointment.date}T${appointment?.time || "00:00"}:00`
      : appointment?.appointment_time || ""
  ).slice(0, 16);
  return [
    String(appointment?.lead_id || lead?.id || lead?.email || appointment?.lead_email || "")
      .trim()
      .toLowerCase(),
    appointmentTime,
    String(appointment?.title || "Appointment").trim().toLowerCase(),
  ].join("|");
}

function normalizeBackendAppointment(appointment, leads) {
  const parsed = parseAppointmentDateTime(appointment?.appointment_time || "");
  const parts = appointmentDateTimeParts(
    appointment?.appointment_time,
    appointment?.timezone || ""
  );
  if (!parsed || !parts) return null;
  const lead =
    (leads || []).find(
      (candidate) => String(candidate?.id || "") === String(appointment?.lead_id || "")
    ) || {
      id: appointment?.lead_id || "",
      name:
        appointment?.lead_full_name ||
        [appointment?.lead_first_name, appointment?.lead_last_name].filter(Boolean).join(" ") ||
        appointment?.lead_email ||
        "Client",
      email: appointment?.lead_email || "",
    };
  return {
    ...appointment,
    type: "appointment",
    date: dateKeyFromParts(parts),
    time: timeKeyFromParts(parts),
    timezone: appointment?.timezone || "",
    sortKey: parsed.getTime(),
    checked: !!(appointment?.done ?? appointment?.completed ?? appointment?.is_done),
    done: !!(appointment?.done ?? appointment?.completed ?? appointment?.is_done),
    lead,
    _backend: appointment,
  };
}

function extractTags(leads, userTags) {
  const tagSet = new Set([...DEFAULT_TAGS, ...(userTags || [])]);
  (leads || []).forEach((lead) => (lead.tags || []).forEach((tag) => tagSet.add(tag)));
  return Array.from(tagSet);
}

function makeId() {
  // Backend expects string IDs. Use UUID when possible.
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  } catch {}
  return `lead_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function CrmDashboard({ authenticatedUser }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { settings, setUser } = useSettings();
  const sessionCapabilities = useMemo(
    () => getWorkspaceCapabilities(authenticatedUser),
    [authenticatedUser]
  );
  const canOpenSection = useCallback(
    (nextSection) => {
      if (nextSection === "owner") return sessionCapabilities.platformOwner;
      if (nextSection === "invoices") return sessionCapabilities.canManageBilling;
      return true;
    },
    [sessionCapabilities.canManageBilling, sessionCapabilities.platformOwner]
  );

  // When routed to /app/import, auto-open Settings → Imports
  const [settingsTab, setSettingsTab] = useState(null);
  const [section, setSection] = useState(
    authenticatedUser?.platformOwner ? "owner" : "overview"
  );
  const [calendarView, setCalendarView] = useState("calendar");

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const requestedSection = params.get("section");
    if (
      requestedSection &&
      Object.prototype.hasOwnProperty.call(SECTION_LABELS, requestedSection) &&
      canOpenSection(requestedSection)
    ) {
      setSection(requestedSection);
      if (requestedSection === "calendar" && params.get("view") === "appointments") {
        setCalendarView("appointments");
      }
      return;
    }
    const requestedSettingsTab = params.get("tab");
    if (requestedSettingsTab) {
      setSettingsTab(requestedSettingsTab);
      setSection("settings");
      return;
    }
    if (location.pathname === "/app/import" || params.get("open") === "imports") {
      setSettingsTab("imports");
      setSection("settings");
    }
  }, [canOpenSection, location.pathname, location.search]);

  useEffect(() => {
    const handleNavigate = (event) => {
      const nextSection = String(event?.detail || "");
      if (
        Object.prototype.hasOwnProperty.call(SECTION_LABELS, nextSection) &&
        canOpenSection(nextSection)
      ) {
        setSection(nextSection);
      }
    };
    window.addEventListener("retainai:navigate", handleNavigate);
    return () => window.removeEventListener("retainai:navigate", handleNavigate);
  }, [canOpenSection]);

  useEffect(() => {
    if (!canOpenSection(section)) setSection("overview");
  }, [canOpenSection, section]);

  // user state (single source of truth)
  const [user, setUserState] = useState(() => {
    if (authenticatedUser?.email) return authenticatedUser;
    const stored = safeParseJSON(localStorage.getItem("user"), null);
    if (stored && typeof stored === "object") {
      return {
        ...stored,
        lineOfBusiness: stored.lineOfBusiness || stored.businessType || stored.business || "",
        name: stored.name || "",
        logo: stored.logo || "",
        email: stored.email || "",
      };
    }
    return null;
  });

  // The signed server session is the only authority for account identity.
  // Local storage and SettingsContext may contain profile data, but can never
  // switch the active account behind the session.
  useEffect(() => {
    if (!authenticatedUser?.email) return;
    setUserState({
      ...authenticatedUser,
      lineOfBusiness:
        authenticatedUser.lineOfBusiness ||
        authenticatedUser.businessType ||
        authenticatedUser.business ||
        "",
    });
    setUser?.(authenticatedUser);
    localStorage.setItem("user", JSON.stringify(authenticatedUser));
  }, [authenticatedUser, setUser]);

  // Sync from SettingsContext if it changes
  useEffect(() => {
    if (settings?.user && settings.user.email && !authenticatedUser?.email) {
      const next = settings.user;
      if (!user || normEmail(next.email) !== normEmail(user.email)) {
        setUserState({
          ...next,
          lineOfBusiness: next.lineOfBusiness || next.businessType || next.business || "",
          name: next.name || "",
          logo: next.logo || "",
          email: next.email || "",
        });
      }
    }
    // eslint-disable-next-line
  }, [settings?.user]);

  // Sync across tabs/windows (storage event)
  useEffect(() => {
    function onStorage(e) {
      if (e.key === "user" && !authenticatedUser?.email) {
        const next = safeParseJSON(localStorage.getItem("user"), null);
        setUserState(next);
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [authenticatedUser?.email]);

  const effectiveEmail = useMemo(() => getEffectiveEmail(user), [user]);

  const [leads, setLeads] = useState([]);
  const leadsRef = useRef([]);
  const [backendAppointments, setBackendAppointments] = useState([]);
  const [appointmentsTimezone, setAppointmentsTimezone] = useState("");
  const [userTags, setUserTags] = useState([]);
  const [tags, setTags] = useState([]);

  const [showLeadModal, setShowLeadModal] = useState(false);
  const [editLead, setEditLead] = useState(null);
  const [draftNotification, setDraftNotification] = useState(null);
  const [highlightLeadIds, setHighlightLeadIds] = useState([]);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [leadPersistenceError, setLeadPersistenceError] = useState("");
  const [deletingLeadId, setDeletingLeadId] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth <= 900 : false
  );
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const sync = () => {
      setIsMobile(media.matches);
      if (!media.matches) setMobileNavOpen(false);
    };
    sync();
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, []);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [section]);
  const [drawerLead, setDrawerLead] = useState(null);

  // Google Calendar bits
  const [googleEvents, setGoogleEvents] = useState([]);
  const [gcalStatus, setGcalStatus] = useState("");
  const [, setGcalConnected] = useState(false);

  const [selectedDate, setSelectedDate] = useState(null);
  const [showQuickAdd, setShowQuickAdd] = useState(false);
  const [quickAddDate, setQuickAddDate] = useState(null);
  const [showInviteModal, setShowInviteModal] = useState(false);

  // ---- Lead persistence strategy (fixes your issue) ----
  // 1) Load local cache immediately (fast UI)
  // 2) Fetch authoritative from backend: GET /api/leads with X-User-Email
  // 3) Save to backend: POST /api/leads with X-User-Email + {leads:[...]} (debounced)
  const saveTimerRef = useRef(null);
  const leadSaveQueueRef = useRef(Promise.resolve());
  const lastSavedJsonRef = useRef("");

  useEffect(() => {
    leadsRef.current = leads;
  }, [leads]);

  // Load per-user local cache immediately when user changes
  useEffect(() => {
    if (!effectiveEmail) {
      setLeads([]);
      setUserTags([]);
      setTags([...DEFAULT_TAGS]);
      return;
    }

    const cachedLeads = safeParseJSON(localStorage.getItem(leadsKey(effectiveEmail)), []);
    const cachedTags = safeParseJSON(localStorage.getItem(tagsKey(effectiveEmail)), []);

    const lsLeads = Array.isArray(cachedLeads) ? cachedLeads : [];
    const lsTags = Array.isArray(cachedTags) ? cachedTags : [];

    setLeads(lsLeads);
    setUserTags(lsTags);
    setTags(extractTags(lsLeads, lsTags));
  }, [effectiveEmail]);

  // Fetch leads from backend (authoritative)
  useEffect(() => {
    let cancelled = false;

    (async () => {
      if (!effectiveEmail) return;

      setLoadingLeads(true);
      try {
        // ✅ NEW canonical endpoint style:
        // GET /api/leads with header X-User-Email
        const res = await fetch(apiUrl("leads"), {
          method: "GET",
          credentials: "include",
          headers: {
            Accept: "application/json",
            "X-User-Email": effectiveEmail,
          },
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json().catch(() => ({}));

        if (cancelled) return;

        const serverLeads = Array.isArray(data?.leads) ? data.leads : [];
        setLeads(serverLeads);
        setTags(extractTags(serverLeads, userTags));

        try {
          localStorage.setItem(leadsKey(effectiveEmail), JSON.stringify(serverLeads));
        } catch {}

        // reset save-deduper
        try {
          lastSavedJsonRef.current = `${effectiveEmail}\n${JSON.stringify(serverLeads)}`;
        } catch {
          lastSavedJsonRef.current = "";
        }
      } catch {
        // backend failed -> keep local cache
      } finally {
        if (!cancelled) setLoadingLeads(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line
  }, [effectiveEmail]);

  // Debounced backend save
  const saveLeadsToBackend = useCallback(
    (newLeads) => {
      const email = effectiveEmail;
      if (!email) return;

      // local cache first (resilient)
      try {
        localStorage.setItem(leadsKey(email), JSON.stringify(newLeads));
      } catch {}

      setTags(extractTags(newLeads, userTags));

      // dedupe identical saves
      let json = "";
      try {
        json = JSON.stringify(newLeads);
      } catch {}
      const saveSignature = json ? `${email}\n${json}` : "";
      if (saveSignature && saveSignature === lastSavedJsonRef.current) return;

      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);

      saveTimerRef.current = setTimeout(() => {
        const operation = leadSaveQueueRef.current.then(async () => {
          try {
            const res = await fetch(apiUrl("leads"), {
              method: "POST",
              credentials: "include",
              headers: {
                "Content-Type": "application/json",
                Accept: "application/json",
                "X-User-Email": email,
              },
              body: JSON.stringify({ leads: newLeads }),
            });

            if (res.ok) {
              lastSavedJsonRef.current = saveSignature || lastSavedJsonRef.current;
            }
          } catch {
            // keep local cache if backend fails
          }
        });
        leadSaveQueueRef.current = operation.catch(() => {});
      }, 450);
    },
    [effectiveEmail, userTags]
  );

  const persistLeadsImmediately = useCallback(
    async (newLeads) => {
      const email = effectiveEmail;
      if (!email) throw new Error("Missing workspace email");

      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }

      let json = "";
      try {
        json = JSON.stringify(newLeads);
        localStorage.setItem(leadsKey(email), json);
      } catch {}
      setTags(extractTags(newLeads, userTags));
      const saveSignature = json ? `${email}\n${json}` : "";

      const operation = leadSaveQueueRef.current.then(async () => {
        const res = await fetch(apiUrl("leads"), {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-User-Email": email,
          },
          body: JSON.stringify({ leads: newLeads }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.ok !== true || Number(data?.count) !== newLeads.length) {
          throw new Error(data?.error || `Could not save customer changes (${res.status})`);
        }
        lastSavedJsonRef.current = saveSignature || lastSavedJsonRef.current;
        return data;
      });

      leadSaveQueueRef.current = operation.catch(() => {});
      return operation;
    },
    [effectiveEmail, userTags]
  );

  const handleUpdateLead = useCallback(
    async (updated) => {
      if (!updated) throw new Error("Missing customer update");

      const previous = leadsRef.current;
      const match = (a, b) => String(a?.id ?? a?.email) === String(b?.id ?? b?.email);
      const exists = previous.some((lead) => match(lead, updated));
      const next = exists
        ? previous.map((lead) => (match(lead, updated) ? { ...lead, ...updated } : lead))
        : [updated, ...previous];

      leadsRef.current = next;
      setLeads(next);

      setDrawerLead((prev) => {
        if (!prev) return prev;
        const same = String(prev?.id ?? prev?.email) === String(updated?.id ?? updated?.email);
        return same ? { ...prev, ...updated } : prev;
      });

      try {
        await persistLeadsImmediately(next);
        setLeadPersistenceError("");
        return updated;
      } catch (error) {
        if (leadsRef.current === next) {
          leadsRef.current = previous;
          setLeads(previous);
          try {
            localStorage.setItem(leadsKey(effectiveEmail), JSON.stringify(previous));
          } catch {}
        }
        setLeadPersistenceError(error?.message || "Could not save customer changes.");
        throw error;
      }
    },
    [effectiveEmail, persistLeadsImmediately]
  );

  useEffect(() => {
    if (highlightLeadIds.length > 0) {
      const timer = setTimeout(() => setHighlightLeadIds([]), 3200);
      return () => clearTimeout(timer);
    }
  }, [highlightLeadIds]);

  const persistUserTags = useCallback(
    (nextTags) => {
      const email = effectiveEmail;
      setUserTags(nextTags);
      if (email) {
        try {
          localStorage.setItem(tagsKey(email), JSON.stringify(nextTags));
        } catch {}
      }
      setTags(extractTags(leads, nextTags));
    },
    [effectiveEmail, leads]
  );

  const handleSaveLead = (lead) => {
    let newLeads;

    if (lead.id) {
      newLeads = leads.map((l) => (String(l.id) === String(lead.id) ? lead : l));
    } else {
      const now = new Date().toISOString();
      lead.id = makeId(); // ✅ string id
      lead.createdAt = now;
      lead.last_contacted = lead.last_contacted || now;
      newLeads = [lead, ...leads];
    }

    setLeads(newLeads);
    saveLeadsToBackend(newLeads);

    setShowLeadModal(false);
    setEditLead(null);

    // merge tags into userTags (per-user)
    if (lead.tags && Array.isArray(lead.tags)) {
      const toAdd = lead.tags.filter((t) => t && !DEFAULT_TAGS.includes(t) && !userTags.includes(t));
      if (toAdd.length) {
        persistUserTags([...userTags, ...toAdd]);
      }
    }
  };

  const handleDeleteLead = async (id) => {
    const leadIndex = leads.findIndex((lead) => String(lead?.id) === String(id));
    if (leadIndex < 0 || deletingLeadId !== null) return false;

    const leadToDelete = leads[leadIndex];
    const leadLabel = leadToDelete?.name || leadToDelete?.email || "this contact";
    if (!window.confirm(`Delete ${leadLabel}? This permanently removes the contact from this workspace.`)) {
      return false;
    }

    const email = effectiveEmail;
    if (!email) {
      setLeadPersistenceError("This contact could not be deleted because the workspace is unavailable.");
      return false;
    }

    const newLeads = leads.filter((lead) => String(lead?.id) !== String(id));
    const json = JSON.stringify(newLeads);
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }

    setDeletingLeadId(String(id));
    setLeadPersistenceError("");
    setLeads(newLeads);
    setTags(extractTags(newLeads, userTags));

    try {
      const operation = leadSaveQueueRef.current.then(async () => {
        const response = await fetch(apiUrl("leads"), {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-User-Email": email,
          },
          body: JSON.stringify({ leads: newLeads }),
        });
        const payload = await response.json().catch(() => ({}));
        return { response, payload };
      });
      leadSaveQueueRef.current = operation.then(() => undefined, () => undefined);
      const { response, payload } = await operation;
      if (!response.ok || payload?.ok === false || payload?.count !== newLeads.length) {
        throw new Error(payload?.error || `Contact deletion failed (${response.status})`);
      }

      lastSavedJsonRef.current = `${email}\n${json}`;
      try {
        localStorage.setItem(leadsKey(email), json);
      } catch {}
      return true;
    } catch (error) {
      if (normEmail(effectiveEmail) === normEmail(email)) {
        setLeads((current) => {
          if (current.some((lead) => String(lead?.id) === String(id))) return current;
          const restored = [...current];
          restored.splice(Math.min(leadIndex, restored.length), 0, leadToDelete);
          return restored;
        });
        setTags((current) => extractTags([leadToDelete], current));
        setLeadPersistenceError(
          error?.message || "This contact could not be deleted. No changes were saved."
        );
      }
      return false;
    } finally {
      setDeletingLeadId(null);
    }
  };

  // Lead contacted (backend optional; we ALWAYS update locally + persist)
  const handleLeadContacted = async (lead) => {
    const email = effectiveEmail;
    if (!email || !lead?.id) return;

    const now = new Date().toISOString();

    // instant UI update
    setLeads((prev) => {
      const next = prev.map((l) =>
        String(l.id) === String(lead.id)
          ? {
              ...l,
              last_contacted: now,
              last_activity_at: now,
              updated_at: now,
              status: "active",
            }
          : l
      );

      saveLeadsToBackend(next);
      return next;
    });

    setDrawerLead((prev) => {
      if (!prev || String(prev.id) !== String(lead.id)) return prev;
      return {
        ...prev,
        last_contacted: now,
        last_activity_at: now,
        updated_at: now,
        status: "active",
      };
    });

    // optional backend endpoint if it exists
    try {
      await fetch(apiUrl("leads/contacted"), {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-User-Email": email,
        },
        body: JSON.stringify({ leadId: String(lead.id), at: now }),
      });
    } catch {}
  };

  const handleLogout = async () => {
    try {
      await fetch(apiUrl("logout"), {
        method: "POST",
        credentials: "include",
      });
    } catch {}
    setUser(null);
    setUserState(null);
    localStorage.removeItem("user");
    setSection("overview");
    navigate("/login", { replace: true });
  };

  function handleSendNotification(lead, aiResponse) {
    setDraftNotification({
      subject: `Follow-up with ${lead.name || "Lead"}`,
      message: aiResponse,
      leadId: lead.id,
      leadEmail: lead.email,
      userEmail: effectiveEmail || user?.email || "",
    });
    setSection("notification-send");
  }

  function handleAfterSendNotification(leadId) {
    if (leadId) setHighlightLeadIds([leadId]);
    setSection("messages");
  }

  // Send AI prompt email through the authenticated POST endpoint only.
  async function handleSendAIPromptEmail(
    lead,
    aiResponse,
    aiSubject = "Message from RetainAI",
    promptType = ""
  ) {
    if (!lead || !lead.email || !aiResponse) {
      throw new Error("Missing recipient or message.");
    }

    const body = {
      leadId: lead.id,
      leadEmail: lead.email,
      message: aiResponse,
      subject: aiSubject,
      promptType: promptType || "",
    };

    const response = await fetch(apiUrl("send-ai-message"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.ok === false) {
      throw new Error(data?.error || `Message could not be sent (HTTP ${response.status}).`);
    }
    setHighlightLeadIds([lead.id]);
    return true;
  }

  // Refresh user (best-effort; backend may not support this)
  const handleRefreshUser = useCallback(async () => {
    const email = effectiveEmail;
    if (!email) return;

    try {
      const res = await fetch(apiUrl(`user/${encodeURIComponent(email)}`), {
        credentials: "include",
        headers: { Accept: "application/json" },
      });

      if (res.ok) {
        const data = await res.json();

        const next = {
          ...(user || {}),
          ...data,
          lineOfBusiness:
            data.lineOfBusiness ||
            data.businessType ||
            data.business ||
            user?.lineOfBusiness ||
            user?.businessType ||
            user?.business ||
            "",
        };

        setUserState(next);
        setUser(next);
        localStorage.setItem("user", JSON.stringify(next));
      }
    } catch {}
  }, [effectiveEmail, user, setUser]);

  const refreshAppointments = useCallback(async () => {
    if (!effectiveEmail) {
      setBackendAppointments([]);
      setAppointmentsTimezone("");
      return;
    }
    const response = await fetch(
      apiUrl(`appointments/${encodeURIComponent(effectiveEmail)}`),
      { credentials: "include", headers: { Accept: "application/json" } }
    );
    if (!response.ok) throw new Error(`Appointments request failed (${response.status})`);
    const payload = await response.json().catch(() => ({}));
    setBackendAppointments(Array.isArray(payload?.appointments) ? payload.appointments : []);
    setAppointmentsTimezone(payload?.timezone || "");
  }, [effectiveEmail]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        if (!cancelled) await refreshAppointments();
      } catch {
        // Keep the last known list visible; child pages surface their own retry state.
      }
    };
    load();
    window.addEventListener("appointments:changed", load);
    return () => {
      cancelled = true;
      window.removeEventListener("appointments:changed", load);
    };
  }, [refreshAppointments]);

  const crmAppointments = useMemo(() => {
    const backend = (backendAppointments || [])
      .map((appointment) => normalizeBackendAppointment(appointment, leads))
      .filter(Boolean);
    const backendSignatures = new Set(backend.map(appointmentSignature));
    const unmatchedLegacy = getAppointmentsFromLeads(leads).filter(
      (appointment) => !backendSignatures.has(appointmentSignature(appointment))
    );
    return [...backend, ...unmatchedLegacy];
  }, [backendAppointments, leads]);
  const SIDEBAR_WIDTH = isMobile ? 0 : sidebarCollapsed ? 60 : 245;

  // Google connection
  const checkGoogleConnection = useCallback(async () => {
    const email = effectiveEmail;
    if (!email) return false;

    try {
      const res = await fetch(apiUrl(`google/status/${encodeURIComponent(email)}`), {
        credentials: "include",
        headers: { Accept: "application/json" },
      });

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
    } catch {
      setGcalConnected(false);
      setGcalStatus("unavailable");
      return false;
    }
  }, [effectiveEmail]);

  const openImports = useCallback(() => {
    setSettingsTab("imports");
    setSection("settings");
    navigate("/app/import?source=google");
  }, [navigate]);

  const openSettings = useCallback(() => {
    setSettingsTab("profile");
    setSection("settings");
    navigate("/app?tab=profile");
  }, [navigate]);

  // Fetch Google events
  const getGoogleEvents = useCallback(async () => {
    const email = effectiveEmail;
    if (!email) return;

    try {
      let calendarId = "";
      try {
        calendarId = localStorage.getItem(`retainai_selected_calendar_${email}`) || "";
      } catch {}
      const query = calendarId ? `?calendarId=${encodeURIComponent(calendarId)}` : "";
      const res = await fetch(apiUrl(`google/events/${encodeURIComponent(email)}${query}`), {
        credentials: "include",
        headers: { Accept: "application/json" },
      });

      if (!res.ok) {
        if (res.status === 401) {
          setGcalStatus("unauthorized");
          setGoogleEvents([]);
          return;
        }
        setGcalStatus(`error: ${res.status}`);
        setGoogleEvents([]);
        return;
      }

      const data = await res.json();
      setGoogleEvents(Array.isArray(data.items) ? data.items : []);
      setGcalStatus("ok");
    } catch {
      setGcalStatus("unavailable");
      setGoogleEvents([]);
    }
  }, [effectiveEmail]);

  useEffect(() => {
    const refreshSelectedCalendar = () => {
      if (section === "calendar") getGoogleEvents();
    };
    window.addEventListener("google-calendar:changed", refreshSelectedCalendar);
    return () =>
      window.removeEventListener("google-calendar:changed", refreshSelectedCalendar);
  }, [getGoogleEvents, section]);

  // Only try to fetch events when in calendar/appointments AND connected.
  useEffect(() => {
    (async () => {
      if (!effectiveEmail) return;

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
  }, [section, effectiveEmail, checkGoogleConnection, getGoogleEvents]);

  function handleQuickAdd(day) {
    setQuickAddDate(day);
    setShowQuickAdd(true);
  }

  async function handleQuickAddSave({ leadId, title, time }) {
    if (!leadId || !title || !quickAddDate) return;
    try {
      const date = localDateKey(quickAddDate);
      const appointmentTime = buildAppointmentTimestamp(date, time);
      if (!appointmentTime) throw new Error("Choose a valid appointment date and time.");
      const response = await fetch(
        apiUrl(`appointments/${encodeURIComponent(effectiveEmail)}`),
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            lead_id: leadId,
            title: title.trim(),
            appointment_time: appointmentTime,
            timezone: appointmentsTimezone || getBrowserTimeZone(),
            duration: 30,
            status: "scheduled",
          }),
        }
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.error || "Could not create the appointment.");
      await refreshAppointments();
      window.dispatchEvent(new Event("appointments:changed"));
      setShowQuickAdd(false);
      setQuickAddDate(null);
    } catch (error) {
      alert(error?.message || "Could not create the appointment. Please try again.");
    }
  }

  useEffect(() => {
    window.RetainAI = window.RetainAI || {};
    window.RetainAI.openImports = openImports;
    window.RetainAI.openSection = (nextSection) => setSection(nextSection);
    window.RetainAI.openTeam = () => {
      setSettingsTab("team");
      setSection("settings");
    };
  }, [openImports]);

  if (!user) return null;

  return (
    <div
      className="crm-root"
      style={{
        minHeight: "100vh",
        width: "100%",
        overflowX: "hidden",
        background: "#181a1b",
      }}
    >
      <CommandPalette
        setSection={setSection}
        isOwner={sessionCapabilities.platformOwner}
        canManageBilling={sessionCapabilities.canManageBilling}
      />
      <header className="crm-mobile-header">
        <button
          type="button"
          className="crm-mobile-menu-btn"
          onClick={() => setMobileNavOpen(true)}
          aria-label="Open navigation"
        >
          <FaBars />
        </button>
        <img src={logo} alt="RetainAI" className="crm-mobile-logo" />
        <div className="crm-mobile-title">
          <strong>RetainAI</strong>
          <span>{SECTION_LABELS[section] || "CRM"}</span>
        </div>
      </header>
      <TrialCommandBar user={user} />
      <OnboardingGuide
        user={user}
        leads={leads}
        setSection={setSection}
        openImports={openImports}
      />

      {mobileNavOpen && (
        <button
          type="button"
          className="crm-sidebar-overlay"
          onClick={() => setMobileNavOpen(false)}
          aria-label="Close navigation"
        />
      )}

      <Sidebar
        logo={logo}
        onLogout={handleLogout}
        user={user}
        setSection={(nextSection) => {
          if (nextSection === "settings") {
            openSettings();
            return;
          }
          setSection(nextSection);
        }}
        section={section}
        collapsed={isMobile ? false : sidebarCollapsed}
        setCollapsed={setSidebarCollapsed}
        isMobile={isMobile}
        mobileOpen={mobileNavOpen}
        onMobileClose={() => setMobileNavOpen(false)}
        onInviteTeam={() => setShowInviteModal(true)}
        onImportLeads={openImports}
      />

      <div
        className={`crm-main-content crm-section-${section}`}
        style={{
          minHeight: "100vh",
          marginLeft: SIDEBAR_WIDTH,
          transition: "margin-left 0.25s cubic-bezier(.77,.2,.2,1)",
          display: "flex",
          flexDirection: "column",
          width: `calc(100vw - ${SIDEBAR_WIDTH}px)`,
          padding: isMobile
            ? section === "settings"
              ? "64px 0 0"
              : "76px 14px 24px"
            : section === "settings"
            ? "0"
            : "24px",
          boxSizing: "border-box",
        }}
      >
        {SECTION_META[section] && (
          <header className="app-section-hero">
            <div>
              <span className="app-section-eyebrow">{SECTION_META[section][0]}</span>
              <h1>{SECTION_META[section][1]}</h1>
              <p>{SECTION_META[section][2]}</p>
            </div>
            <span className="app-section-live"><i /> Workspace live</span>
          </header>
        )}

        {section === "overview" && (
          <RetentionCommandCenter
            leads={leads}
            appointments={crmAppointments}
            user={user}
            onOpenMessages={() => setSection("messages")}
            onOpenAutomations={(playbook) => {
              try {
                localStorage.setItem("retainai:selected-playbook", playbook || "");
              } catch {}
              setSection("automations");
            }}
          />
        )}

        {section === "dashboard" && (
          <>
            {leadPersistenceError && (
              <div
                role="alert"
                style={{
                  marginBottom: 12,
                  padding: "11px 13px",
                  border: "1px solid rgba(230,101,101,.55)",
                  borderRadius: 10,
                  background: "rgba(230,101,101,.08)",
                  color: "#ff9b9b",
                  fontSize: 13,
                }}
              >
                {leadPersistenceError}
              </div>
            )}
            <LeadsDashboard
              leads={leads}
              loading={loadingLeads}
              user={user}
              onAddLead={() => {
                setEditLead(null);
                setShowLeadModal(true);
              }}
              onEditLead={(lead) => {
                setEditLead(lead);
                setShowLeadModal(true);
              }}
              onDeleteLead={handleDeleteLead}
              drawerLead={drawerLead}
              setDrawerLead={setDrawerLead}
              onContactedLead={handleLeadContacted}
              onImportLeads={openImports}
              onUpdateLead={handleUpdateLead}
              onSendNotification={handleSendNotification}
            />

            {showLeadModal && (
              <LeadModal
                lead={editLead}
                tags={tags}
                onClose={() => {
                  setShowLeadModal(false);
                  setEditLead(null);
                }}
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
                  gap: 10,
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
                  style={{
                    background: "#f7cb53",
                    color: "#232323",
                    border: "none",
                    borderRadius: 8,
                    padding: "8px 12px",
                    fontWeight: 800,
                    cursor: "pointer",
                  }}
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
                  position: "fixed",
                  left: 0,
                  top: 0,
                  width: "100%",
                  height: "100vh",
                  background: "#000a",
                  zIndex: 99,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
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
                  <h3
                    style={{
                      color: "#f7cb53",
                      fontWeight: 800,
                      marginBottom: 12,
                      fontSize: "1.05rem",
                    }}
                  >
                    Add Appointment ({quickAddDate?.toLocaleDateString()})
                  </h3>
                  <QuickAddForm
                    leads={leads}
                    timeZone={appointmentsTimezone || getBrowserTimeZone()}
                    onSave={handleQuickAddSave}
                    onCancel={() => {
                      setShowQuickAdd(false);
                      setQuickAddDate(null);
                    }}
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

        {section === "analytics" && <Insights leads={leads} events={crmAppointments} user={user} />}

        {section === "invoices" && sessionCapabilities.canManageBilling && (
          <Invoices user={user} leads={leads} refreshUser={handleRefreshUser} />
        )}

        {section === "automations" && <Automations user={user} />}

        {section === "owner" && user?.platformOwner && <OwnerConsole />}
      </div>

      {showInviteModal && <InviteTeamModal user={user} onClose={() => setShowInviteModal(false)} />}
    </div>
  );
}

// Quick Add Appointment form
function QuickAddForm({ leads, onSave, onCancel, timeZone }) {
  const [leadId, setLeadId] = useState("");
  const [title, setTitle] = useState("");
  const [time, setTime] = useState(() => {
    const next = new Date(Date.now() + 30 * 60 * 1000);
    next.setMinutes(Math.ceil(next.getMinutes() / 15) * 15, 0, 0);
    return timeKeyFromParts(appointmentDateTimeParts(next, timeZone)) || "09:00";
  });
  const [saving, setSaving] = useState(false);

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (saving) return;
        setSaving(true);
        try {
          await onSave({ leadId, title, time });
        } finally {
          setSaving(false);
        }
      }}
    >
      <div style={{ marginBottom: 14 }}>
        <label style={{ color: "#fff", fontWeight: 700, display: "block", marginBottom: 6 }}>
          Lead
        </label>
        <select
          value={leadId}
          onChange={(e) => setLeadId(e.target.value)}
          style={{
            padding: "10px 12px",
            borderRadius: 8,
            background: "#181a1b",
            color: "#fff",
            border: "1px solid #444",
            width: "100%",
          }}
          required
        >
          <option value="">Select Lead</option>
          {leads.map((lead) => (
            <option value={lead.id} key={lead.id}>
              {lead.name}
            </option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: 14 }}>
        <label style={{ color: "#fff", fontWeight: 700, display: "block", marginBottom: 6 }}>
          Title
        </label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Appointment title"
          style={{
            padding: "10px 12px",
            borderRadius: 8,
            background: "#181a1b",
            color: "#fff",
            border: "1px solid #444",
            width: "100%",
          }}
          required
        />
      </div>

      <div style={{ marginBottom: 14 }}>
        <label style={{ color: "#fff", fontWeight: 700, display: "block", marginBottom: 6 }}>
          Time
        </label>
        <input
          type="time"
          value={time}
          onChange={(e) => setTime(e.target.value)}
          style={{
            padding: "10px 12px",
            borderRadius: 8,
            background: "#181a1b",
            color: "#fff",
            border: "1px solid #444",
            width: "100%",
          }}
          required
        />
        <div style={{ color: "#9aa3ab", fontSize: 12, marginTop: 6 }}>
          Saved in {String(timeZone || "UTC").replace(/_/g, " ")}.
        </div>
      </div>

      <div style={{ display: "flex", gap: 10 }}>
        <button
          type="submit"
          disabled={saving}
          style={{
            background: "#f7cb53",
            color: "#232323",
            fontWeight: 800,
            border: "none",
            borderRadius: 8,
            padding: "11px 0",
            cursor: "pointer",
            width: "50%",
          }}
        >
          {saving ? "Adding…" : "Add"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          style={{
            background: "#232323",
            color: "#fff",
            fontWeight: 800,
            border: "1px solid #444",
            borderRadius: 8,
            padding: "11px 0",
            cursor: "pointer",
            width: "50%",
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default CrmDashboard;
