// File: frontend/src/components/Settings.jsx
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import GoogleCalendarEvents from "./GoogleCalendarEvents";
import StripeConnectCard from "./StripeConnectCard";
import {
  FaUser,
  FaPlug,
  FaQuestionCircle,
  FaUsers,
  FaSearch,
  FaTrash,
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
  const [saving, setSaving] = useState(false);
  const [info, setInfo] = useState("");
  const [profileBackendOk, setProfileBackendOk] = useState(null);

  useEffect(() => {
    if (initialTab && TABS.some((t) => t.key === initialTab)) {
      setTab(initialTab);
    }
  }, [initialTab]);

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

    setForm({
      name: next.name || "",
      email: next.email || "",
      business: next.business || next.businessName || "",
      type: next.businessType || next.lineOfBusiness || "",
      location: next.location || "",
      teamSize: String(next.people ?? next.teamSize ?? ""),
    });

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
      setForm({
        name: fromBackend.name || "",
        email: fromBackend.email || "",
        business: fromBackend.business || fromBackend.businessName || "",
        type: fromBackend.businessType || fromBackend.lineOfBusiness || "",
        location: fromBackend.location || "",
        teamSize: String(fromBackend.people ?? fromBackend.teamSize ?? ""),
      });

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
        setForm({
          name: fromBackend.name || "",
          email: fromBackend.email || "",
          business: fromBackend.business || fromBackend.businessName || "",
          type: fromBackend.businessType || fromBackend.lineOfBusiness || "",
          location: fromBackend.location || "",
          teamSize: String(fromBackend.people ?? fromBackend.teamSize ?? ""),
        });

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
      setEditMode(false);
    } finally {
      setSaving(false);
    }
  }, [form, profile, refreshUser, syncProfileFromBackend]);

  const leftOffset = sidebarCollapsed ? 60 : 245;
  const settingsWidth = `calc(100vw - ${leftOffset}px)`;
  const MAX_W = 1000;

  if (!profile?.email) {
    return (
      <div
        className="settings-layout"
        style={{ left: leftOffset, width: settingsWidth }}
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
      style={{ left: leftOffset, width: settingsWidth }}
    >
      <nav className="settings-nav">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={tab === t.key ? "active" : ""}
            onClick={() => {
              setTab(t.key);
              setEditMode(false);
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
                        onChange={(e) =>
                          setForm((f) => ({ ...f, [name]: e.target.value }))
                        }
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
                      onClick={() => setEditMode(true)}
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
          />
        )}

        {tab === "integrations" && (
          <div style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <h2>Integrations</h2>

            <div className="integration-row" style={{ justifyContent: "center" }}>
              <div className="integration-card">
                <GoogleCalendarEvents
                  user={profile}
                  onStatus={setGcalStatus}
                  onEvents={setGoogleEvents}
                />
              </div>

              <StripeConnectCard
                user={profile}
                refreshUser={async () => {
                  try {
                    if (typeof refreshUser === "function") {
                      await refreshUser();
                    }
                  } catch {}

                  try {
                    await syncProfileFromBackend(profile.email);
                  } catch {}
                }}
              />

              <div className="integration-card coming-soon">
                <SiInstagram className="integration-icon instagram" />
                <div>
                  <div className="integration-title">Instagram</div>
                  <div className="integration-desc">Coming soon!</div>
                </div>
              </div>
            </div>

            <div style={{ marginTop: 12, color: "#bbb" }}>
              Google Calendar status:{" "}
              <b style={{ color: "#fff" }}>{gcalStatus || "Not connected"}</b>
            </div>

            <div style={{ marginTop: 8, color: "#bbb" }}>
              Stripe status:{" "}
              <b style={{ color: "#fff" }}>
                {profile?.stripe_connected ? "Connected" : "Not connected"}
              </b>
              {profile?.stripe_account_id ? (
                <span style={{ marginLeft: 8, color: "#8d8d93" }}>
                  ({profile.stripe_account_id})
                </span>
              ) : null}
            </div>
          </div>
        )}

        {tab === "help" && (
          <div style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <h2>Help & Support</h2>
            <p className="help-line">
              If you need anything, email{" "}
              <a href="mailto:owner@retainai.ca">owner@retainai.ca</a>.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

/* ------------------------------------------------------------
   Team tab
------------------------------------------------------------ */

function TeamTab({ ownerEmail, userEmail, maxWidth }) {
  const [members, setMembers] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyEmail, setBusyEmail] = useState("");
  const [error, setError] = useState("");

  const roles = ["owner", "manager", "member"];

  const loadMembers = useCallback(async () => {
    if (!ownerEmail) return;
    setLoading(true);
    setError("");

    const url = apiUrl(
      `team/members?ownerEmail=${encodeURIComponent(ownerEmail)}`
    );

    try {
      const res = await fetch(url, {
        credentials: "include",
        headers: {
          Accept: "application/json",
          "X-User-Email": userEmail || "",
          "X-Owner-Email": ownerEmail || "",
        },
      });

      const ct = (res.headers.get("content-type") || "").toLowerCase();
      const raw = await res.text();

      if (!res.ok) {
        throw new Error(`HTTP ${res.status} @ ${url}\n${raw.slice(0, 300)}`);
      }
      if (!ct.includes("application/json")) {
        throw new Error(
          `Expected JSON @ ${url} but got ${ct || "unknown"}\n${raw.slice(
            0,
            200
          )}`
        );
      }

      const data = JSON.parse(raw);
      if (Array.isArray(data?.members)) setMembers(data.members);
      else if (Array.isArray(data)) setMembers(data);
      else setMembers([]);
    } catch (e) {
      setError(String(e).slice(0, 900));
      setMembers([]);
    } finally {
      setLoading(false);
    }
  }, [ownerEmail, userEmail]);

  useEffect(() => {
    loadMembers();
  }, [loadMembers]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return members;
    return members.filter(
      (m) =>
        (m.name || "").toLowerCase().includes(q) ||
        (m.email || "").toLowerCase().includes(q) ||
        (m.role || "").toLowerCase().includes(q)
    );
  }, [members, search]);

  const changeRole = async (email, role) => {
    setBusyEmail(email);
    setMembers((ms) => ms.map((m) => (m.email === email ? { ...m, role } : m)));

    try {
      await fetch(apiUrl("team/role"), {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-User-Email": userEmail || "",
          "X-Owner-Email": ownerEmail || "",
        },
        body: JSON.stringify({ email, role, ownerEmail }),
      });
    } catch {
      alert("Could not change role. Backend route /api/team/role may be missing.");
      loadMembers();
    } finally {
      setBusyEmail("");
    }
  };

  const removeMember = async (email) => {
    if (!window.confirm("Remove this member?")) return;
    setBusyEmail(email);

    const prev = members;
    setMembers((ms) => ms.filter((m) => m.email !== email));

    try {
      await fetch(apiUrl("team/remove"), {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-User-Email": userEmail || "",
          "X-Owner-Email": ownerEmail || "",
        },
        body: JSON.stringify({ email, ownerEmail }),
      });
    } catch {
      alert("Could not remove. Backend route /api/team/remove may be missing.");
      setMembers(prev);
    } finally {
      setBusyEmail("");
    }
  };

  return (
    <div>
      <h2 style={{ maxWidth: maxWidth, margin: "0 auto 14px" }}>Team</h2>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          margin: "0 auto 14px",
          maxWidth: maxWidth,
          width: "100%",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "#232325",
            borderRadius: 10,
            padding: "10px 12px",
            border: "1px solid #2c2c2f",
            flex: 1,
          }}
        >
          <FaSearch style={{ color: "#aaa" }} />
          <input
            placeholder="Search by name, email, or role…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              background: "transparent",
              border: "none",
              outline: "none",
              color: "#fff",
              width: "100%",
            }}
          />
        </div>

        <button
          className="btn"
          onClick={loadMembers}
          style={{
            background: "#232323",
            color: "#fff",
            border: "1px solid #444",
          }}
        >
          Refresh
        </button>
      </div>

      {error && (
        <pre
          style={{
            maxWidth,
            margin: "0 auto 14px",
            padding: 12,
            background: "#2a2a2e",
            border: "1px solid #3a3a3f",
            borderRadius: 10,
            color: "#ddd",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {error}
        </pre>
      )}

      <div
        style={{
          background: "#232325",
          borderRadius: 12,
          padding: 0,
          overflow: "hidden",
          boxShadow: "0 2px 12px #0002",
          maxWidth: maxWidth,
          width: "100%",
          margin: "0 auto",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "2fr 2fr 1.2fr 1.2fr 0.8fr",
            gap: 8,
            padding: "14px 16px",
            background: "#1f1f23",
            color: "#bbb",
            fontWeight: 800,
          }}
        >
          <div>Name</div>
          <div>Email</div>
          <div>Role</div>
          <div>Last login</div>
          <div style={{ textAlign: "right" }}>Actions</div>
        </div>

        {loading ? (
          <div style={{ padding: 18, color: "#ddd" }}>Loading members…</div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: 18, color: "#bbb" }}>
            No members found (or backend team routes missing).
          </div>
        ) : (
          filtered.map((m) => (
            <div
              key={m.email}
              style={{
                display: "grid",
                gridTemplateColumns: "2fr 2fr 1.2fr 1.2fr 0.8fr",
                gap: 8,
                padding: "14px 16px",
                borderTop: "1px solid #2b2b2f",
                alignItems: "center",
              }}
            >
              <div style={{ color: "#fff", fontWeight: 700 }}>
                {m.name || "—"}
              </div>
              <div style={{ color: "#ddd" }}>{m.email}</div>
              <div>
                <select
                  disabled={busyEmail === m.email || m.email === ownerEmail}
                  value={m.role || "member"}
                  onChange={(e) => changeRole(m.email, e.target.value)}
                  style={{
                    background: "#18181b",
                    color: "#fff",
                    border: "1px solid #333",
                    borderRadius: 8,
                    padding: "8px 10px",
                    fontWeight: 700,
                    minWidth: 120,
                  }}
                >
                  {roles.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ color: "#bbb" }}>
                {m.last_login ? new Date(m.last_login).toLocaleString() : "—"}
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button
                  className="btn"
                  title="Remove"
                  disabled={busyEmail === m.email || m.email === ownerEmail}
                  onClick={() => removeMember(m.email)}
                  style={{
                    background: "#2a2a2a",
                    color: "#fff",
                    border: "1px solid #3a3a3a",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <FaTrash />
                  Remove
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}