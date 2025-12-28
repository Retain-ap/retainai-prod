// File: src/components/Settings.jsx
import React, { useState, useEffect, useMemo, useRef } from "react";
import { useLocation } from "react-router-dom";
import GoogleCalendarEvents from "./GoogleCalendarEvents";
import StripeConnectCard from "./StripeConnectCard";
import { FaUser, FaPlug, FaQuestionCircle, FaUsers, FaSearch, FaTrash } from "react-icons/fa";
import { SiInstagram } from "react-icons/si";
import "./settings.css";

/* ───────────────────────────────────────────────────────────────
   API base auto-detection (prod safe)
   Tries envs first, then same-origin /api variations.
   Caches the first base that returns application/json.
   ─────────────────────────────────────────────────────────────── */
function norm(u) {
  if (!u) return "";
  // Remove trailing slashes
  return u.replace(/\/+$/, "");
}

function candidatesFromEnv() {
  const v1 = (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_API_BASE) || "";
  const v2 = (typeof process !== "undefined" && process.env && process.env.REACT_APP_API_BASE) || "";
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return [
    norm(v1),
    norm(v2),
    // same-origin API prefix patterns
    norm("/api"),
    norm(`${origin}/api`),
  ].filter(Boolean);
}

/** Robust JSON fetcher that surfaces HTML/500s clearly and retries with other bases */
async function fetchJSONExpecting(url, opts = {}) {
  const res = await fetch(url, opts);
  const ct = res.headers.get("content-type") || "";
  const body = await res.text();

  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${res.statusText} @ ${url}\n${body.slice(0, 400)}`);
  }
  if (!ct.toLowerCase().includes("application/json")) {
    // If server sent HTML, likely the SPA index or a proxy miss.
    if (/<\/html>/i.test(body) || /<!doctype html>/i.test(body)) {
      throw new Error(`Expected JSON but got HTML (likely SPA fallback) @ ${url}\nCheck API base / proxy.`);
    }
    throw new Error(`Expected JSON but got ${ct} @ ${url}\n${body.slice(0, 400)}`);
  }

  try {
    return JSON.parse(body);
  } catch (e) {
    throw new Error(`Failed to parse JSON @ ${url}: ${e}\n${body.slice(0, 400)}`);
  }
}

/** Try multiple bases until one returns JSON. Remember the working one in memory + sessionStorage. */
async function fetchJSONWithBaseDiscovery(path, opts = {}, stickyBaseRef) {
  // Allow absolute URLs
  if (/^https?:\/\//i.test(path)) {
    return fetchJSONExpecting(path, opts);
  }

  // If we already discovered a working base this session, use it first
  const cached = stickyBaseRef.current || sessionStorage.getItem("__api_base__");
  const bases = [];
  if (cached) bases.push(cached);
  for (const c of candidatesFromEnv()) {
    if (!bases.includes(c)) bases.push(c);
  }

  const tried = [];
  let lastErr = null;

  for (const base of bases) {
    const url = `${base}${path.startsWith("/") ? "" : "/"}${path}`;
    try {
      const data = await fetchJSONExpecting(url, {
        credentials: "include",
        headers: { Accept: "application/json", ...(opts.headers || {}) },
        ...opts,
      });
      // Cache the working base
      stickyBaseRef.current = base;
      sessionStorage.setItem("__api_base__", base);
      return data;
    } catch (e) {
      lastErr = e;
      tried.push(`${base}${path}`);
    }
  }

  const msg = `All API base candidates failed for ${path}.
Tried:
- ${tried.join("\n- ")}
Last error: ${lastErr}`;
  throw new Error(msg);
}

const TABS = [
  { key: "profile",      label: "Profile",        icon: <FaUser /> },
  { key: "team",         label: "Team",           icon: <FaUsers /> },
  { key: "integrations", label: "Integrations",   icon: <FaPlug /> },
  { key: "help",         label: "Help & Support", icon: <FaQuestionCircle /> },
];

export default function Settings({
  user,
  sidebarCollapsed,
  googleEvents,
  setGoogleEvents,
  gcalStatus,
  setGcalStatus,
  initialTab,
}) {
  const { search } = useLocation();
  const [tab, setTab] = useState(initialTab || "profile");
  const [profile, setProfile] = useState(null);
  const [form, setForm] = useState({
    name: "", email: "", business: "", type: "", location: "", teamSize: ""
  });
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [bootError, setBootError] = useState("");
  const apiBaseRef = useRef(null); // sticky working base for this component

  useEffect(() => {
    if (initialTab && TABS.some(t => t.key === initialTab)) setTab(initialTab);
  }, [initialTab]);

  /** Load profile from backend (GET /api/profile?email=...) */
  const loadProfile = async () => {
    try {
      setBootError("");
      if (!user?.email) return;
      const data = await fetchJSONWithBaseDiscovery(
        `/api/profile?email=${encodeURIComponent(user.email)}`,
        { method: "GET" },
        apiBaseRef
      );
      setProfile(data);
      setForm({
        name: data.name || "",
        email: data.email || "",
        business: data.business || data.businessName || "",
        type: data.businessType || "",
        location: data.location || "",
        teamSize: data.people || data.teamSize || ""
      });
      localStorage.setItem("user", JSON.stringify(data));
    } catch (err) {
      console.error("Failed to load profile:", err);
      setBootError(String(err).slice(0, 600));
      setProfile(null);
    }
  };

  // Load when user email is available
  useEffect(() => { loadProfile(); }, [user?.email]);

  // If Stripe redirect param is present, refresh profile
  useEffect(() => {
    const params = new URLSearchParams(search);
    if (params.get("stripe_connected") === "1") loadProfile();
  }, [search, user?.email]);

  /** Save profile. Uses your existing route /api/oauth/google/complete */
  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        email: form.email,
        name: form.name,
        logo: profile?.logo || "",
        businessType: form.type,
        businessName: form.business,
        people: form.teamSize
      };
      const data = await fetchJSONWithBaseDiscovery(
        `/api/oauth/google/complete`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        apiBaseRef
      );
      if (data.user) {
        await loadProfile();
        setEditMode(false);
      } else {
        console.error("Save error payload:", data);
      }
    } catch (e) {
      console.error("Failed to save profile:", e);
      alert("Could not save profile. See console for details.");
    } finally {
      setSaving(false);
    }
  };

  const leftOffset = sidebarCollapsed ? 60 : 245;
  const settingsWidth = `calc(100vw - ${leftOffset}px)`;
  const MAX_W = 1000;

  // Boot errors (like wrong API base / proxy) should render clearly
  if (!profile) {
    return (
      <div className="settings-layout" style={{ left: leftOffset, width: settingsWidth }}>
        <div style={{ padding: 16 }}>
          <div style={{ fontWeight: 800, marginBottom: 8 }}>Loading…</div>
          {bootError && (
            <pre
              style={{
                marginTop: 10,
                padding: 12,
                background: "#2a2a2e",
                borderRadius: 8,
                border: "1px solid #3a3a3f",
                color: "#ddd",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                maxWidth: 800,
              }}
            >
{bootError}
            </pre>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="settings-layout" style={{ left: leftOffset, width: settingsWidth }}>
      <nav className="settings-nav">
        {TABS.map(t => (
          <button
            key={t.key}
            className={tab === t.key ? "active" : ""}
            onClick={() => { setTab(t.key); setEditMode(false); }}
          >
            <span className="settings-icon">{t.icon}</span>
            <span className="settings-label">{t.label}</span>
          </button>
        ))}
      </nav>

      <main className="settings-content fade-in">
        {/* PROFILE */}
        {tab === "profile" && (
          <div className="profile-tab" style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <h2>Profile</h2>
            <div className="profile-card">
              <div className="avatar">
                {profile.logo ? <img src={profile.logo} alt="logo" /> : (profile.name?.[0]?.toUpperCase() || "?")}
              </div>
              <div className="profile-fields">
                {[
                  { label: "Name",      name: "name"     },
                  { label: "Email",     name: "email"    },
                  { label: "Business",  name: "business" },
                  { label: "Type",      name: "type"     },
                  { label: "Location",  name: "location" },
                  { label: "Team Size", name: "teamSize" }
                ].map(({ label, name }) => (
                  <div key={name} className="field-row">
                    <div className="field-label">{label}</div>
                    {editMode ? (
                      <input
                        className="field-input"
                        type="text"
                        value={form[name]}
                        onChange={e => setForm(f => ({ ...f, [name]: e.target.value }))}
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
                        onClick={() => { setEditMode(false); loadProfile(); }}
                        disabled={saving}
                      >
                        Cancel
                      </button>
                      <button className="btn btn-save" onClick={handleSave} disabled={saving}>
                        {saving ? "Saving…" : "Save"}
                      </button>
                    </>
                  ) : (
                    <button className="btn btn-edit" onClick={() => setEditMode(true)}>
                      Edit Profile
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TEAM */}
        {tab === "team" && (
          <TeamTab ownerEmail={profile.email} maxWidth={MAX_W} apiBaseRef={apiBaseRef} />
        )}

        {/* INTEGRATIONS */}
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

              <StripeConnectCard user={profile} refreshUser={loadProfile} />

              <div className="integration-card coming-soon">
                <SiInstagram className="integration-icon instagram" />
                <div>
                  <div className="integration-title">Instagram</div>
                  <div className="integration-desc">Coming soon!</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* HELP */}
        {tab === "help" && (
          <div style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <h2>Help & Support</h2>
            <p className="help-line">
              If you need anything, email{" "}
              <a href="mailto:owner@retainai.ca">owner@retainai.ca</a> or see our{" "}
              <a href="https://docs.retainai.ca" target="_blank" rel="noreferrer">
                documentation
              </a>.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────── */
/* Team tab                                                        */
/* ─────────────────────────────────────────────────────────────── */
function TeamTab({ ownerEmail, maxWidth, apiBaseRef }) {
  const [members, setMembers] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyEmail, setBusyEmail] = useState("");

  const roles = ["owner", "manager", "member"];

  const loadMembers = async () => {
    if (!ownerEmail) return;
    setLoading(true);
    try {
      const data = await fetchJSONWithBaseDiscovery(
        `/api/team/members`,
        {
          headers: { "X-User-Email": ownerEmail },
        },
        apiBaseRef
      );
      if (data.members) setMembers(data.members);
    } catch (e) {
      console.error("Load members failed:", e);
      alert("Could not load team members. Check API base / backend routes.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (ownerEmail) loadMembers(); }, [ownerEmail]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return members;
    return members.filter(m =>
      (m.name || "").toLowerCase().includes(q) ||
      (m.email || "").toLowerCase().includes(q) ||
      (m.role || "").toLowerCase().includes(q)
    );
  }, [members, search]);

  const changeRole = async (email, role) => {
    setBusyEmail(email);
    setMembers(ms => ms.map(m => (m.email === email ? { ...m, role } : m)));
    try {
      await fetchJSONWithBaseDiscovery(
        `/api/team/role`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-User-Email": ownerEmail },
          body: JSON.stringify({ email, role }),
        },
        apiBaseRef
      );
    } catch (e) {
      alert("Could not change role. Make sure /api/team/role exists on backend.");
      loadMembers();
    } finally {
      setBusyEmail("");
    }
  };

  const removeMember = async (email) => {
    if (!window.confirm("Remove this member?")) return;
    setBusyEmail(email);
    const prev = members;
    setMembers(ms => ms.filter(m => m.email !== email));
    try {
      await fetchJSONWithBaseDiscovery(
        `/api/team/remove`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-User-Email": ownerEmail },
          body: JSON.stringify({ email }),
        },
        apiBaseRef
      );
    } catch (e) {
      alert("Could not remove. Make sure /api/team/remove exists on backend.");
      setMembers(prev);
    } finally {
      setBusyEmail("");
    }
  };

  return (
    <div>
      <h2 style={{ maxWidth: maxWidth, margin: "0 auto 14px" }}>Team</h2>

      {/* Search + refresh */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          margin: "0 auto 14px",
          maxWidth: maxWidth,
          width: "100%"
        }}
      >
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          background: "#232325", borderRadius: 10,
          padding: "10px 12px", border: "1px solid #2c2c2f", flex: 1
        }}>
          <FaSearch style={{ color: "#aaa" }} />
          <input
            placeholder="Search by name, email, or role…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ background: "transparent", border: "none", outline: "none", color: "#fff", width: "100%" }}
          />
        </div>
        <button
          className="btn"
          onClick={loadMembers}
          style={{ background: "#232323", color: "#fff", border: "1px solid #444" }}
        >
          Refresh
        </button>
      </div>

      {/* Members table */}
      <div
        style={{
          background: "#232325",
          borderRadius: 12,
          padding: 0,
          overflow: "hidden",
          boxShadow: "0 2px 12px #0002",
          maxWidth: maxWidth,
          width: "100%",
          margin: "0 auto"
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
            fontWeight: 800
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
          <div style={{ padding: 18, color: "#bbb" }}>No members found.</div>
        ) : (
          filtered.map(m => (
            <div
              key={m.email}
              style={{
                display: "grid",
                gridTemplateColumns: "2fr 2fr 1.2fr 1.2fr 0.8fr",
                gap: 8,
                padding: "14px 16px",
                borderTop: "1px solid #2b2b2f",
                alignItems: "center"
              }}
            >
              <div style={{ color: "#fff", fontWeight: 700 }}>{m.name || "—"}</div>
              <div style={{ color: "#ddd" }}>{m.email}</div>
              <div>
                <select
                  disabled={busyEmail === m.email || m.email === ownerEmail}
                  value={m.role || "member"}
                  onChange={e => changeRole(m.email, e.target.value)}
                  style={{
                    background: "#18181b",
                    color: "#fff",
                    border: "1px solid #333",
                    borderRadius: 8,
                    padding: "8px 10px",
                    fontWeight: 700,
                    minWidth: 120
                  }}
                >
                  {roles.map(r => <option key={r} value={r}>{r}</option>)}
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
                    gap: 8
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
