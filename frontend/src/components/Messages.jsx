// src/components/Messages.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { SiWhatsapp } from "react-icons/si";
import { API_BASE } from "../config";

/** ===== THEME ===== */
const C = {
  bg: "#181a1b",
  panel: "#232323",
  header: "#1d1f20",
  border: "#2b2f33",
  text: "#f3f4f5",
  sub: "#9aa3ab",
  accent: "#f7cb53",
  wa: "#25D366",
  danger: "#e66565",
  success: "#25D366",
  in: "#202c33",
  out: "#005c4b",
  soft: "#1e2326",
  softer: "#15181a",
  mutedBlue: "#1e2a30",
};
const PANEL_H = "72vh";

/** ===== HELPERS ===== */
function cleanAIText(t) {
  let s = String(t || "");

  s = s
    .replace(/^(Subject|Lead Name|Recipient):.*(\n|$)/gi, "")
    .replace(/^\s*[\w ]+:\s*$/gim, "")
    .replace(/^\s*\n+/g, "")
    .replace(/^\s*\[template:[^\]]+\]\s*/i, "");

  const introAnywhere = new RegExp(
    String.raw`(^|[\s]*[,;:\-\u2013\u2014]\s*)` +
      String.raw`(?:it'?s|it\u2019s|this\s+is)\s+` +
      String.raw`[^,\n\r;:\-\u2013\u2014]{1,60}\s+` +
      String.raw`(?:from|at)\s+` +
      String.raw`[^,\n\r;:\-\u2013\u2014]{1,120}\s*` +
      String.raw`[\-\u2013\u2014:]\s*`,
    "gi"
  );

  let prev = null;
  while (prev !== s) {
    prev = s;
    s = s.replace(introAnywhere, (_m, keep) => keep || "");
  }

  s = s.replace(/[ \t]{2,}/g, " ");
  return s.trim();
}

const htmlToText = (s) => {
  if (!s) return "";
  let t = String(s);
  t = t.replace(/<br\s*\/?>/gi, "\n");
  t = t.replace(/<\/p>\s*<p>/gi, "\n\n");
  t = t.replace(/<\/?[^>]+>/g, "");
  return t.trim();
};

const initials = (name, email) =>
  !name && !email
    ? "?"
    : (name ? name.split(" ").map((p) => p[0]).join("") : (email || "?")[0])
        .toUpperCase()
        .slice(0, 2);

const digits = (s = "") => (s || "").replace(/\D/g, "");

const fmtNA = (num) => {
  const n = digits(num);
  return n.length === 11 && n.startsWith("1")
    ? `(${n.slice(1, 4)}) ${n.slice(4, 7)}-${n.slice(7)}`
    : num || "";
};

const FIRSTNAME = (s = "") => String(s).trim().split(/\s+/)[0] || "";
const LOWER = (s = "") => String(s).toLowerCase();

const toApiLang = (ui) => String(ui || "").replace("-", "_");
const normApi = (code) => {
  if (!code) return "en";
  const c = String(code).replace("-", "_").trim();
  const p = c.split("_");
  return p.length === 2 ? `${p[0].toLowerCase()}_${p[1].toUpperCase()}` : p[0].toLowerCase();
};
const toUiLang = (api) => {
  const a = String(api || "").toLowerCase();
  if (!a) return "en";
  return a.startsWith("en") ? "en" : api;
};

const ping = (name) => window.dispatchEvent(new Event(name));

function pad2(n) {
  return String(n).padStart(2, "0");
}
function nextDow(from, targetDow, allowToday = false) {
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  const curr = d.getDay();
  let delta = (targetDow - curr + 7) % 7;
  if (delta === 0 && !allowToday) delta = 7;
  d.setDate(d.getDate() + delta);
  return d;
}
function thisOrNextDow(from, targetDow) {
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  const curr = d.getDay();
  let delta = targetDow - curr;
  if (delta < 0) delta += 7;
  if (delta === 0) return d;
  d.setDate(d.getDate() + delta);
  return d;
}
function toISODate(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function parseApptFromText(text) {
  if (!text) return null;
  const t = String(text).toLowerCase();

  const ampm = t.match(/\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b/i);
  const hhmm = !ampm && t.match(/\b([01]?\d|2[0-3]):([0-5]\d)\b/);

  let hours = null;
  let minutes = 0;

  if (ampm) {
    const h = parseInt(ampm[1], 10);
    const m = ampm[2] ? parseInt(ampm[2], 10) : 0;
    const isPM = /p/i.test(ampm[3]);
    hours = (h % 12) + (isPM ? 12 : 0);
    minutes = m;
  } else if (hhmm) {
    hours = parseInt(hhmm[1], 10);
    minutes = parseInt(hhmm[2], 10);
  } else {
    const bareHour = t.match(/\bat\s*(\d{1,2})\b/);
    if (bareHour) {
      const h = parseInt(bareHour[1], 10);
      if (h >= 1 && h <= 12) {
        hours = h <= 7 ? h + 12 : h;
      }
    }
  }

  const dows = {
    sunday: 0,
    monday: 1,
    tuesday: 2,
    wednesday: 3,
    thursday: 4,
    friday: 5,
    saturday: 6,
  };

  let targetDate = null;
  const now = new Date();

  if (/\btoday\b/.test(t)) {
    targetDate = new Date(now);
  } else if (/\btomorrow\b/.test(t)) {
    targetDate = new Date(now);
    targetDate.setDate(targetDate.getDate() + 1);
  } else {
    const dowMatch = t.match(/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i);
    if (dowMatch) {
      const dow = dows[dowMatch[1].toLowerCase()];
      if (/\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i.test(t)) {
        const d = thisOrNextDow(now, dow);
        targetDate = d < now ? nextDow(now, dow) : d;
      } else if (/\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i.test(t)) {
        targetDate = nextDow(now, dow, false);
      } else {
        const allowToday =
          hours != null ? hours > now.getHours() || (hours === now.getHours() && minutes > now.getMinutes()) : false;
        targetDate = nextDow(now, dow, allowToday);
      }
    }
  }

  if (!targetDate || hours == null) return null;

  return {
    date: toISODate(targetDate),
    time: `${pad2(hours)}:${pad2(minutes)}`,
  };
}

/** ===== LOCAL PERSISTENCE ===== */
const SUG_KEYS = (email) => ({
  consumed: `msg_suggestions_consumed_${email || "anon"}`,
});
const AUTO_LOG_KEY = (userEmail, leadId) =>
  `auto_log_${(userEmail || "anon").toLowerCase()}_${String(leadId || "lead")}`;
const TEMPLATE_RENDER_KEY = (userEmail, leadId) =>
  `wa_template_render_cache_${(userEmail || "anon").toLowerCase()}_${String(leadId || "lead")}`;

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

const sigForSuggestion = (leadId, sug) =>
  `${String(leadId || "lead")}|${sug?.date || ""}|${sug?.time || ""}`;

/** ===== TEMPLATE PARSING / RENDERING ===== */
const between = (txt, startIdx, endIdx, span = 36) => {
  const left = Math.max(0, startIdx - span);
  const right = Math.min(txt.length, endIdx + span);
  return {
    left: LOWER(txt.slice(left, startIdx)),
    right: LOWER(txt.slice(endIdx, right)),
  };
};

function inferParamKindsFromBody(bodyText, count, templateName = "") {
  const kinds = Array.from({ length: count }, () => null);
  const body = String(bodyText || "");
  const bodyLower = LOWER(body);
  const nameLower = LOWER(templateName);

  for (let i = 1; i <= count; i++) {
    const re = new RegExp(`\\{\\{\\s*${i}\\s*\\}\\}`, "g");
    const m = re.exec(body);
    if (!m) continue;
    const { index } = m;
    const ctx = between(body, index, index + m[0].length, 44);
    const L = ctx.left;
    const R = ctx.right;
    const around = `${L} ${R}`;

    if (/(^|\s)(hi|hello|hey|dear)\s*$/.test(L) || /(client|customer|guest|lead|name)\s*$/.test(L)) {
      kinds[i - 1] = "lead_name";
      continue;
    }
    if (/(i'?m|i am|this is)\s*$/.test(L)) {
      kinds[i - 1] = "user_name";
      continue;
    }
    if (/(from|at)\s*$/.test(L) || /^(\s*(from|at)\b)/.test(R) || /\bbusiness\b/.test(around)) {
      kinds[i - 1] = "business";
      continue;
    }
    if (/\b(date|day|tomorrow|today|scheduled for|booked for)\b/.test(around)) {
      kinds[i - 1] = "date";
      continue;
    }
    if (/\b(time|slot|pm|am|o'clock|at)\b/.test(around)) {
      kinds[i - 1] = "time";
      continue;
    }
    if (/\b(location|address|studio|office|salon|shop)\b/.test(around)) {
      kinds[i - 1] = "location";
      continue;
    }
    if (/\b(service|treatment|package|appointment type)\b/.test(around)) {
      kinds[i - 1] = "service";
      continue;
    }
    if (/\b(price|quote|budget|total|cost)\b/.test(around)) {
      kinds[i - 1] = "price";
      continue;
    }
    if (/\bemail\b/.test(around)) {
      kinds[i - 1] = "email";
      continue;
    }
    if (/\bphone|number|call\b/.test(around)) {
      kinds[i - 1] = "phone";
      continue;
    }
  }

  // Template-name-aware cleanup
  for (let i = 0; i < kinds.length; i++) {
    if (kinds[i]) continue;

    if (/resched|reschedule/.test(nameLower)) {
      kinds[i] =
        i === 0 ? "lead_name" :
        i === 1 ? "business" :
        i === 2 ? "date" :
        i === 3 ? "time" :
        "details";
      continue;
    }

    if (/confirm|confirmation/.test(nameLower)) {
      kinds[i] =
        i === 0 ? "lead_name" :
        i === 1 ? "business" :
        i === 2 ? "date" :
        i === 3 ? "time" :
        i === 4 ? "location" :
        "details";
      continue;
    }

    if (/follow|reminder/.test(nameLower)) {
      kinds[i] =
        i === 0 ? "lead_name" :
        i === 1 ? "business" :
        i === 2 ? "details" :
        "details";
      continue;
    }

    if (/welcome|intro|outreach/.test(nameLower)) {
      kinds[i] =
        i === 0 ? "lead_name" :
        i === 1 ? "user_name" :
        i === 2 ? "business" :
        i === 3 ? "details" :
        "details";
      continue;
    }

    kinds[i] =
      i === 0 ? "lead_name" :
      i === 1 ? "user_name" :
      i === 2 ? "business" :
      i === 3 ? "details" :
      i === 4 ? "date" :
      i === 5 ? "time" :
      "details";
  }

  return kinds;
}

function valueForKind(kind, { user, lead, input, suggestion }) {
  switch (kind) {
    case "lead_name":
      return FIRSTNAME(lead?.name) || lead?.name || (lead?.email ? lead.email.split("@")[0] : "") || "there";
    case "user_name":
      return user?.name || "";
    case "business":
      return user?.business || user?.businessType || "";
    case "details":
      return (input || "").trim();
    case "date":
      return suggestion?.date || "";
    case "time":
      return suggestion?.time || "";
    case "location":
      return lead?.location || user?.location || "";
    case "service":
      return Array.isArray(lead?.tags) && lead.tags.length ? lead.tags[0] : "";
    case "price":
      return "";
    case "email":
      return lead?.email || user?.email || "";
    case "phone":
      return lead?.whatsapp || lead?.phone || "";
    default:
      return "";
  }
}

function friendlyLabelForKind(kind, i) {
  switch (kind) {
    case "lead_name":
      return "Lead first name";
    case "user_name":
      return "Your name";
    case "business":
      return "Business name";
    case "details":
      return "Message details";
    case "date":
      return "Appointment date";
    case "time":
      return "Appointment time";
    case "location":
      return "Location";
    case "service":
      return "Service";
    case "price":
      return "Price";
    case "email":
      return "Email";
    case "phone":
      return "Phone";
    default:
      return `Field ${i + 1}`;
  }
}

function fieldHintForKind(kind) {
  switch (kind) {
    case "lead_name":
      return "John";
    case "user_name":
      return "Mateo";
    case "business":
      return "Makijo Nails";
    case "details":
      return "your appointment is confirmed";
    case "date":
      return "2026-05-24";
    case "time":
      return "7:00 PM";
    case "location":
      return "123 Main St";
    case "service":
      return "Nail fill";
    case "price":
      return "$75";
    case "email":
      return "lead@email.com";
    case "phone":
      return "(226) 201-4738";
    default:
      return "Enter value";
  }
}

function renderTemplatePreview(bodyText, values = []) {
  let out = String(bodyText || "");
  values.forEach((v, idx) => {
    const re = new RegExp(`\\{\\{\\s*${idx + 1}\\s*\\}\\}`, "g");
    out = out.replace(re, v || `{{${idx + 1}}}`);
  });
  return cleanAIText(out).trim();
}

function parseTemplateEchoText(text) {
  const raw = String(text || "").trim();
  if (!raw) return null;

  if (/^\[template:[^\]]+\]/i.test(raw)) {
    return { kind: "template_echo", text: "" };
  }

  // exact object-ish payload strings
  if (/^\s*\{[\s\S]*payload[\s\S]*text[\s\S]*\}\s*$/i.test(raw)) {
    const textMatch =
      raw.match(/(?:^|[,{]\s*)text\s*:\s*'([^']*)'/i) ||
      raw.match(/(?:^|[,{]\s*)text\s*:\s*"([^"]*)"/i) ||
      raw.match(/['"]text['"]\s*:\s*'([^']*)'/i) ||
      raw.match(/['"]text['"]\s*:\s*"([^"]*)"/i);

    const payloadMatch =
      raw.match(/(?:^|[,{]\s*)payload\s*:\s*'([^']*)'/i) ||
      raw.match(/(?:^|[,{]\s*)payload\s*:\s*"([^"]*)"/i) ||
      raw.match(/['"]payload['"]\s*:\s*'([^']*)'/i) ||
      raw.match(/['"]payload['"]\s*:\s*"([^"]*)"/i);

    return {
      kind: "payload_echo",
      text: (textMatch?.[1] || payloadMatch?.[1] || "").trim(),
    };
  }

  return null;
}

function pushTemplateRenderCache(userEmail, leadId, renderedText, meta = {}) {
  const key = TEMPLATE_RENDER_KEY(userEmail, leadId);
  const existing = loadJSON(key, []);
  const next = [
    ...existing,
    {
      id: `${Date.now()}_${Math.random().toString(16).slice(2)}`,
      text: renderedText,
      template_name: meta.template_name || "",
      language_code: meta.language_code || "",
      created_at: new Date().toISOString(),
      used: false,
    },
  ].slice(-20);
  saveJSON(key, next);
}

function consumeTemplateRenderCache(userEmail, leadId, countNeeded) {
  const key = TEMPLATE_RENDER_KEY(userEmail, leadId);
  const existing = loadJSON(key, []);
  if (!Array.isArray(existing) || !existing.length) {
    return { consumed: [], nextCache: existing || [] };
  }

  const consumed = [];
  const nextCache = existing.map((item) => {
    if (!item.used && consumed.length < countNeeded) {
      consumed.push(item.text || "");
      return { ...item, used: true };
    }
    return item;
  });

  saveJSON(key, nextCache);
  return { consumed, nextCache };
}

function normalizeThreadMessages(rawMessages, userEmail, leadId) {
  const list = Array.isArray(rawMessages) ? rawMessages.map((m) => ({ ...m })) : [];
  const payloadIndexes = [];

  list.forEach((m, idx) => {
    if (m?.from !== "user") return;
    const parsed = parseTemplateEchoText(m?.text);
    if (parsed) payloadIndexes.push({ idx, parsed });
  });

  if (!payloadIndexes.length) return list;

  const { consumed } = consumeTemplateRenderCache(userEmail, leadId, payloadIndexes.length);

  payloadIndexes.forEach((entry, i) => {
    const rendered = consumed[i];
    const fallbackExtracted = cleanAIText(entry?.parsed?.text || "");
    const finalText = cleanAIText(rendered || fallbackExtracted || "");

    list[entry.idx] = {
      ...list[entry.idx],
      text: finalText || fallbackExtracted || "",
      _rendered_template: true,
      _payload_cleaned: true,
    };
  });

  return list.filter((m) => {
    if (m?.from !== "user") return true;
    const parsed = parseTemplateEchoText(m?.text);
    if (!parsed) return true;
    const cleaned = cleanAIText(m?.text || "");
    return Boolean(cleaned);
  });
}

function getChatPreview(thread) {
  if (!Array.isArray(thread) || !thread.length) return "No messages yet";
  for (let i = thread.length - 1; i >= 0; i--) {
    const txt = cleanAIText(thread[i]?.text || "");
    if (txt) return txt;
  }
  return "No messages yet";
}

function buildConversationHistory(thread, maxItems = 8) {
  return (Array.isArray(thread) ? thread : [])
    .slice(-maxItems)
    .map((m) => ({
      role: m?.from === "user" ? "business" : "lead",
      text: cleanAIText(m?.text || ""),
      time: m?.time || "",
    }))
    .filter((m) => m.text);
}

function quickSuggestionFromInbound(text, leadName) {
  const inbound = String(text || "").trim();
  if (!inbound) return "";

  const name = FIRSTNAME(leadName) || "there";
  const t = inbound.toLowerCase();

  if (/(resched|reschedule|move|another time|tomorrow|next week|what time)/i.test(t)) {
    return `Hi ${name}! No problem at all. I can help with that. What time works best for you?`;
  }
  if (/(confirm|confirmed|okay sounds good|sounds good|works for me|perfect)/i.test(t)) {
    return `Hi ${name}! Perfect — you're all set. Let me know if you need anything before your appointment.`;
  }
  if (/(price|cost|how much|quote)/i.test(t)) {
    return `Hi ${name}! I’d be happy to help with pricing. Tell me what service you’re looking for and I’ll send the details over.`;
  }
  if (/(thanks|thank you)/i.test(t)) {
    return `You’re very welcome, ${name}!`;
  }
  return `Hi ${name}! Thanks for the message.`;
}

function buildSmartAutofillValues(expectedParams, paramKinds, context) {
  return Array.from({ length: expectedParams }, (_, idx) => {
    const kind = paramKinds?.[idx];
    return valueForKind(kind, context) || "";
  });
}

/** ===== COMPONENT ===== */
export default function Messages({ user, leads = [], defaultTemplate = "", language = "en" }) {
  const API = (() => {
    const env = (v) => (v && v.trim()) || "";
    const fromEnv =
      env(process.env.REACT_APP_API_URL) ||
      env(process.env.REACT_APP_API_BASE);
    if (fromEnv) return fromEnv.replace(/\/$/, "");
    return API_BASE;
  })();

  /** --- selection & list filter --- */
  const [q, setQ] = useState("");
  const filteredLeads = useMemo(() => {
    if (!q.trim()) return leads;
    const s = q.trim().toLowerCase();
    return leads.filter(
      (l) =>
        (l.name || "").toLowerCase().includes(s) ||
        (l.email || "").toLowerCase().includes(s) ||
        (l.phone || "").toLowerCase().includes(s) ||
        (l.whatsapp || "").toLowerCase().includes(s)
    );
  }, [leads, q]);

  const [activeLeadId, setActiveLeadId] = useState(filteredLeads?.[0]?.id ?? null);

  useEffect(() => {
    if (!filteredLeads.length) {
      setActiveLeadId(null);
      return;
    }
    if (!filteredLeads.find((l) => String(l.id) === String(activeLeadId))) {
      setActiveLeadId(filteredLeads[0]?.id ?? null);
    }
  }, [filteredLeads, activeLeadId]);

  const lead = useMemo(
    () => filteredLeads.find((l) => String(l.id) === String(activeLeadId)),
    [filteredLeads, activeLeadId]
  );

  const toE164 = useMemo(() => digits(lead?.whatsapp || lead?.phone), [lead]);

  /** --- thread state --- */
  const [thread, setThread] = useState([]);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const chatRef = useRef(null);
  const pollTimer = useRef(null);

  const [autoLog, setAutoLog] = useState([]);
  const [showAutoLog, setShowAutoLog] = useState(false);

  useEffect(() => {
    setThread([]);
    setInput("");
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
    setSuggestion(null);

    if (user?.email && lead?.id) {
      const key = AUTO_LOG_KEY(user.email, lead.id);
      setAutoLog(loadJSON(key, []));
    } else {
      setAutoLog([]);
    }
    setShowAutoLog(false);
  }, [activeLeadId, user?.email, lead?.id]);

  useEffect(() => {
    if (!API || !user?.email || !lead?.id) return;
    let stop = false;

    const tick = async () => {
      setPolling(true);
      try {
        const r = await fetch(
          `${API}/api/whatsapp/messages?user_email=${encodeURIComponent(user.email)}&lead_id=${encodeURIComponent(
            lead.id
          )}`
        );
        const j = await r.json();
        const normalized = normalizeThreadMessages(j?.messages, user.email, lead.id);
        if (!stop) setThread(Array.isArray(normalized) ? normalized : []);
      } catch {
      } finally {
        if (!stop) setPolling(false);
      }
      if (!stop) pollTimer.current = setTimeout(tick, 6000);
    };

    tick();
    return () => {
      stop = true;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [API, user?.email, lead?.id]);

  useEffect(() => {
    chatRef.current?.scrollTo({ top: 1e9, behavior: "smooth" });
  }, [thread.length, activeLeadId]);

  /** --- 24h gate & templates --- */
  const [gate, setGate] = useState({
    inside24h: false,
    canFreeText: false,
    canTemplate: false,
    templateApproved: false,
    templateStatus: "UNKNOWN",
  });

  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templatesError, setTemplatesError] = useState("");
  const [templateName, setTemplateName] = useState(defaultTemplate);
  const [templateLangUI, setTemplateLangUI] = useState(language);

  const [health, setHealth] = useState(null);
  useEffect(() => {
    if (!API) return;
    (async () => {
      try {
        const r = await fetch(`${API}/api/whatsapp/health`);
        const j = await r.json();
        setHealth(j);
      } catch {}
    })();
  }, [API]);

  useEffect(() => {
    if (!API) return;
    (async () => {
      setTemplatesLoading(true);
      setTemplatesError("");
      try {
        const r = await fetch(`${API}/api/whatsapp/templates`);
        const j = await r.json();

        const rows =
          Array.isArray(j?.data?.data) ? j.data.data :
          Array.isArray(j?.data) ? j.data :
          Array.isArray(j?.templates) ? j.templates :
          [];

        const cleaned = rows.filter((t) => String(t?.name || "").toLowerCase() !== "hello_world");

        setTemplates(
          cleaned.map((t) => ({
            name: t.name,
            languageUI: toUiLang(t.normalized_language || t.language),
            status: String(t.status || "").toUpperCase(),
          }))
        );

        if (!cleaned.length) {
          setTemplatesError("No WhatsApp templates were found for this account.");
        }
      } catch {
        setTemplatesError("Could not load WhatsApp templates.");
      } finally {
        setTemplatesLoading(false);
      }
    })();
  }, [API]);

  useEffect(() => {
    if (!templates.length) return;
    const hasCurrent = templateName && templates.some((t) => t.name === templateName && t.languageUI === templateLangUI);
    if (hasCurrent) return;

    const preferredName = (health?.default_template || defaultTemplate || "").trim();
    const preferredLangUI = toUiLang(health?.default_lang_api || language);

    const choice =
      (preferredName &&
        templates.find((t) => t.name === preferredName && t.languageUI === preferredLangUI && t.status === "APPROVED")) ||
      (preferredName && templates.find((t) => t.name === preferredName && t.status === "APPROVED")) ||
      templates.find((t) => t.status === "APPROVED") ||
      templates[0];

    if (choice) {
      setTemplateName(choice.name);
      setTemplateLangUI(choice.languageUI);
    }
  }, [templates, health, defaultTemplate, language, templateName, templateLangUI]);

  const refreshWindow = async (force = false) => {
    if (!API || !user?.email || !lead?.id) return;
    const langApi = normApi(toApiLang(templateLangUI));
    const tpl = (templateName || "").trim();
    try {
      const url = `${API}/api/whatsapp/window-state?user_email=${encodeURIComponent(
        user.email
      )}&lead_id=${encodeURIComponent(lead.id)}&template_name=${encodeURIComponent(tpl)}&language_code=${encodeURIComponent(
        langApi
      )}${force ? "&force=1" : ""}`;
      const r = await fetch(url);
      const d = await r.json();
      setGate({
        inside24h: !!d.inside24h,
        canFreeText: !!d.canFreeText,
        canTemplate: !!d.canTemplate,
        templateApproved: !!d.templateApproved,
        templateStatus: String(d.templateStatus || "UNKNOWN").toUpperCase(),
      });
    } catch {}
  };

  useEffect(() => {
    refreshWindow(false);
  }, [API, user?.email, lead?.id, templateName, templateLangUI]); // eslint-disable-line

  useEffect(() => {
    refreshWindow(true);
  }, []); // eslint-disable-line

  /** --- template params --- */
  const [expectedParams, setExpectedParams] = useState(null);
  const [paramValues, setParamValues] = useState([]);
  const [templateBodyText, setTemplateBodyText] = useState("");
  const [templateExample, setTemplateExample] = useState(null);
  const [paramKinds, setParamKinds] = useState([]);
  const [templateInfoLoading, setTemplateInfoLoading] = useState(false);
  const [templateInfoError, setTemplateInfoError] = useState("");

  useEffect(() => {
    if (!API) return;
    const name = (templateName || "").trim();
    const languageCode = normApi(toApiLang(templateLangUI));

    if (!name || name.toLowerCase() === "hello_world") {
      setExpectedParams(null);
      setTemplateBodyText("");
      setTemplateExample(null);
      setParamValues([]);
      setParamKinds([]);
      setTemplateInfoError("");
      return;
    }

    (async () => {
      setTemplateInfoLoading(true);
      setTemplateInfoError("");
      try {
        const r = await fetch(
          `${API}/api/whatsapp/template-info?name=${encodeURIComponent(name)}&language_code=${encodeURIComponent(languageCode)}`
        );
        const j = await r.json();
        const t = (j.templates || [])[0];

        if (t) {
          const count = typeof t.body_param_count === "number" ? t.body_param_count : null;
          setExpectedParams(count);

          const comps = Array.isArray(t.components) ? t.components : [];
          const body = comps.find((c) => String(c.type || "").toUpperCase() === "BODY");
          const bodyText = body?.text || "";
          setTemplateBodyText(bodyText);

          const ex = body?.example?.body_text;
          setTemplateExample(Array.isArray(ex) && ex.length ? ex[0] : null);

          if (typeof count === "number" && count > 0) {
            const inferred = inferParamKindsFromBody(bodyText || "", count, name);
            setParamKinds(inferred);
            setParamValues((prev) => Array.from({ length: count }, (_, i) => prev?.[i] ?? ""));
          } else {
            setParamKinds([]);
            setParamValues([]);
          }
        } else {
          setExpectedParams(null);
          setTemplateBodyText("");
          setTemplateExample(null);
          setParamKinds([]);
          setParamValues([]);
          setTemplateInfoError("Could not read this template’s placeholders.");
        }
      } catch {
        setExpectedParams(null);
        setTemplateBodyText("");
        setTemplateExample(null);
        setParamKinds([]);
        setParamValues([]);
        setTemplateInfoError("Could not load this template’s details.");
      } finally {
        setTemplateInfoLoading(false);
      }
    })();
  }, [API, templateName, templateLangUI]);

  /** --- composer --- */
  const [input, setInput] = useState("");
  const [banner, setBanner] = useState(null);

  const lastInbound = useMemo(() => {
    for (let i = thread.length - 1; i >= 0; i--) {
      if (thread[i]?.from === "lead" && typeof thread[i]?.text === "string") {
        return thread[i].text;
      }
    }
    return "";
  }, [thread]);

  const conversationHistory = useMemo(() => buildConversationHistory(thread, 8), [thread]);

  const canSendBase = Boolean(API && user?.email && lead?.id && toE164);

  /** ---- appointment suggestion state (+ persistence) ---- */
  const [suggestion, setSuggestion] = useState(null);
  const [consumedMap, setConsumedMap] = useState({});

  useEffect(() => {
    setConsumedMap(loadJSON(SUG_KEYS(user?.email).consumed, {}));
  }, [user?.email]);

  useEffect(() => {
    const s = parseApptFromText(lastInbound);
    if (!s || !user?.email || !lead?.id) {
      setSuggestion(null);
      return;
    }
    const sig = sigForSuggestion(lead.id, s);
    if (consumedMap[sig]) {
      setSuggestion(null);
      return;
    }
    setSuggestion({ ...s });
  }, [lastInbound, user?.email, lead?.id, consumedMap]);

  const markConsumed = (sug) => {
    if (!sug || !user?.email || !lead?.id) return;
    const key = SUG_KEYS(user?.email).consumed;
    const sig = sigForSuggestion(lead.id, sug);
    const next = { ...consumedMap, [sig]: true };
    setConsumedMap(next);
    saveJSON(key, next);
  };

  const autofillParams = () => {
    if (typeof expectedParams !== "number" || expectedParams <= 0) return;
    const values = buildSmartAutofillValues(expectedParams, paramKinds, {
      user,
      lead,
      input,
      suggestion,
    });
    setParamValues(values);
  };

  const onConfirmSuggestion = async () => {
    if (!suggestion || !user?.email || !lead?.id) return;
    try {
      const appointment_time = `${suggestion.date}T${suggestion.time}:00`;

      const payload = {
        lead_email: lead?.email || "",
        lead_first_name: (lead?.name || "").split(" ")[0] || (lead?.name || "Client"),
        user_name: user?.name || "",
        user_email: user?.email,
        business_name: user?.business || user?.businessType || "",
        appointment_time,
        appointment_location: lead?.location || user?.location || "TBD",
        duration: 30,
        notes: "Auto-created from WhatsApp confirmation",
        lead_id: String(lead?.id || ""),
        status: "booked",
      };

      const res = await fetch(`${API}/api/appointments/${encodeURIComponent(user.email)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const j = await res.json();
      if (!res.ok) {
        setBanner(j?.error || `Failed to add appointment (${res.status})`);
        return;
      }

      setBanner(`Appointment added for ${suggestion.date} at ${suggestion.time}.`);
      markConsumed(suggestion);
      setSuggestion(null);
      ping("appointments:changed");

      setTimeout(async () => {
        try {
          const r = await fetch(
            `${API}/api/whatsapp/messages?user_email=${encodeURIComponent(user.email)}&lead_id=${encodeURIComponent(
              lead.id
            )}`
          );
          const jj = await r.json();
          const normalized = normalizeThreadMessages(jj?.messages, user.email, lead.id);
          setThread(Array.isArray(normalized) ? normalized : []);
        } catch {}
      }, 250);
    } catch (e) {
      setBanner(e.message || "Failed to add appointment.");
    }
  };

  const onSend = async () => {
    if (!canSendBase || loading) return;
    const text = input.trim();
    setLoading(true);
    setBanner(null);

    try {
      const payload = {
        to: toE164,
        user_email: user.email,
        lead_id: lead.id,
      };

      if (gate.inside24h) {
        if (!text) {
          setBanner("Type a message to send inside the 24-hour session.");
          setLoading(false);
          return;
        }
        payload.message = text;
        payload.skip_personalization = true;

        // optimistic bubble for free text
        setThread((prev) => [
          ...prev,
          {
            from: "user",
            text,
            time: new Date().toISOString(),
            _optimistic: true,
          },
        ]);
      } else {
        if (!templateName) {
          setBanner("Pick a template to send outside the 24-hour window.");
          setLoading(false);
          return;
        }

        if (!gate.templateApproved) {
          setBanner(`This template is not approved for sending right now (${gate.templateStatus}).`);
          setLoading(false);
          return;
        }

        payload.template_name = templateName;
        payload.language_code = normApi(toApiLang(templateLangUI));

        if (typeof expectedParams === "number" && expectedParams > 0) {
          const list = (paramValues || []).map((v) => String(v || "").trim()).slice(0, expectedParams);
          const missing = list.filter((v) => !v).length;
          if (missing) {
            setBanner(`This template needs ${expectedParams} field${expectedParams > 1 ? "s" : ""}. Please fill all of them.`);
            setLoading(false);
            return;
          }
          payload.template_params = list;
        }

        const rendered = renderTemplatePreview(templateBodyText, paramValues).trim();
        if (rendered) {
          pushTemplateRenderCache(user.email, lead.id, rendered, {
            template_name: templateName,
            language_code: normApi(toApiLang(templateLangUI)),
          });

          // optimistic rendered bubble
          setThread((prev) => [
            ...prev,
            {
              from: "user",
              text: rendered,
              time: new Date().toISOString(),
              _rendered_template: true,
              _optimistic: true,
            },
          ]);
        }
      }

      const res = await fetch(`${API}/api/whatsapp/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        setBanner(data?.error || `Send failed (${res.status})`);
        // rollback the optimistic last bubble if send failed
        setThread((prev) => prev.filter((m) => !m?._optimistic));
        return;
      }

      setBanner(data.mode === "template" ? `Template sent successfully.` : null);
      setInput("");

      if (typeof expectedParams === "number" && expectedParams > 0) {
        setParamValues(Array.from({ length: expectedParams }, () => ""));
      }

      setTimeout(async () => {
        try {
          const r = await fetch(
            `${API}/api/whatsapp/messages?user_email=${encodeURIComponent(user.email)}&lead_id=${encodeURIComponent(
              lead.id
            )}`
          );
          const j = await r.json();
          const normalized = normalizeThreadMessages(j?.messages, user.email, lead.id);
          setThread(Array.isArray(normalized) ? normalized : []);
        } catch {}
      }, 250);
    } catch (e) {
      setBanner(e.message || "Send failed.");
      setThread((prev) => prev.filter((m) => !m?._optimistic));
    } finally {
      setLoading(false);
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onSend();
  };

  const onDraftAI = async () => {
    if (!API || !lead) return;
    setBanner(null);

    const fallback = quickSuggestionFromInbound(lastInbound, lead?.name);

    try {
      const body = {
        lead: {
          name: lead.name || "",
          email: lead.email || "",
          phone: lead.phone || lead.whatsapp || "",
          tags: lead.tags || [],
          notes: lead.notes || "",
        },
        last_message: lastInbound || "",
        conversation_history: conversationHistory,
        user_business: user?.business || user?.businessType || "business",
        user_name: user?.name || "",
      };

      const r = await fetch(`${API}/api/generate-message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const j = await r.json();
      if (j?.reply) {
        const draft = cleanAIText(j.reply);
        setInput((prev) => (prev?.trim() ? prev.trim() + "\n\n" + draft : draft));
      } else {
        setInput((prev) => (prev?.trim() ? prev.trim() + "\n\n" + fallback : fallback));
      }
    } catch {
      setInput((prev) => (prev?.trim() ? prev.trim() + "\n\n" + fallback : fallback));
    }
  };

  /** --- Listen to Automations sends and show instantly in thread + log --- */
  useEffect(() => {
    const handler = (e) => {
      const items = (e?.detail?.items || []).filter(Boolean);
      if (!items.length || !lead || !user?.email) return;

      const leadEmail = String(lead.email || "").toLowerCase();
      const leadPhone = digits(lead.whatsapp || lead.phone);

      const matched = items.filter((it) => {
        const toLower = String(it.to || "").toLowerCase();
        const toDigits = digits(it.to || "");
        return (
          (leadEmail && toLower && toLower === leadEmail) ||
          (leadPhone && toDigits && (toDigits.endsWith(leadPhone) || leadPhone.endsWith(toDigits)))
        );
      });
      if (!matched.length) return;

      const bubbles = matched.map((it) => ({
        from: "user",
        text: htmlToText(it.text || it.subject || it.html || ""),
        time: it.created_at || new Date().toISOString(),
      }));

      setThread((prev) => [...prev, ...bubbles]);

      const key = AUTO_LOG_KEY(user.email, lead.id);
      setAutoLog((prev) => {
        const next = [...prev, ...matched];
        try {
          localStorage.setItem(key, JSON.stringify(next));
        } catch {}
        return next;
      });
    };

    window.addEventListener("app:message-sent", handler);
    return () => window.removeEventListener("app:message-sent", handler);
  }, [lead, user?.email]);

  /** --- UI when no leads --- */
  if (!Array.isArray(leads) || !leads.length) {
    return (
      <div style={{ width: "100%", minHeight: "100vh", background: C.bg }}>
        <Header />
        <div style={{ color: C.sub, padding: 18 }}>Add a lead with a WhatsApp number to start chatting.</div>
      </div>
    );
  }

  const hasTemplateParams = typeof expectedParams === "number" && expectedParams > 0;
  const templatePreview = renderTemplatePreview(templateBodyText, paramValues);
  const lastPreview = getChatPreview(thread);

  return (
    <div style={{ width: "100%", minHeight: "100vh", background: C.bg }}>
      <Header />

      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 18 }}>
        {/* LEFT – chat list */}
        <div
          style={{
            background: C.panel,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            overflow: "hidden",
            height: PANEL_H,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              height: 50,
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "0 12px",
              borderBottom: `1px solid ${C.border}`,
              color: C.text,
              fontWeight: 800,
            }}
          >
            <SiWhatsapp style={{ color: C.wa }} />
            Chats
          </div>

          <div style={{ padding: 10, borderBottom: `1px solid ${C.border}` }}>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search..."
              style={{
                width: "100%",
                background: C.bg,
                color: C.text,
                border: `1px solid ${C.border}`,
                borderRadius: 10,
                padding: "8px 10px",
                fontSize: 14,
                outline: "none",
              }}
            />
          </div>

          <div style={{ overflowY: "auto", flex: 1 }}>
            {filteredLeads.map((ld) => {
              const active = String(ld.id) === String(activeLeadId);
              const preview =
                String(ld.id) === String(activeLeadId)
                  ? lastPreview
                  : "Open chat";
              return (
                <button
                  key={ld.id}
                  onClick={() => setActiveLeadId(ld.id)}
                  style={{
                    width: "100%",
                    background: active ? C.header : "transparent",
                    border: 0,
                    borderBottom: `1px solid ${C.border}`,
                    color: C.text,
                    textAlign: "left",
                    cursor: "pointer",
                    padding: "10px 12px",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                  }}
                >
                  <div
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: "50%",
                      background: C.header,
                      display: "grid",
                      placeItems: "center",
                      color: C.accent,
                      fontWeight: 800,
                      border: `1px solid ${C.border}`,
                      flex: "0 0 34px",
                    }}
                  >
                    {initials(ld.name, ld.email)}
                  </div>
                  <div style={{ overflow: "hidden", minWidth: 0 }}>
                    <div
                      style={{
                        fontWeight: 700,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {ld.name || ld.email}
                    </div>
                    <div style={{ fontSize: 12, color: C.sub }}>{fmtNA(ld.phone || ld.whatsapp)}</div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "#7f8a92",
                        marginTop: 3,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {preview}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* RIGHT – thread + composer */}
        <div
          key={activeLeadId}
          style={{
            background: C.panel,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            height: PANEL_H,
            display: "grid",
            gridTemplateRows: suggestion
              ? gate.inside24h
                ? "56px auto 1fr auto"
                : "56px auto auto 1fr auto"
              : gate.inside24h
              ? "56px 1fr auto"
              : "56px auto 1fr auto",
            overflow: "hidden",
          }}
        >
          {/* Chat header */}
          <div
            style={{
              height: 56,
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "0 12px",
              borderBottom: `1px solid ${C.border}`,
              background: C.header,
              color: C.text,
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: "50%",
                background: C.panel,
                display: "grid",
                placeItems: "center",
                color: C.accent,
                fontWeight: 800,
                border: `1px solid ${C.border}`,
                flex: "0 0 36px",
              }}
            >
              {initials(lead?.name, lead?.email)}
            </div>

            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 800 }}>{lead?.name || lead?.email}</div>
              <div style={{ fontSize: 12, color: C.sub }}>{fmtNA(lead?.phone || lead?.whatsapp)}</div>
            </div>

            <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
              <button
                onClick={() => setShowAutoLog((s) => !s)}
                style={{
                  background: "transparent",
                  color: C.accent,
                  border: `1px solid ${C.accent}`,
                  padding: "6px 10px",
                  borderRadius: 999,
                  fontSize: 12,
                  fontWeight: 800,
                  cursor: "pointer",
                }}
                title="Show messages sent by automations"
              >
                Automation sends ({autoLog.length})
              </button>

              <Pill
                color={gate.inside24h ? C.wa : C.accent}
                text={
                  gate.inside24h
                    ? polling ? "Inside 24h · syncing" : "Inside 24h session"
                    : gate.templateApproved
                    ? "Outside 24h · template ready"
                    : `Outside 24h (${gate.templateStatus})`
                }
              />
            </div>
          </div>

          {/* Template controls */}
          {!gate.inside24h && (
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 8,
                alignItems: "center",
                padding: "10px 12px",
                borderBottom: `1px solid ${C.border}`,
                background: C.panel,
              }}
            >
              <div
                style={{
                  width: "100%",
                  display: "grid",
                  gridTemplateColumns: "1fr auto",
                  gap: 10,
                  alignItems: "center",
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ color: C.text, fontSize: 13, fontWeight: 800 }}>
                    Send approved template
                  </div>
                  <div style={{ color: C.sub, fontSize: 12, marginTop: 3 }}>
                    Required outside the 24-hour WhatsApp session.
                  </div>
                </div>

                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={autofillParams}
                    style={btn("ghost")}
                    title="Autofill common fields"
                    disabled={!hasTemplateParams}
                  >
                    Autofill
                  </button>
                  <button
                    onClick={() => setParamValues(Array.from({ length: expectedParams || 0 }, () => ""))}
                    style={btn("outline")}
                    title="Clear fields"
                    disabled={!hasTemplateParams}
                  >
                    Clear
                  </button>
                </div>
              </div>

              <div style={{ width: "100%" }}>
                <select
                  value={`${templateName}|${templateLangUI}`}
                  onChange={(e) => {
                    const [n, l] = e.target.value.split("|");
                    setTemplateName(n);
                    setTemplateLangUI(l);
                    setTimeout(() => refreshWindow(true), 0);
                  }}
                  style={{
                    width: "100%",
                    background: C.bg,
                    color: C.text,
                    border: `1px solid ${C.border}`,
                    borderRadius: 10,
                    padding: "10px 12px",
                    fontSize: 13,
                  }}
                  disabled={templatesLoading}
                >
                  {!templates.find((t) => t.name === templateName && t.languageUI === templateLangUI) && templateName && (
                    <option value={`${templateName}|${templateLangUI}`}>
                      {templateName} ({templateLangUI})
                    </option>
                  )}
                  {templates.map((t) => (
                    <option key={`${t.name}-${t.languageUI}`} value={`${t.name}|${t.languageUI}`}>
                      {t.name} ({t.languageUI}) {t.status === "APPROVED" ? "✓" : "•"}
                    </option>
                  ))}
                </select>
              </div>

              {templatesLoading && (
                <div style={{ width: "100%", color: C.sub, fontSize: 12 }}>Loading templates...</div>
              )}

              {!!templatesError && (
                <div style={{ width: "100%", color: C.danger, fontSize: 12 }}>{templatesError}</div>
              )}

              {!templatesLoading && !templates.length && (
                <div style={{ width: "100%", color: C.sub, fontSize: 12 }}>
                  No templates available yet. Create and approve one in Meta first.
                </div>
              )}

              {!gate.templateApproved && templateName && (
                <div style={{ width: "100%", color: C.danger, fontSize: 12, fontWeight: 700 }}>
                  This template is not approved for sending right now.
                </div>
              )}

              {templateInfoLoading && (
                <div style={{ width: "100%", color: C.sub, fontSize: 12 }}>Loading template details...</div>
              )}

              {!!templateInfoError && (
                <div style={{ width: "100%", color: C.danger, fontSize: 12 }}>{templateInfoError}</div>
              )}

              {!!templateBodyText && (
                <div
                  style={{
                    width: "100%",
                    background: C.bg,
                    border: `1px solid ${C.border}`,
                    borderRadius: 10,
                    padding: "10px 12px",
                    marginTop: 2,
                  }}
                >
                  <div style={{ color: C.sub, fontSize: 11, marginBottom: 6, fontWeight: 700 }}>
                    Template message
                  </div>
                  <div style={{ color: C.text, fontSize: 13, lineHeight: 1.45, whiteSpace: "pre-wrap" }}>
                    {templateBodyText}
                  </div>
                </div>
              )}

              {hasTemplateParams && (
                <>
                  <div style={{ width: "100%", color: C.text, fontSize: 13, fontWeight: 800, marginTop: 4 }}>
                    Fill the required fields
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 8,
                      width: "100%",
                      marginTop: 2,
                    }}
                  >
                    {Array.from({ length: expectedParams }).map((_, i) => (
                      <div key={i} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <label style={{ fontSize: 12, color: C.sub, fontWeight: 700 }}>
                          {friendlyLabelForKind(paramKinds?.[i], i)}
                        </label>
                        <input
                          value={paramValues?.[i] ?? ""}
                          onChange={(e) => {
                            const v = e.target.value;
                            setParamValues((prev) => {
                              const next = Array.from({ length: expectedParams }, (_, idx) => prev?.[idx] ?? "");
                              next[i] = v;
                              return next;
                            });
                          }}
                          placeholder={templateExample?.[i] ?? fieldHintForKind(paramKinds?.[i])}
                          style={{
                            background: C.bg,
                            color: C.text,
                            border: `1px solid ${C.border}`,
                            borderRadius: 10,
                            padding: "10px 12px",
                            fontSize: 13,
                            outline: "none",
                          }}
                        />
                      </div>
                    ))}
                  </div>

                  {!!templateBodyText && (
                    <div
                      style={{
                        width: "100%",
                        background: C.softer,
                        border: `1px solid ${C.border}`,
                        borderRadius: 10,
                        padding: "10px 12px",
                        marginTop: 4,
                      }}
                    >
                      <div style={{ color: C.sub, fontSize: 11, marginBottom: 6, fontWeight: 700 }}>
                        What the lead will receive
                      </div>
                      <div style={{ color: C.text, fontSize: 13, lineHeight: 1.45, whiteSpace: "pre-wrap" }}>
                        {templatePreview}
                      </div>
                    </div>
                  )}
                </>
              )}

              {!templateInfoLoading && !hasTemplateParams && !!templateName && !!templateBodyText && (
                <div style={{ width: "100%", color: C.sub, fontSize: 12 }}>
                  This template does not need extra fields.
                </div>
              )}
            </div>
          )}

          {/* Automation sends panel */}
          {showAutoLog && (
            <div
              style={{
                padding: "8px 12px",
                borderBottom: `1px solid ${C.border}`,
                background: C.soft,
                maxHeight: 160,
                overflowY: "auto",
              }}
            >
              {autoLog.length === 0 ? (
                <div style={{ color: C.sub, fontSize: 12 }}>No automation messages yet for this lead.</div>
              ) : (
                autoLog
                  .slice()
                  .reverse()
                  .map((it, idx) => (
                    <div
                      key={idx}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "90px 1fr",
                        gap: 10,
                        padding: "6px 0",
                        borderBottom: idx === autoLog.length - 1 ? "0" : `1px dashed ${C.border}`,
                      }}
                    >
                      <div style={{ color: C.sub, fontSize: 12 }}>
                        {it.channel?.toUpperCase() || "AUTO"} ·{" "}
                        {new Date(it.created_at || Date.now()).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </div>
                      <div style={{ color: C.text, fontSize: 13, whiteSpace: "pre-wrap" }}>
                        {htmlToText(it.text || it.subject || it.html || "")}
                      </div>
                    </div>
                  ))
              )}
            </div>
          )}

          {/* Appointment suggestion banner */}
          {suggestion && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 12px",
                borderBottom: `1px solid ${C.border}`,
                background: C.soft,
                flexWrap: "wrap",
              }}
            >
              <span style={{ color: C.accent, fontWeight: 900 }}>Suggested appointment</span>
              <span style={{ color: C.text, fontWeight: 800 }}>
                {new Date(`${suggestion.date}T${suggestion.time}:00`).toLocaleString([], {
                  weekday: "short",
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <button style={btn("primary")} onClick={onConfirmSuggestion}>
                  Add to Calendar
                </button>
                <button
                  style={btn("ghost")}
                  onClick={() => {
                    markConsumed(suggestion);
                    setSuggestion(null);
                  }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}

          {/* Thread */}
          <div
            ref={chatRef}
            style={{
              overflowY: "auto",
              padding: "14px 16px",
              backgroundImage:
                "radial-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), radial-gradient(rgba(255,255,255,0.02) 1px, transparent 1px)",
              backgroundSize: "24px 24px, 48px 48px",
              backgroundPosition: "0 0, 12px 12px",
              paddingBottom: 110,
            }}
          >
            {thread.length === 0 && (
              <div style={{ textAlign: "center", color: C.sub, marginTop: 8 }}>
                No messages yet. Say hello 👋
              </div>
            )}
            {thread.map((m, i) => (
              <Bubble
                key={i}
                from={m.from}
                text={m.text}
                time={m.time}
                renderedTemplate={m._rendered_template}
              />
            ))}
          </div>

          {/* Composer */}
          <div style={{ background: C.panel, borderTop: `1px solid ${C.border}` }}>
            {banner && (
              <div
                style={{
                  padding: "6px 10px",
                  fontSize: 12,
                  color: "#d2b48c",
                  background: "#3a2a18",
                  borderBottom: `1px solid ${C.border}`,
                }}
              >
                {banner}
              </div>
            )}

            <div style={{ padding: 10 }}>
              {!gate.inside24h && hasTemplateParams && (
                <div
                  style={{
                    marginBottom: 10,
                    color: C.sub,
                    fontSize: 12,
                    lineHeight: 1.4,
                  }}
                >
                  The box below is optional while using a template. It helps AI Reply and autofill.
                </div>
              )}

              <div style={{ display: "flex", gap: 10 }}>
                <textarea
                  rows={3}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder={
                    !toE164
                      ? "No WhatsApp number on this lead"
                      : gate.inside24h
                      ? "Type a message... (Ctrl/⌘ + Enter to send)"
                      : hasTemplateParams
                      ? "Optional notes for AI reply or autofill..."
                      : "Outside 24h — choose an approved template above"
                  }
                  style={{
                    flex: 1,
                    resize: "none",
                    background: C.bg,
                    color: C.text,
                    border: `1px solid ${C.border}`,
                    borderRadius: 12,
                    padding: "12px 14px",
                    fontSize: 15,
                    outline: "none",
                    boxSizing: "border-box",
                  }}
                  disabled={!canSendBase}
                  maxLength={2000}
                />

                <button
                  onClick={onDraftAI}
                  disabled={!canSendBase}
                  style={btn("ghost", !canSendBase)}
                  title="Draft from the live conversation"
                >
                  AI Reply
                </button>

                <button
                  onClick={onSend}
                  disabled={!canSendBase || loading || (!gate.inside24h && !templateName)}
                  style={btn("primary", !canSendBase || loading || (!gate.inside24h && !templateName))}
                  title="Send (Ctrl/⌘ + Enter)"
                >
                  {loading ? "Sending..." : "Send"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** ===== small UI atoms ===== */
function Header() {
  return (
    <div
      style={{
        padding: "0 0 18px 0",
        borderBottom: `1px solid ${C.border}`,
        marginBottom: 18,
      }}
    >
      <h2
        style={{
          color: C.text,
          fontWeight: 900,
          margin: 0,
          letterSpacing: "-0.5px",
          fontSize: 28,
        }}
      >
        Messages
      </h2>
    </div>
  );
}

function Pill({ color, text }) {
  return (
    <span
      style={{
        background: "transparent",
        color,
        border: `1px solid ${color}`,
        padding: "6px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 800,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </span>
  );
}

function btn(kind, disabled = false) {
  const base = {
    minWidth: 120,
    borderRadius: 999,
    padding: "12px 18px",
    fontWeight: 900,
    cursor: disabled ? "not-allowed" : "pointer",
  };

  if (kind === "primary") {
    return {
      ...base,
      border: 0,
      background: C.accent,
      color: "#1a1a1a",
      opacity: disabled ? 0.7 : 1,
    };
  }

  if (kind === "outline") {
    return {
      ...base,
      background: "transparent",
      color: C.accent,
      border: `2px solid ${C.accent}`,
      opacity: disabled ? 0.7 : 1,
    };
  }

  return {
    ...base,
    border: 0,
    background: C.mutedBlue,
    color: C.text,
    opacity: disabled ? 0.7 : 1,
  };
}

function Bubble({ from, text, time, renderedTemplate }) {
  const you = from === "user";
  const safe = cleanAIText(text);

  if (!safe) return null;

  return (
    <div
      style={{
        display: "flex",
        justifyContent: you ? "flex-end" : "flex-start",
        marginBottom: 8,
      }}
    >
      <div
        style={{
          maxWidth: "88%",
          background: you ? C.out : C.in,
          color: C.text,
          border: `1px solid ${C.border}`,
          borderRadius: you ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
          padding: "10px 12px",
          boxShadow: "0 1px 1px rgba(0,0,0,0.25)",
        }}
      >
        {renderedTemplate && (
          <div
            style={{
              fontSize: 11,
              fontWeight: 800,
              color: "#b6d7c8",
              marginBottom: 5,
              textTransform: "uppercase",
              letterSpacing: 0.3,
            }}
          >
            Template message
          </div>
        )}
        <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 15 }}>{safe}</div>
        <div style={{ fontSize: 11, color: C.sub, textAlign: "right", marginTop: 6 }}>
          {time
            ? new Date(time).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })
            : ""}
        </div>
      </div>
    </div>
  );
}