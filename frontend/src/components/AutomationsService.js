// frontend/src/components/AutomationsService.js
import { apiUrl } from "../apiBase";

const ROOT = apiUrl("automations/");

async function request(path = "", { method = "GET", body, userEmail, query } = {}) {
  const suffix = path ? String(path).replace(/^\/+/, "") : "";
  const params = new URLSearchParams();
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });
  const url = `${ROOT}${suffix}${params.toString() ? `?${params}` : ""}`;

  const response = await fetch(url, {
    method,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(userEmail
        ? { "X-User-Email": String(userEmail).trim().toLowerCase() }
        : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const contentType = (response.headers.get("content-type") || "").toLowerCase();
  let data = {};
  try {
    data = contentType.includes("application/json")
      ? await response.json()
      : { message: await response.text() };
  } catch {
    data = {};
  }

  if (!response.ok) {
    const validation = Array.isArray(data?.validation_errors)
      ? ` ${data.validation_errors.join(" ")}`
      : "";
    const error = new Error(
      `${data?.error || data?.message || `${response.status} ${response.statusText}`}${validation}`.trim()
    );
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data || {};
}

function dispatchAutomationSent(items = []) {
  if (!Array.isArray(items) || !items.length) return;
  const normalized = items
    .filter((item) => item?.status === "sent")
    .map((item) => {
      const info = item.info || {};
      const type = item.type || "";
      return {
        id: `automation_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        channel: type.includes("whatsapp") ? "whatsapp" : "email",
        status: item.status,
        to: info.to || "",
        text: info.text || info.message || "",
        subject: info.subject || "",
        created_at: new Date().toISOString(),
      };
    });

  if (!normalized.length) return;
  try {
    window.dispatchEvent(
      new CustomEvent("app:message-sent", {
        detail: { source: "automations", items: normalized },
      })
    );
  } catch {}
}

const api = {
  getHealth(userEmail) {
    return request("health", { userEmail });
  },

  getDashboard(userEmail) {
    return request("dashboard", { userEmail });
  },

  getTemplates(userEmail) {
    return request("templates", { userEmail });
  },

  getProfile(userEmail) {
    return request("user/profile", { userEmail });
  },

  saveProfile(userEmail, profile) {
    return request("user/profile", {
      method: "POST",
      userEmail,
      body: profile,
    });
  },

  listFlows(userEmail) {
    return request("", { userEmail });
  },

  createFlow(userEmail, flow) {
    return request("", {
      method: "POST",
      userEmail,
      body: { flow },
    });
  },

  updateFlow(userEmail, flowId, flow) {
    return request(encodeURIComponent(flowId), {
      method: "PUT",
      userEmail,
      body: { flow },
    });
  },

  deleteFlow(userEmail, flowId) {
    return request(encodeURIComponent(flowId), {
      method: "DELETE",
      userEmail,
    });
  },

  enableFlow(userEmail, flowId, enabled) {
    return request(`enable/${encodeURIComponent(flowId)}`, {
      method: "POST",
      userEmail,
      body: { enabled },
    });
  },

  listLeads(userEmail) {
    return request("leads", { userEmail });
  },

  getHistory(userEmail, options = {}) {
    return request("history", {
      userEmail,
      query: {
        limit: options.limit || 100,
        flow_id: options.flowId || "",
        status: options.status || "",
      },
    });
  },

  retryRun(userEmail, flowId, leadId) {
    return request(`history/${encodeURIComponent(flowId)}/${encodeURIComponent(leadId)}/retry`, {
      method: "POST", userEmail, body: {},
    });
  },

  getWATemplates(userEmail) {
    return request("wa/templates", { userEmail });
  },

  preview(userEmail, flowOrId, lead) {
    return request("test", {
      method: "POST",
      userEmail,
      body: {
        mode: "dryrun",
        lead_email: lead?.email || "",
        lead_id: lead?.id || "",
        ...(typeof flowOrId === "object"
          ? { flow: flowOrId }
          : { flow_id: String(flowOrId || "") }),
      },
    });
  },

  async runLiveTest(userEmail, flowOrId, lead) {
    const data = await request("test-live", {
      method: "POST",
      userEmail,
      body: {
        confirm_live: true,
        ignore_waits: true,
        ignore_quiet_hours: true,
        bypass_rate_limits: true,
        lead_email: lead?.email || "",
        lead_id: lead?.id || "",
        ...(typeof flowOrId === "object"
          ? { flow: flowOrId }
          : { flow_id: String(flowOrId || "") }),
      },
    });
    dispatchAutomationSent(data?.did || []);
    return data;
  },


  // Backward-compatible names used by the current Automations.jsx.
  dryRun(userEmail, flowOrId, opts = {}) {
    const lead = {
      email: opts.lead_email || opts.leadEmail || "",
      id: opts.lead_id || opts.leadId || "",
    };
    return api.preview(userEmail, flowOrId, lead);
  },

  executeNow(userEmail, flowOrId, opts = {}) {
    const lead = {
      email: opts.lead_email || opts.leadEmail || "",
      id: opts.lead_id || opts.leadId || "",
    };
    return api.runLiveTest(userEmail, flowOrId, lead);
  },

  runEngineOnce(userEmail) {
    return request("run", { method: "POST", userEmail, body: {} });
  },
};

export default api;
