// File: frontend/src/components/Settings.jsx
import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import GoogleCalendarEvents from "./GoogleCalendarEvents";
import StripeConnectCard from "./StripeConnectCard";
import WhatsAppHealthCard from "./WhatsAppHealthCard";
import TwoFactorSettings from "./TwoFactorSettings";
import ImportContacts from "./ImportContacts";
import {
  FaUser,
  FaPlug,
  FaQuestionCircle,
  FaUsers,
  FaSearch,
  FaTrash,
  FaUserPlus,
  FaSyncAlt,
  FaCopy,
  FaTimes,
  FaClock,
  FaCrown,
  FaCheckCircle,
  FaEnvelope,
  FaLifeRing,
  FaCreditCard,
  FaRobot,
  FaShieldAlt,
  FaArrowRight,
  FaExternalLinkAlt,
  FaFileImport,
} from "react-icons/fa";
import { SiInstagram } from "react-icons/si";
import "./settings.css";

import { apiUrl } from "../apiBase";

/* ------------------------------------------------------------
   Settings (PROD-SAFE)
   - Profile loads from:
       1) props.user
       2) backend GET /api/profile?email=...
       3) localStorage fallback
   - Save uses POST /api/profile
   - Auto-refreshes profile/integrations:
       * on load/login
       * every 1 hour while mounted and user is logged in
------------------------------------------------------------ */

const TABS = [
  { key: "profile", label: "Profile", icon: <FaUser /> },
  { key: "team", label: "Team", icon: <FaUsers /> },
  { key: "integrations", label: "Integrations", icon: <FaPlug /> },
  { key: "imports", label: "Import Contacts", icon: <FaFileImport /> },
  { key: "billing", label: "Billing", icon: <FaCreditCard /> },
  { key: "notifications", label: "Notifications", icon: <FaEnvelope /> },
  { key: "security", label: "Security", icon: <FaShieldAlt /> },
  { key: "account", label: "Data & Account", icon: <FaTrash /> },
  { key: "help", label: "Help & Support", icon: <FaQuestionCircle /> },
];

const PROFILE_REFRESH_MS = 60 * 60 * 1000; // 1 hour

function safeParse(json) {
  try {
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function normalizeUser(u) {
  if (!u || typeof u !== "object") return null;

  const people =
    u.people !== undefined && u.people !== null && u.people !== ""
      ? u.people
      : u.teamSize ?? "";

  const teamSize =
    u.teamSize !== undefined && u.teamSize !== null && u.teamSize !== ""
      ? u.teamSize
      : u.people ?? "";

  return {
    ...u,
    email: u.email || "",
    name: u.name || "",
    logo: u.logo || "",
    business: u.business || u.businessName || "",
    businessName: u.businessName || u.business || "",
    businessType: u.businessType || u.lineOfBusiness || "",
    lineOfBusiness: u.lineOfBusiness || u.businessType || "",
    location: u.location || "",
    people,
    teamSize,
    stripe_connected: Boolean(u.stripe_connected),
    stripe_account_id: u.stripe_account_id || "",
    gcal_connected: Boolean(u.gcal_connected),
    gcal_calendars: Array.isArray(u.gcal_calendars) ? u.gcal_calendars : [],
    role: u.role || "",
    orgOwnerEmail: u.orgOwnerEmail || "",
    canInviteTeam: Boolean(u.canInviteTeam),
    canEditBusiness: Boolean(u.canEditBusiness),
    canManageBilling: Boolean(u.canManageBilling),
  };
}

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, {
    credentials: "include",
    ...opts,
    headers: {
      Accept: "application/json",
      ...(opts.headers || {}),
    },
  });

  const ct = (res.headers.get("content-type") || "").toLowerCase();
  const raw = await res.text();

  if (!res.ok) {
    const err = new Error(
      `HTTP ${res.status} ${res.statusText} @ ${url}\n${raw.slice(0, 300)}`
    );
    err.status = res.status;
    err.raw = raw;
    throw err;
  }

  if (ct.includes("application/json")) {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  return raw;
}

async function postJson(path, payload) {
  const url = apiUrl(path);
  return fetchJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export default function Settings({
  user,
  sidebarCollapsed,
  googleEvents,
  setGoogleEvents,
  gcalStatus,
  setGcalStatus,
  initialTab,
  refreshUser,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const { search } = location;

  const [tab, setTab] = useState(initialTab || "profile");

  const [profile, setProfile] = useState(() => {
    const fromProps = normalizeUser(user);
    if (fromProps?.email) return fromProps;

    const stored = safeParse(localStorage.getItem("user") || "");
    return normalizeUser(stored);
  });

  const [form, setForm] = useState(() => ({
    name: profile?.name || "",
    email: profile?.email || "",
    business: profile?.business || profile?.businessName || "",
    type: profile?.businessType || profile?.lineOfBusiness || "",
    location: profile?.location || "",
    teamSize: String(profile?.people ?? profile?.teamSize ?? ""),
  }));

  const [editMode, setEditMode] = useState(false);
  const editModeRef = useRef(false);
  const formDirtyRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [info, setInfo] = useState("");
  const [profileBackendOk, setProfileBackendOk] = useState(null);
  const [supportCopied, setSupportCopied] = useState(false);
  const [billingUsage, setBillingUsage] = useState(null);

  useEffect(() => {
    editModeRef.current = editMode;
  }, [editMode]);
  const [notificationPrefs, setNotificationPrefs] = useState(() => {
    const saved = safeParse(localStorage.getItem("retainai:notification-preferences") || "");
    return {
      actionDigest: saved?.actionDigest !== false,
      automationFailures: saved?.automationFailures !== false,
      appointmentAlerts: saved?.appointmentAlerts !== false,
      weeklyReport: saved?.weeklyReport !== false,
    };
  });

  const updateNotificationPref = useCallback((key) => {
    setNotificationPrefs((current) => {
      const next = { ...current, [key]: !current[key] };
      try {
        localStorage.setItem("retainai:notification-preferences", JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);

  useEffect(() => {
    if (initialTab && TABS.some((t) => t.key === initialTab)) {
      setTab(initialTab);
    }
  }, [initialTab]);

  useEffect(() => {
    if (tab !== "billing") return;
    fetchJson(apiUrl("billing/usage")).then(setBillingUsage).catch(() => setBillingUsage(null));
  }, [tab]);

  useEffect(() => {
    const next = normalizeUser(user);
    if (!next?.email) return;

    setProfile((prev) => {
      if (!prev) return next;

      const changed =
        prev.email !== next.email ||
        prev.name !== next.name ||
        prev.logo !== next.logo ||
        prev.business !== next.business ||
        prev.businessType !== next.businessType ||
        prev.location !== next.location ||
        String(prev.people ?? "") !== String(next.people ?? "") ||
        Boolean(prev.stripe_connected) !== Boolean(next.stripe_connected) ||
        String(prev.stripe_account_id || "") !==
          String(next.stripe_account_id || "") ||
        Boolean(prev.gcal_connected) !== Boolean(next.gcal_connected) ||
        String(prev.role || "") !== String(next.role || "") ||
        String(prev.orgOwnerEmail || "") !== String(next.orgOwnerEmail || "");

      return changed ? next : prev;
    });

    if (!editModeRef.current && !formDirtyRef.current) {
      setForm({
        name: next.name || "",
        email: next.email || "",
        business: next.business || next.businessName || "",
        type: next.businessType || next.lineOfBusiness || "",
        location: next.location || "",
        teamSize: String(next.people ?? next.teamSize ?? ""),
      });
    }

    try {
      localStorage.setItem("user", JSON.stringify(next));
    } catch {}

    setInfo("");
  }, [user]);

  const tryFetchProfileFromBackend = useCallback(async (email) => {
    if (!email) return null;

    const url = apiUrl(`profile?email=${encodeURIComponent(email)}`);

    try {
      const data = await fetchJson(url);
      const maybeProfile =
        data?.profile && typeof data.profile === "object" ? data.profile : data;

      const normalized = normalizeUser(maybeProfile);

      if (normalized?.email) {
        setProfileBackendOk(true);
        return normalized;
      }

      setProfileBackendOk(true);
      return null;
    } catch {
      setProfileBackendOk(false);
      return null;
    }
  }, []);

  const syncProfileFromBackend = useCallback(
    async (email) => {
      const fromBackend = await tryFetchProfileFromBackend(email);
      if (!fromBackend?.email) return null;

      setProfile(fromBackend);
      if (!editModeRef.current && !formDirtyRef.current) {
        setForm({
          name: fromBackend.name || "",
          email: fromBackend.email || "",
          business: fromBackend.business || fromBackend.businessName || "",
          type: fromBackend.businessType || fromBackend.lineOfBusiness || "",
          location: fromBackend.location || "",
          teamSize: String(fromBackend.people ?? fromBackend.teamSize ?? ""),
        });
      }

      try {
        localStorage.setItem("user", JSON.stringify(fromBackend));
      } catch {}

      return fromBackend;
    },
    [tryFetchProfileFromBackend]
  );

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const email = profile?.email;
      if (!email) return;

      const fromBackend = await tryFetchProfileFromBackend(email);
      if (cancelled) return;

      if (fromBackend?.email) {
        setProfile(fromBackend);
        if (!editModeRef.current && !formDirtyRef.current) {
          setForm({
            name: fromBackend.name || "",
            email: fromBackend.email || "",
            business: fromBackend.business || fromBackend.businessName || "",
            type: fromBackend.businessType || fromBackend.lineOfBusiness || "",
            location: fromBackend.location || "",
            teamSize: String(fromBackend.people ?? fromBackend.teamSize ?? ""),
          });
        }

        try {
          localStorage.setItem("user", JSON.stringify(fromBackend));
        } catch {}
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [profile?.email, tryFetchProfileFromBackend]);

  useEffect(() => {
    if (!profile?.email) return;

    let cancelled = false;

    const runRefresh = async () => {
      try {
        if (typeof refreshUser === "function") {
          await refreshUser();
        }
      } catch {}

      try {
        const fresh = await syncProfileFromBackend(profile.email);
        if (cancelled) return;

        if (fresh?.email) {
          setInfo("");
        }
      } catch {
        if (!cancelled) {
          setProfileBackendOk(false);
        }
      }
    };

    runRefresh();
    const timer = setInterval(runRefresh, PROFILE_REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [profile?.email, refreshUser, syncProfileFromBackend]);

  useEffect(() => {
    const params = new URLSearchParams(search);
    const stripeConnected = params.get("stripe_connected") === "1";
    const stripeRefresh = params.get("stripe_refresh") === "1";
    const stripeError = params.get("stripe_error") === "1";
    const stripeErrorDesc = params.get("stripe_error_desc");

    if (!(stripeConnected || stripeRefresh || stripeError)) return;

    const email = profile?.email || user?.email;

    (async () => {
      if (stripeError) {
        setInfo(
          stripeErrorDesc
            ? decodeURIComponent(stripeErrorDesc)
            : "Stripe connection failed."
        );
      } else if (email) {
        try {
          if (typeof refreshUser === "function") {
            await refreshUser();
          }
        } catch {}

        try {
          await syncProfileFromBackend(email);
        } catch {}

        if (stripeConnected) {
          setInfo("Stripe connected ✅");
        } else if (stripeRefresh) {
          setInfo("Stripe onboarding refreshed.");
        }
      }

      params.delete("stripe_connected");
      params.delete("stripe_refresh");
      params.delete("stripe_error");
      params.delete("stripe_error_desc");

      navigate(
        {
          pathname: location.pathname,
          search: params.toString(),
        },
        { replace: true }
      );
    })();
  }, [
    search,
    profile?.email,
    user?.email,
    refreshUser,
    syncProfileFromBackend,
    navigate,
    location.pathname,
  ]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setInfo("");

    const payload = {
      email: form.email,
      name: form.name,
      logo: profile?.logo || "",
      business: form.business,
      businessName: form.business,
      businessType: form.type,
      lineOfBusiness: form.type,
      location: form.location,
      people: form.teamSize,
      teamSize: form.teamSize,
      stripe_connected: profile?.stripe_connected || false,
      stripe_account_id: profile?.stripe_account_id || "",
    };

    const merged = normalizeUser({ ...(profile || {}), ...payload });
    setProfile(merged);

    try {
      localStorage.setItem("user", JSON.stringify(merged));
    } catch {}

    try {
      await postJson("profile", payload);
      setProfileBackendOk(true);
      setInfo("Saved ✅");
      formDirtyRef.current = false;
      setEditMode(false);

      if (typeof refreshUser === "function") {
        try {
          await refreshUser();
        } catch {}
      }

      await syncProfileFromBackend(form.email);
    } catch (e) {
      setProfileBackendOk(false);
      console.warn("Profile save failed (backend). Using localStorage only.", e);
      setInfo("Saved locally ✅ (backend profile endpoint unavailable)");
      formDirtyRef.current = false;
      setEditMode(false);
    } finally {
      setSaving(false);
    }
  }, [form, profile, refreshUser, syncProfileFromBackend]);

  const supportEmail = "owner@retainai.ca";
  const supportMailto = useMemo(() => {
    const business = profile?.business || profile?.businessName || "";
    const subject = business
      ? `RetainAI support request — ${business}`
      : "RetainAI support request";
    const body = [
      "Hi RetainAI Support,",
      "",
      "I need help with:",
      "",
      "What I expected to happen:",
      "",
      "What actually happened:",
      "",
      `Account email: ${profile?.email || ""}`,
      `Business: ${business || "Not provided"}`,
      `Account role: ${profile?.role || "Not available"}`,
      "Browser / device:",
      "",
      "I have attached a screenshot if relevant.",
    ].join("\n");

    return `mailto:${supportEmail}?subject=${encodeURIComponent(
      subject
    )}&body=${encodeURIComponent(body)}`;
  }, [profile?.business, profile?.businessName, profile?.email, profile?.role]);

  const supportTopicMailto = useCallback(
    (topic) => {
      const business = profile?.business || profile?.businessName || "";
      const subject = `RetainAI support — ${topic}`;
      const body = [
        "Hi RetainAI Support,",
        "",
        `I need help with ${topic.toLowerCase()}:`,
        "",
        "Details:",
        "",
        `Account email: ${profile?.email || ""}`,
        `Business: ${business || "Not provided"}`,
      ].join("\n");

      return `mailto:${supportEmail}?subject=${encodeURIComponent(
        subject
      )}&body=${encodeURIComponent(body)}`;
    },
    [profile?.business, profile?.businessName, profile?.email]
  );

  const copySupportEmail = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(supportEmail);
      setSupportCopied(true);
      window.setTimeout(() => setSupportCopied(false), 1800);
    } catch {
      window.prompt("Copy this support email:", supportEmail);
    }
  }, []);

  const openSubscriptionBilling = async () => {
    setInfo("Opening secure billing…");
    try {
      const endpoint = profile?.hasBillingProfile
        ? "billing/portal"
        : "billing/checkout";
      const response = await fetch(apiUrl(endpoint), {
        method: "POST",
        credentials: "include",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.url) {
        throw new Error(data.error || "Billing is unavailable.");
      }
      window.location.assign(data.url);
    } catch (error) {
      setInfo(error.message || "Billing is unavailable.");
    }
  };

  const downloadWorkspaceData = async () => {
    setInfo("Preparing your workspace export…");
    try {
      const response = await fetch(apiUrl("account/export"), { credentials: "include" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Workspace export is unavailable.");
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = "retainai-workspace-export.json";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(href);
      setInfo("Workspace export downloaded. Credentials and access tokens were excluded.");
    } catch (error) {
      setInfo(error.message || "Workspace export is unavailable.");
    }
  };

  const scheduleAccountDeletion = async () => {
    const confirmation = window.prompt(
      `Schedule this workspace for deletion in 14 days? Type ${profile.email} to confirm.`
    );
    if (confirmation !== profile.email) return;
    try {
      const data = await postJson("account/deletion", {
        action: "schedule",
        confirmation,
      });
      setInfo(
        `Deletion scheduled for ${new Date(data.deletion_scheduled_for).toLocaleString()}. Contact support or use the owner console to cancel.`
      );
      if (typeof refreshUser === "function") refreshUser();
    } catch (error) {
      setInfo(error.message || "Could not schedule account deletion.");
    }
  };

  const cancelAccountDeletion = async () => {
    try {
      await postJson("account/deletion", { action: "cancel" });
      setInfo("Scheduled deletion cancelled. Your workspace will remain active.");
      if (typeof refreshUser === "function") await refreshUser();
      await syncProfileFromBackend(profile.email);
    } catch (error) {
      setInfo(error.message || "Could not cancel scheduled deletion.");
    }
  };

  const deleteAccountNow = async () => {
    const phrase = `DELETE ${profile.email}`;
    const confirmation = window.prompt(
      `This permanently deletes the workspace, team access, contacts, messages, appointments, automations, and account data. This cannot be undone.\n\nType ${phrase} to continue.`
    );
    if (confirmation !== phrase) return;
    if (!window.confirm("Final confirmation: permanently delete this RetainAI workspace now?")) {
      return;
    }
    setInfo("Cancelling billing and securely deleting the workspace…");
    try {
      const response = await fetch(apiUrl("account/deletion"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ action: "delete_now", confirmation }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          data.message ||
          (data.error === "billing_cancellation_failed"
            ? "Billing could not be cancelled safely. Open the billing portal or contact support before deleting."
            : data.error) ||
          "The workspace could not be deleted."
        );
      }
      localStorage.clear();
      window.location.assign("/login?account=deleted");
    } catch (error) {
      setInfo(error.message || "The workspace could not be deleted.");
    }
  };

  const MAX_W = 1120;

  if (!profile?.email) {
    return (
      <div
        className="settings-layout"
      >
        <div style={{ padding: 16, maxWidth: 900 }}>
          <div style={{ fontWeight: 900, marginBottom: 8, color: "#fff" }}>
            Settings couldn’t identify your account
          </div>
          <div style={{ color: "#bbb", lineHeight: 1.5 }}>
            Your session user is missing an email. Log out and log back in.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="settings-layout"
    >
      <nav className="settings-nav">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={tab === t.key ? "active" : ""}
            aria-label={t.label}
            aria-current={tab === t.key ? "page" : undefined}
            title={t.label}
            onClick={() => {
              setTab(t.key);
              setEditMode(false);
              formDirtyRef.current = false;
              setInfo("");
            }}
          >
            <span className="settings-icon">{t.icon}</span>
            <span className="settings-label">{t.label}</span>
          </button>
        ))}
      </nav>

      <main className="settings-content fade-in">
        {tab === "profile" && (
          <div
            className="profile-tab"
            style={{ maxWidth: MAX_W, margin: "0 auto" }}
          >
            <h2>Profile</h2>

            {(info || profileBackendOk === false) && (
              <div
                style={{
                  marginBottom: 12,
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: "1px solid #2f2f33",
                  background: "#1f1f23",
                  color: "#ddd",
                  fontWeight: 700,
                }}
              >
                {info ||
                  "Backend profile endpoint unavailable — using local profile cache."}
              </div>
            )}

            <div className="profile-card">
              <div className="avatar">
                {profile.logo ? (
                  <img src={profile.logo} alt="logo" />
                ) : (
                  profile.name?.[0]?.toUpperCase() || "?"
                )}
              </div>

              <div className="profile-fields">
                {[
                  { label: "Name", name: "name" },
                  { label: "Email", name: "email" },
                  { label: "Business", name: "business" },
                  { label: "Type", name: "type" },
                  { label: "Location", name: "location" },
                  { label: "Team Size", name: "teamSize" },
                ].map(({ label, name }) => (
                  <div key={name} className="field-row">
                    <div className="field-label">{label}</div>
                    {editMode ? (
                      <input
                        className="field-input"
                        type="text"
                        value={form[name]}
                        onChange={(e) => {
                          formDirtyRef.current = true;
                          setForm((f) => ({ ...f, [name]: e.target.value }));
                        }}
                        disabled={name === "email"}
                      />
                    ) : (
                      <div className="field-value">{form[name] || "—"}</div>
                    )}
                  </div>
                ))}

                <div className="profile-actions">
                  {editMode ? (
                    <>
                      <button
                        className="btn btn-cancel"
                        onClick={() => {
                          setEditMode(false);
                          formDirtyRef.current = false;
                          setForm({
                            name: profile.name || "",
                            email: profile.email || "",
                            business:
                              profile.business || profile.businessName || "",
                            type:
                              profile.businessType ||
                              profile.lineOfBusiness ||
                              "",
                            location: profile.location || "",
                            teamSize: String(
                              profile.people ?? profile.teamSize ?? ""
                            ),
                          });
                          setInfo("");
                        }}
                        disabled={saving}
                      >
                        Cancel
                      </button>

                      <button
                        className="btn btn-save"
                        onClick={handleSave}
                        disabled={saving}
                      >
                        {saving ? "Saving…" : "Save"}
                      </button>
                    </>
                  ) : (
                    <button
                      className="btn btn-edit"
                      onClick={() => {
                        formDirtyRef.current = false;
                        setEditMode(true);
                      }}
                    >
                      Edit Profile
                    </button>
                  )}
                </div>

                <div
                  style={{
                    marginTop: 10,
                    color: "#8d8d93",
                    fontSize: 12,
                    lineHeight: 1.5,
                  }}
                >
                  Profile sync:{" "}
                  <b style={{ color: "#fff" }}>
                    {profileBackendOk === true
                      ? "Server"
                      : profileBackendOk === false
                      ? "Local cache"
                      : "Checking…"}
                  </b>
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === "team" && (
          <TeamTab
            ownerEmail={profile.orgOwnerEmail || profile.email}
            userEmail={profile.email}
            maxWidth={MAX_W}
            canManageTeam={profile.canInviteTeam}
            currentRole={profile.role}
          />
        )}

        {tab === "integrations" && (
          <div className="integrations-page" style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <div className="settings-page-heading">
              <div>
                <span className="settings-page-eyebrow">Workspace connections</span>
                <h2>Connected accounts</h2>
                <p>Connect the services RetainAI uses for scheduling, payments, and customer conversations.</p>
              </div>
              <div className="settings-page-security">
                <FaShieldAlt aria-hidden="true" />
                Secure account connections
              </div>
            </div>

            <div className="integration-overview">
              <div>
                <span>Google Calendar</span>
                <strong className={profile?.gcal_connected ? "ready" : "muted"}>
                  {profile?.gcal_connected ? "Connected" : "Optional"}
                </strong>
              </div>
              <div>
                <span>Stripe Payments</span>
                <strong className={profile?.stripe_connected ? "ready" : "muted"}>
                  {profile?.stripe_connected ? "Connected" : "Optional"}
                </strong>
              </div>
              <div>
                <span>Account access</span>
                <strong className="ready">Encrypted OAuth</strong>
              </div>
            </div>

            <div className="connected-accounts-grid">
              <GoogleCalendarEvents
                user={profile}
                onStatus={setGcalStatus}
                onEvents={setGoogleEvents}
              />

              <StripeConnectCard
                user={profile}
                refreshUser={async () => {
                  try {
                    if (typeof refreshUser === "function") await refreshUser();
                  } catch {}
                  try {
                    await syncProfileFromBackend(profile.email);
                  } catch {}
                }}
              />

              <WhatsAppHealthCard user={profile} />

              <article className="account-card account-card-coming-soon">
                <div className="account-card-top">
                  <div className="account-brand-icon instagram" aria-hidden="true">
                    <SiInstagram />
                  </div>
                  <span className="account-status-badge coming-soon">Coming soon</span>
                </div>
                <div className="account-card-copy">
                  <h3>Instagram</h3>
                  <p>Bring customer messages and lead activity into one RetainAI inbox.</p>
                </div>
                <div className="account-card-content">
                  <div className="account-detail-box">
                    Instagram messaging will appear here once the integration is ready for production.
                  </div>
                </div>
                <div className="account-card-actions">
                  <button className="account-secondary-btn" disabled>Not available yet</button>
                </div>
              </article>
            </div>

            <div className="integration-privacy-note">
              <FaShieldAlt aria-hidden="true" />
              <div>
                <strong>Your credentials stay private.</strong>
                <span>RetainAI uses secure provider authorization and never displays connected-account secrets on this page.</span>
              </div>
            </div>
          </div>
        )}

        {tab === "imports" && <ImportContacts user={user} focusGoogle />}

        {tab === "billing" && (
          <div className="integrations-page" style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <div className="settings-page-heading">
              <div>
                <span className="settings-page-eyebrow">Plans and payments</span>
                <h2>Billing</h2>
                <p>Manage your RetainAI subscription and the Stripe account used for customer invoices.</p>
              </div>
              <div className="settings-page-security"><FaShieldAlt /> Secure billing</div>
            </div>
            <div className="integration-overview">
              <div><span>Account status</span><strong className="ready">{profile?.status || "Active"}</strong></div>
              <div><span>Current plan</span><strong>{billingUsage?.plan || "Standard"}</strong></div>
              <div><span>Stripe invoicing</span><strong className={profile?.stripe_connected ? "ready" : "muted"}>{profile?.stripe_connected ? "Connected" : "Optional"}</strong></div>
            </div>
            <div className="owner-detail-grid" style={{ marginBottom: 18 }}>
              <div><span>Trial ends</span><strong>{billingUsage?.trial_ends_at ? new Date(billingUsage.trial_ends_at).toLocaleDateString() : "—"}</strong></div>
              <div><span>Next payment</span><strong>{billingUsage?.next_payment_at ? new Date(Number(billingUsage.next_payment_at) * 1000).toLocaleDateString() : "Shown in Stripe"}</strong></div>
              <div><span>WhatsApp messages</span><strong>{billingUsage?.whatsapp_messages || 0}</strong></div>
              <div><span>AI generations</span><strong>{billingUsage?.ai_generations || 0}</strong></div>
              <div><span>Active automations</span><strong>{billingUsage?.active_automations || 0}</strong></div>
              <div><span>Team seats</span><strong>{billingUsage?.team_seats || 1}</strong></div>
              <div><span>Contacts</span><strong>{billingUsage?.contacts || 0}</strong></div>
              <div><span>Invoices created</span><strong>{billingUsage?.invoices_created || 0}</strong></div>
            </div>
            <div className="connected-accounts-grid">
              <StripeConnectCard
                user={profile}
                refreshUser={async () => {
                  if (typeof refreshUser === "function") await refreshUser();
                  await syncProfileFromBackend(profile.email);
                }}
              />
              <article className="account-card">
                <div className="account-card-copy">
                  <h3>RetainAI subscription</h3>
                  <p>Your workspace remains protected by server-verified account and billing status.</p>
                </div>
                <div className="account-card-content">
                  <div className="account-detail-box">
                    {profile?.trialActive
                      ? `${profile.trialDaysRemaining || 0} days remain in your trial.`
                      : "Manage your plan, invoices, and payment method securely through Stripe."}
                  </div>
                </div>
                <div className="account-card-actions">
                  <button className="account-primary-btn" onClick={openSubscriptionBilling}>
                    {profile?.hasBillingProfile ? "Manage subscription" : "Choose a plan"}
                  </button>
                  <a className="account-primary-btn" href={supportTopicMailto("billing and subscription")}>Contact billing support</a>
                </div>
              </article>
            </div>
          </div>
        )}

        {tab === "notifications" && (
          <div className="integrations-page" style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <div className="settings-page-heading">
              <div>
                <span className="settings-page-eyebrow">Stay informed</span>
                <h2>Notifications</h2>
                <p>Choose which operational updates RetainAI should prioritize for this device.</p>
              </div>
            </div>
            <div className="connected-accounts-grid">
              {[
                ["actionDigest", "Daily action briefing", "A morning summary of at-risk customers, opportunities, and appointments."],
                ["automationFailures", "Automation failures", "Immediate notice when a customer workflow needs attention."],
                ["appointmentAlerts", "Appointment alerts", "Upcoming appointments, confirmations, and no-show risks."],
                ["weeklyReport", "Weekly business report", "A concise retention and relationship-health summary."],
              ].map(([key, title, copy]) => (
                <article className="account-card" key={key}>
                  <div className="account-card-copy"><h3>{title}</h3><p>{copy}</p></div>
                  <div className="account-card-actions">
                    <button className={notificationPrefs[key] ? "account-primary-btn" : "account-secondary-btn"} onClick={() => updateNotificationPref(key)}>
                      {notificationPrefs[key] ? "Enabled" : "Disabled"}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </div>
        )}

        {tab === "security" && (
          <div className="integrations-page" style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <div className="settings-page-heading">
              <div>
                <span className="settings-page-eyebrow">Account protection</span>
                <h2>Security</h2>
                <p>Your login is protected by a server-verified, encrypted HttpOnly session.</p>
              </div>
              <div className="settings-page-security"><FaShieldAlt /> Protected session</div>
            </div>
            <div className="integration-overview">
              <div><span>Signed in as</span><strong>{profile.email}</strong></div>
              <div><span>Workspace role</span><strong>{profile.role || "Owner"}</strong></div>
              <div><span>Session storage</span><strong className="ready">HttpOnly cookie</strong></div>
            </div>
            <div className="connected-accounts-grid">
              <TwoFactorSettings />
              <article className="account-card">
                <div className="account-card-copy"><h3>Password assistance</h3><p>Request a secure password reset through RetainAI support.</p></div>
                <div className="account-card-actions"><a className="account-primary-btn" href={supportTopicMailto("password reset")}>Request reset</a></div>
              </article>
              <article className="account-card">
                <div className="account-card-copy"><h3>Security recommendation</h3><p>Use a unique password and remove team members as soon as they no longer need workspace access.</p></div>
                <div className="account-card-content"><div className="account-detail-box">Sensitive integrations and platform-owner controls are verified by the backend, not by browser storage.</div></div>
              </article>
            </div>
          </div>
        )}

        {tab === "account" && (
          <div className="integrations-page" style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <div className="settings-page-heading">
              <div>
                <span className="settings-page-eyebrow">Ownership and privacy</span>
                <h2>Data & Account</h2>
                <p>Download your information, manage your subscription, or close your workspace without getting stuck.</p>
              </div>
              <div className="settings-page-security"><FaShieldAlt /> Owner protected</div>
            </div>
            <div className="integration-overview">
              <div><span>Workspace</span><strong>{profile.business || profile.email}</strong></div>
              <div><span>Account owner</span><strong>{profile.orgOwnerEmail || profile.email}</strong></div>
              <div>
                <span>Deletion status</span>
                <strong className={profile.deletion_scheduled_for ? "muted" : "ready"}>
                  {profile.deletion_scheduled_for ? "Scheduled" : "Not scheduled"}
                </strong>
              </div>
            </div>
            <div className="connected-accounts-grid">
              <article className="account-card">
                <div className="account-card-copy">
                  <h3>Download workspace data</h3>
                  <p>Export your profile, team, and contacts. Credentials and integration tokens are always excluded.</p>
                </div>
                <div className="account-card-actions">
                  <button className="account-primary-btn" onClick={downloadWorkspaceData}>Download export</button>
                </div>
              </article>
              <article className="account-card">
                <div className="account-card-copy">
                  <h3>Subscription and invoices</h3>
                  <p>Update your payment method, review invoices, change plans, or cancel billing through Stripe.</p>
                </div>
                <div className="account-card-actions">
                  <button className="account-primary-btn" onClick={openSubscriptionBilling}>
                    Open billing portal
                  </button>
                </div>
              </article>
              <article className="account-card">
                <div className="account-card-copy">
                  <h3>{profile.deletion_scheduled_for ? "Workspace deletion scheduled" : "Close workspace"}</h3>
                  <p>
                    {profile.deletion_scheduled_for
                      ? `Your recovery window ends ${new Date(profile.deletion_scheduled_for).toLocaleString()}.`
                      : "Schedule deletion with a 14-day recovery window. Your workspace stays accessible during that period."}
                  </p>
                </div>
                <div className="account-card-content">
                  <div className="account-detail-box">
                    Download your data and cancel billing first. Only the workspace owner can make this change.
                  </div>
                </div>
                <div className="account-card-actions">
                  {profile.deletion_scheduled_for ? (
                    <button className="account-primary-btn" onClick={cancelAccountDeletion}>Cancel deletion</button>
                  ) : (
                    <button className="account-secondary-btn" onClick={scheduleAccountDeletion}>Schedule deletion</button>
                  )}
                  <a className="account-secondary-btn" href={supportTopicMailto("account closure")}>Get help</a>
                </div>
              </article>
              <article className="account-card account-danger-card">
                <div className="account-card-copy">
                  <h3>Delete workspace now</h3>
                  <p>
                    Permanently remove the account and workspace immediately. RetainAI first attempts to cancel
                    any active subscription so the customer cannot be billed after deletion.
                  </p>
                </div>
                <div className="account-card-content">
                  <div className="account-detail-box">
                    This cannot be undone. Download the workspace export before continuing.
                  </div>
                </div>
                <div className="account-card-actions">
                  {profile.platformOwner ? (
                    <button className="account-secondary-btn" disabled>Platform owner account protected</button>
                  ) : (
                    <button className="account-danger-btn" onClick={deleteAccountNow}>Delete now</button>
                  )}
                </div>
              </article>
            </div>
          </div>
        )}

        {tab === "help" && (
          <div
            className="help-support-page fade-in"
            style={{ maxWidth: MAX_W, margin: "0 auto" }}
          >
            <section className="help-support-hero">
              <div className="help-support-hero-copy">
                <div className="help-eyebrow">
                  <FaLifeRing aria-hidden="true" />
                  RetainAI Support
                </div>
                <h2>How can we help?</h2>
                <p>
                  Get help with your account, team, billing, integrations,
                  messages, and automations. Your account details are included
                  automatically when you email support.
                </p>
              </div>

              <a className="help-primary-btn" href={supportMailto}>
                <FaEnvelope aria-hidden="true" />
                Email support
                <FaExternalLinkAlt
                  className="help-btn-trailing-icon"
                  aria-hidden="true"
                />
              </a>
            </section>

            <div className="help-overview-grid">
              <section className="help-panel help-contact-panel">
                <div className="help-panel-icon">
                  <FaEnvelope aria-hidden="true" />
                </div>
                <div className="help-panel-copy">
                  <div className="help-panel-kicker">Direct support</div>
                  <h3>Talk to the RetainAI team</h3>
                  <p>
                    Send us the issue, what you expected, and a screenshot when
                    possible. The email button prepares a useful support request
                    for you.
                  </p>

                  <div className="help-email-row">
                    <a href={`mailto:${supportEmail}`}>{supportEmail}</a>
                    <button
                      type="button"
                      className="help-copy-btn"
                      onClick={copySupportEmail}
                      aria-label="Copy support email"
                    >
                      {supportCopied ? (
                        <FaCheckCircle aria-hidden="true" />
                      ) : (
                        <FaCopy aria-hidden="true" />
                      )}
                      {supportCopied ? "Copied" : "Copy"}
                    </button>
                  </div>
                </div>
              </section>

              <aside className="help-panel help-account-panel">
                <div className="help-account-heading">
                  <div>
                    <div className="help-panel-kicker">Support profile</div>
                    <h3>Your account details</h3>
                  </div>
                  <span className="help-account-status">Active session</span>
                </div>

                <dl className="help-account-list">
                  <div>
                    <dt>Account email</dt>
                    <dd>{profile?.email || "—"}</dd>
                  </div>
                  <div>
                    <dt>Business</dt>
                    <dd>
                      {profile?.business || profile?.businessName || "Not set"}
                    </dd>
                  </div>
                  <div>
                    <dt>Role</dt>
                    <dd className="help-role-value">
                      {profile?.role || "Owner"}
                    </dd>
                  </div>
                </dl>
              </aside>
            </div>

            <section className="help-section">
              <div className="help-section-heading">
                <div>
                  <div className="help-panel-kicker">Quick help</div>
                  <h3>Choose what you need help with</h3>
                </div>
                <p>Open the right settings page or start a prepared email.</p>
              </div>

              <div className="help-topic-grid">
                <button
                  type="button"
                  className="help-topic-card"
                  onClick={() => setTab("team")}
                >
                  <span className="help-topic-icon">
                    <FaUsers aria-hidden="true" />
                  </span>
                  <span className="help-topic-copy">
                    <strong>Account & team</strong>
                    <small>Invites, roles, access, and profile questions.</small>
                  </span>
                  <FaArrowRight className="help-topic-arrow" aria-hidden="true" />
                </button>

                <button
                  type="button"
                  className="help-topic-card"
                  onClick={() => setTab("integrations")}
                >
                  <span className="help-topic-icon">
                    <FaPlug aria-hidden="true" />
                  </span>
                  <span className="help-topic-copy">
                    <strong>Integrations</strong>
                    <small>Calendar, Stripe, WhatsApp, and connection status.</small>
                  </span>
                  <FaArrowRight className="help-topic-arrow" aria-hidden="true" />
                </button>

                <a
                  className="help-topic-card"
                  href={supportTopicMailto("Billing and invoices")}
                >
                  <span className="help-topic-icon">
                    <FaCreditCard aria-hidden="true" />
                  </span>
                  <span className="help-topic-copy">
                    <strong>Billing & invoices</strong>
                    <small>Subscriptions, payments, invoices, or payouts.</small>
                  </span>
                  <FaArrowRight className="help-topic-arrow" aria-hidden="true" />
                </a>

                <a
                  className="help-topic-card"
                  href={supportTopicMailto("Automations and messaging")}
                >
                  <span className="help-topic-icon">
                    <FaRobot aria-hidden="true" />
                  </span>
                  <span className="help-topic-copy">
                    <strong>Automations & messages</strong>
                    <small>Flow errors, templates, WhatsApp, and email sends.</small>
                  </span>
                  <FaArrowRight className="help-topic-arrow" aria-hidden="true" />
                </a>
              </div>
            </section>

            <div className="help-lower-grid">
              <section className="help-panel help-faq-panel">
                <div className="help-panel-kicker">Before you email</div>
                <h3>Information that helps us solve it faster</h3>

                <div className="help-checklist">
                  <div>
                    <FaCheckCircle aria-hidden="true" />
                    <span>What page you were on and what you clicked.</span>
                  </div>
                  <div>
                    <FaCheckCircle aria-hidden="true" />
                    <span>What you expected and what happened instead.</span>
                  </div>
                  <div>
                    <FaCheckCircle aria-hidden="true" />
                    <span>A screenshot and the approximate time of the issue.</span>
                  </div>
                  <div>
                    <FaCheckCircle aria-hidden="true" />
                    <span>The affected lead or teammate email, when relevant.</span>
                  </div>
                </div>
              </section>

              <aside className="help-panel help-security-panel">
                <div className="help-security-icon">
                  <FaShieldAlt aria-hidden="true" />
                </div>
                <div>
                  <div className="help-panel-kicker">Stay secure</div>
                  <h3>Never send sensitive credentials</h3>
                  <p>
                    RetainAI support will never need your password, one-time
                    verification code, Stripe secret key, or WhatsApp access
                    token. Redact private customer information from screenshots.
                  </p>
                </div>
              </aside>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

/* ------------------------------------------------------------
   Team tab
------------------------------------------------------------ */

function TeamTab({ ownerEmail, userEmail, maxWidth, canManageTeam, currentRole }) {
  const [members, setMembers] = useState([]);
  const [invites, setInvites] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [serverCanManage, setServerCanManage] = useState(Boolean(canManageTeam));

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviteResult, setInviteResult] = useState(null);

  const canManage = Boolean(serverCanManage || canManageTeam || currentRole === "owner");

  const teamRequest = useCallback(
    async (path, opts = {}) =>
      fetchJson(apiUrl(path), {
        ...opts,
        headers: {
          ...(opts.body ? { "Content-Type": "application/json" } : {}),
          Accept: "application/json",
          "X-User-Email": userEmail || "",
          ...(opts.headers || {}),
        },
      }),
    [userEmail]
  );

  const friendlyError = useCallback((err) => {
    let code = "";
    try {
      code = JSON.parse(err?.raw || "{}")?.error || "";
    } catch {}

    const messages = {
      auth_required: "Your session could not be verified. Log out and back in.",
      forbidden: "Only the workspace owner can manage team members.",
      already_member: "That person is already on this team.",
      email_in_use: "That email already belongs to another RetainAI workspace.",
      valid_email_required: "Enter a valid email address.",
      invalid_role: "Choose Manager or Member.",
      member_not_found: "That team member could not be found.",
      owner_role_locked: "The owner role cannot be changed.",
      cannot_remove_owner: "The workspace owner cannot be removed.",
      invite_not_found: "That invitation is no longer available.",
      invite_inactive: "That invitation is no longer active.",
    };

    return messages[code] || "Something went wrong. Please try again.";
  }, []);

  const loadTeam = useCallback(async () => {
    if (!userEmail) return;
    setLoading(true);
    setError("");

    try {
      const memberData = await teamRequest("team/members");
      const nextMembers = Array.isArray(memberData?.members)
        ? memberData.members
        : [];
      const allowed = Boolean(memberData?.can_manage);

      setMembers(nextMembers);
      setServerCanManage(allowed);

      if (allowed) {
        const inviteData = await teamRequest("team/invites");
        setInvites(Array.isArray(inviteData?.invites) ? inviteData.invites : []);
      } else {
        setInvites([]);
      }
    } catch (err) {
      setMembers([]);
      setInvites([]);
      setError(friendlyError(err));
    } finally {
      setLoading(false);
    }
  }, [friendlyError, teamRequest, userEmail]);

  useEffect(() => {
    loadTeam();
  }, [loadTeam]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return members;
    return members.filter((member) =>
      [member.name, member.email, member.role, member.status]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(q))
    );
  }, [members, search]);

  const activeCount = members.filter(
    (member) => String(member.status || "active").toLowerCase() === "active"
  ).length;

  const formatDate = (value) => {
    if (!value) return "Never";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Never";

    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return `Today, ${date.toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
      })}`;
    }

    return date.toLocaleDateString([], {
      month: "short",
      day: "numeric",
      year: date.getFullYear() !== today.getFullYear() ? "numeric" : undefined,
    });
  };

  const copyText = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      setNotice("Invitation link copied.");
    } catch {
      window.prompt("Copy this invitation link:", text);
    }
  };

  const openInvite = () => {
    setInviteEmail("");
    setInviteRole("member");
    setInviteResult(null);
    setError("");
    setInviteOpen(true);
  };

  const submitInvite = async (event) => {
    event.preventDefault();
    setBusyKey("invite");
    setError("");
    setNotice("");

    try {
      const data = await teamRequest("team/invite", {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      setInviteResult(data?.invite || null);
      setNotice(
        data?.invite?.email_sent
          ? "Invitation email sent."
          : "Invitation created. Copy the link below to send it manually."
      );
      await loadTeam();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusyKey("");
    }
  };

  const changeRole = async (email, role) => {
    setBusyKey(`role:${email}`);
    setError("");
    setNotice("");

    try {
      const data = await teamRequest("team/role", {
        method: "POST",
        body: JSON.stringify({ email, role }),
      });
      setMembers((current) =>
        current.map((member) =>
          member.email === email ? data?.member || { ...member, role } : member
        )
      );
      setNotice("Member role updated.");
    } catch (err) {
      setError(friendlyError(err));
      await loadTeam();
    } finally {
      setBusyKey("");
    }
  };

  const removeMember = async (member) => {
    const label = member.name || member.email;
    if (!window.confirm(`Remove ${label} from this workspace?`)) return;

    setBusyKey(`remove:${member.email}`);
    setError("");
    setNotice("");

    try {
      await teamRequest("team/remove", {
        method: "POST",
        body: JSON.stringify({ email: member.email }),
      });
      setMembers((current) =>
        current.filter((item) => item.email !== member.email)
      );
      setNotice(`${label} was removed from the workspace.`);
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusyKey("");
    }
  };

  const resendInvite = async (invite) => {
    setBusyKey(`resend:${invite.token}`);
    setError("");
    setNotice("");

    try {
      const data = await teamRequest("team/invite/resend", {
        method: "POST",
        body: JSON.stringify({ token: invite.token }),
      });
      setNotice(
        data?.invite?.email_sent
          ? `Invitation resent to ${invite.email}.`
          : "Invitation renewed. Copy its link to send it manually."
      );
      await loadTeam();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusyKey("");
    }
  };

  const cancelInvite = async (invite) => {
    if (!window.confirm(`Cancel the invitation for ${invite.email}?`)) return;
    setBusyKey(`cancel:${invite.token}`);
    setError("");
    setNotice("");

    try {
      await teamRequest("team/invite/cancel", {
        method: "POST",
        body: JSON.stringify({ token: invite.token }),
      });
      setInvites((current) =>
        current.filter((item) => item.token !== invite.token)
      );
      setNotice("Invitation cancelled.");
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusyKey("");
    }
  };

  return (
    <div className="team-tab" style={{ maxWidth, margin: "0 auto" }}>
      <div className="team-heading-row">
        <div>
          <h2>Team</h2>
          <p>Manage who can access your RetainAI workspace.</p>
        </div>

        {canManage && (
          <button className="team-primary-btn" onClick={openInvite}>
            <FaUserPlus />
            Invite member
          </button>
        )}
      </div>

      <div className="team-stats">
        <div className="team-stat-card">
          <span>Active members</span>
          <strong>{activeCount}</strong>
        </div>
        <div className="team-stat-card">
          <span>Pending invitations</span>
          <strong>{invites.length}</strong>
        </div>
        <div className="team-stat-card">
          <span>Your access</span>
          <strong className="team-role-text">
            {String(currentRole || (canManage ? "owner" : "member"))}
          </strong>
        </div>
      </div>

      {(notice || error) && (
        <div className={`team-message ${error ? "error" : "success"}`}>
          {error || notice}
        </div>
      )}

      <div className="team-toolbar">
        <label className="team-search">
          <FaSearch />
          <input
            placeholder="Search by name, email, role, or status"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>

        <button
          className="team-secondary-btn"
          onClick={loadTeam}
          disabled={loading}
        >
          <FaSyncAlt className={loading ? "team-spin" : ""} />
          Refresh
        </button>
      </div>

      <section className="team-panel">
        <div className="team-panel-title">
          <div>
            <h3>Workspace members</h3>
            <span>{members.length} total</span>
          </div>
        </div>

        <div className="team-table team-table-header">
          <div>Member</div>
          <div>Role</div>
          <div>Status</div>
          <div>Last active</div>
          <div aria-label="Actions" />
        </div>

        {loading ? (
          <div className="team-empty">Loading your team…</div>
        ) : filtered.length === 0 ? (
          <div className="team-empty">
            {search ? "No members match that search." : "No team members found."}
          </div>
        ) : (
          filtered.map((member) => {
            const isOwner =
              member.role === "owner" || member.email === ownerEmail;
            const rowBusy = busyKey.includes(member.email);
            const initial = (member.name || member.email || "?")
              .trim()
              .charAt(0)
              .toUpperCase();

            return (
              <div className="team-table team-member-row" key={member.email}>
                <div className="team-member-cell" data-label="Member">
                  <div className="team-avatar">
                    {member.avatar ? (
                      <img src={member.avatar} alt="" />
                    ) : (
                      initial
                    )}
                  </div>
                  <div className="team-member-copy">
                    <strong>{member.name || "Unnamed member"}</strong>
                    <span>{member.email}</span>
                  </div>
                </div>

                <div data-label="Role">
                  {isOwner ? (
                    <span className="team-badge owner">
                      <FaCrown /> Owner
                    </span>
                  ) : canManage ? (
                    <select
                      className="team-role-select"
                      value={member.role || "member"}
                      disabled={rowBusy}
                      onChange={(event) =>
                        changeRole(member.email, event.target.value)
                      }
                    >
                      <option value="manager">Manager</option>
                      <option value="member">Member</option>
                    </select>
                  ) : (
                    <span className="team-badge neutral">
                      {member.role || "member"}
                    </span>
                  )}
                </div>

                <div data-label="Status">
                  <span className="team-badge active">
                    <span className="team-status-dot" />
                    {member.status || "active"}
                  </span>
                </div>

                <div className="team-last-active" data-label="Last active">
                  {formatDate(member.last_login)}
                </div>

                <div className="team-actions" data-label="Actions">
                  {!isOwner && canManage ? (
                    <button
                      className="team-icon-btn danger"
                      title={`Remove ${member.name || member.email}`}
                      disabled={rowBusy}
                      onClick={() => removeMember(member)}
                    >
                      <FaTrash />
                      <span>Remove</span>
                    </button>
                  ) : (
                    <span className="team-locked-copy">
                      {isOwner ? "Protected" : ""}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </section>

      {canManage && (
        <section className="team-panel team-invites-panel">
          <div className="team-panel-title">
            <div>
              <h3>Pending invitations</h3>
              <span>Invitation links expire after 7 days.</span>
            </div>
          </div>

          {invites.length === 0 ? (
            <div className="team-empty compact">No pending invitations.</div>
          ) : (
            invites.map((invite) => (
              <div className="team-invite-row" key={invite.token}>
                <div className="team-invite-main">
                  <div className="team-invite-icon">
                    <FaClock />
                  </div>
                  <div>
                    <strong>{invite.email}</strong>
                    <span>
                      {invite.role === "manager" ? "Manager" : "Member"} · Expires {" "}
                      {new Date(invite.expires_at * 1000).toLocaleDateString()}
                    </span>
                  </div>
                </div>

                <div className="team-invite-actions">
                  <button
                    className="team-text-btn"
                    onClick={() => copyText(invite.accept_url)}
                  >
                    <FaCopy /> Copy link
                  </button>
                  <button
                    className="team-text-btn"
                    disabled={busyKey === `resend:${invite.token}`}
                    onClick={() => resendInvite(invite)}
                  >
                    <FaSyncAlt /> Resend
                  </button>
                  <button
                    className="team-text-btn danger"
                    disabled={busyKey === `cancel:${invite.token}`}
                    onClick={() => cancelInvite(invite)}
                  >
                    <FaTimes /> Cancel
                  </button>
                </div>
              </div>
            ))
          )}
        </section>
      )}

      {inviteOpen && (
        <div
          className="team-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setInviteOpen(false);
          }}
        >
          <div className="team-modal" role="dialog" aria-modal="true">
            <button
              className="team-modal-close"
              onClick={() => setInviteOpen(false)}
              aria-label="Close invitation dialog"
            >
              <FaTimes />
            </button>

            <div className="team-modal-icon">
              <FaUserPlus />
            </div>
            <h3>Invite a team member</h3>
            <p>
              They will receive access to this workspace based on the role you
              choose.
            </p>

            {!inviteResult ? (
              <form onSubmit={submitInvite}>
                <label className="team-field">
                  <span>Email address</span>
                  <input
                    type="email"
                    required
                    autoFocus
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                    placeholder="teammate@example.com"
                  />
                </label>

                <label className="team-field">
                  <span>Role</span>
                  <select
                    value={inviteRole}
                    onChange={(event) => setInviteRole(event.target.value)}
                  >
                    <option value="member">Member — everyday CRM access</option>
                    <option value="manager">Manager — broader workspace access</option>
                  </select>
                </label>

                <div className="team-role-help">
                  <strong>
                    {inviteRole === "manager" ? "Manager" : "Member"}
                  </strong>
                  <span>
                    {inviteRole === "manager"
                      ? "Can work with leads, messages, calendar, analytics, and automations."
                      : "Can work with leads, messages, calendar, and notifications."}
                  </span>
                </div>

                <button
                  className="team-primary-btn team-modal-submit"
                  type="submit"
                  disabled={busyKey === "invite"}
                >
                  {busyKey === "invite" ? "Creating invitation…" : "Send invitation"}
                </button>
              </form>
            ) : (
              <div className="team-invite-success">
                <FaCheckCircle />
                <h4>Invitation ready</h4>
                <p>
                  {inviteResult.email_sent
                    ? `An email was sent to ${inviteResult.email}.`
                    : "Email delivery is not configured, so send this secure link manually."}
                </p>
                <button
                  className="team-secondary-btn"
                  onClick={() => copyText(inviteResult.accept_url)}
                >
                  <FaCopy /> Copy invitation link
                </button>
                <button
                  className="team-text-btn"
                  onClick={() => setInviteOpen(false)}
                >
                  Done
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

