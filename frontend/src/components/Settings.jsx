// File: frontend/src/components/Settings.jsx
import React, { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
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

/* ───────────────────────────────────────────────────────────────
   Settings.jsx (Render-safe)
   - NO top-level fetch calls
   - Uses apiUrl() from apiBase.js (single source of truth)
   - Protects against SPA HTML fallback
   - Fallbacks if backend route differs:
       GET  /api/profile?email=
       GET  /api/user/<email>
       POST /api/profile
       POST /api/user
   ─────────────────────────────────────────────────────────────── */

function isProbablyHtml(text) {
  const t = String(text || "").toLowerCase();
  return t.includes("<!doctype html") || t.includes("</html>") || t.includes("<head");
}

async function fetchJSONStrict(url, opts = {}) {
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
    throw new Error(`HTTP ${res.status} ${res.statusText} @ ${url}\n${raw.slice(0, 400)}`);
  }

  // If backend accidentally routes to SPA, we get HTML.
  if (!ct.includes("application/json")) {
    if (isProbablyHtml(raw)) {
      throw new Error(
        `Expected JSON but got HTML (SPA fallback). Wrong API base / route.\nURL: ${url}`
      );
    }
    throw new Error(
      `Expected JSON but got ${ct || "unknown content-type"}.\nURL: ${url}\n${raw.slice(0, 200)}`
    );
  }

  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`Bad JSON @ ${url}: ${e}\n${raw.slice(0, 200)}`);
  }
}

function normalizeProfileResponse(raw, fallbackEmail) {
  const base = (raw && (raw.profile || raw.user || raw)) || {};
  const out = { ...base };
  if (!out.email && fallbackEmail) out.email = fallbackEmail;

  // Normalize naming variants
  if (!out.business && out.businessName) out.business = out.businessName;
  if (!out.businessName && out.business) out.businessName = out.business;

  if (!out.businessType && out.type) out.businessType = out.type;

  return out;
}

const TABS = [
  { key: "profile", label: "Profile", icon: <FaUser /> },
  { key: "team", label: "Team", icon: <FaUsers /> },
  { key: "integrations", label: "Integrations", icon: <FaPlug /> },
  { key: "help", label: "Help & Support", icon: <FaQuestionCircle /> },
];

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
  const { search } = useLocation();

  const [tab, setTab] = useState(initialTab || "profile");
  const [profile, setProfile] = useState(null);
  const [form, setForm] = useState({
    name: "",
    email: "",
    business: "",
    type: "",
    location: "",
    teamSize: "",
  });

  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [bootError, setBootError] = useState("");
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    if (initialTab && TABS.some((t) => t.key === initialTab)) setTab(initialTab);
  }, [initialTab]);

  // --- Load profile with fallback routes ---
  const loadProfile = async () => {
    setBootError("");
    setBooting(true);

    try {
      const email = user?.email || profile?.email || "";
      if (!email) {
        setProfile(null);
        setBootError("No user email found. Please sign in again.");
        return;
      }

      // Attempt 1: /api/profile?email=
      try {
        const url1 = apiUrl(`profile?email=${encodeURIComponent(email)}`);
        const raw1 = await fetchJSONStrict(url1);
        const prof1 = normalizeProfileResponse(raw1, email);
        setProfile(prof1);
        setForm({
          name: prof1.name || "",
          email: prof1.email || email,
          business: prof1.business || prof1.businessName || "",
          type: prof1.businessType || "",
          location: prof1.location || "",
          teamSize:
            prof1.people ?? prof1.teamSize ?? prof1.team_size ?? prof1.teamSize === 0
              ? String(prof1.people ?? prof1.teamSize ?? prof1.team_size ?? "")
              : "",
        });

        try {
          localStorage.setItem("user", JSON.stringify(prof1));
        } catch {}

        return;
      } catch (e1) {
        // fall through to try /api/user/<email>
        console.warn("profile?email route failed, trying /user/<email>:", e1);
      }

      // Attempt 2: /api/user/<email>
      const url2 = apiUrl(`user/${encodeURIComponent(email)}`);
      const raw2 = await fetchJSONStrict(url2);
      const prof2 = normalizeProfileResponse(raw2, email);

      setProfile(prof2);
      setForm({
        name: prof2.name || "",
        email: prof2.email || email,
        business: prof2.business || prof2.businessName || "",
        type: prof2.businessType || "",
        location: prof2.location || "",
        teamSize:
          prof2.people ?? prof2.teamSize ?? prof2.team_size ?? prof2.teamSize === 0
            ? String(prof2.people ?? prof2.teamSize ?? prof2.team_size ?? "")
            : "",
      });

      try {
        localStorage.setItem("user", JSON.stringify(prof2));
      } catch {}
    } catch (err) {
      console.error("Failed to load profile:", err);
      setProfile(null);
      setBootError(String(err).slice(0, 1200));
    } finally {
      setBooting(false);
    }
  };

  useEffect(() => {
    loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.email]);

  useEffect(() => {
    const params = new URLSearchParams(search);
    if (params.get("stripe_connected") === "1") loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        email: form.email,
        name: form.name,
        logo: profile?.logo || "",
        businessType: form.type,
        business: form.business,
        businessName: form.business,
        location: form.location,
        people: form.teamSize,
        teamSize: form.teamSize,
      };

      // Try POST /api/profile first
      try {
        const url1 = apiUrl("profile");
        const raw1 = await fetchJSONStrict(url1, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const prof = normalizeProfileResponse(raw1, form.email);
        setProfile(prof);
        setForm((f) => ({
          ...f,
          name: prof.name || f.name,
          email: prof.email || f.email,
          business: prof.business || prof.businessName || f.business,
          type: prof.businessType || f.type,
          location: prof.location || f.location,
          teamSize: String(prof.people ?? prof.teamSize ?? f.teamSize ?? ""),
        }));
      } catch (e1) {
        // Fallback POST /api/user
        console.warn("POST /profile failed, trying POST /user:", e1);
        const url2 = apiUrl("user");
        const raw2 = await fetchJSONStrict(url2, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const prof = normalizeProfileResponse(raw2, form.email);
        setProfile(prof);
        setForm((f) => ({
          ...f,
          name: prof.name || f.name,
          email: prof.email || f.email,
          business: prof.business || prof.businessName || f.business,
          type: prof.businessType || f.type,
          location: prof.location || f.location,
          teamSize: String(prof.people ?? prof.teamSize ?? f.teamSize ?? ""),
        }));
      }

      setEditMode(false);

      // Optional: let parent refresh
      if (typeof refreshUser === "function") {
        try {
          await refreshUser();
        } catch {}
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

  if (booting || !profile) {
    return (
      <div className="settings-layout" style={{ left: leftOffset, width: settingsWidth }}>
        <div style={{ padding: 16, maxWidth: 900 }}>
          <div style={{ fontWeight: 900, marginBottom: 8, color: "#fff" }}>
            {booting ? "Loading Settings…" : "Settings couldn’t load"}
          </div>

          <div style={{ color: "#bbb", lineHeight: 1.5 }}>
            {booting
              ? "Fetching your profile and workspace data."
              : "Your profile request failed. This is usually an API routing / backend origin issue."}
          </div>

          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button
              className="btn"
              onClick={loadProfile}
              style={{ background: "#232323", color: "#fff", border: "1px solid #444" }}
            >
              Retry
            </button>
          </div>

          {bootError && (
            <pre
              style={{
                marginTop: 14,
                padding: 12,
                background: "#2a2a2e",
                borderRadius: 10,
                border: "1px solid #3a3a3f",
                color: "#ddd",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
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
        {TABS.map((t) => (
          <button
            key={t.key}
            className={tab === t.key ? "active" : ""}
            onClick={() => {
              setTab(t.key);
              setEditMode(false);
            }}
          >
            <span className="settings-icon">{t.icon}</span>
            <span className="settings-label">{t.label}</span>
          </button>
        ))}
      </nav>

      <main className="settings-content fade-in">
        {tab === "profile" && (
          <div className="profile-tab" style={{ maxWidth: MAX_W, margin: "0 auto" }}>
            <h2>Profile</h2>
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
                        value={form[name] || ""}
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
                          loadProfile();
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
                    <button className="btn btn-edit" onClick={() => setEditMode(true)}>
                      Edit Profile
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === "team" && (
          <TeamTab
            ownerEmail={profile.email}
            userEmail={user?.email || profile.email}
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

/* ─────────────────────────────────────────────────────────────── */
/* Team tab                                                        */
/* ─────────────────────────────────────────────────────────────── */

function TeamTab({ ownerEmail, userEmail, maxWidth }) {
  const [members, setMembers] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyEmail, setBusyEmail] = useState("");
  const [error, setError] = useState("");

  const roles = ["owner", "manager", "member"];

  const loadMembers = async () => {
    if (!ownerEmail) return;
    setLoading(true);
    setError("");
    try {
      const url = apiUrl(`team/members?ownerEmail=${encodeURIComponent(ownerEmail)}`);
      const data = await fetchJSONStrict(url, {},);

      if (Array.isArray(data?.members)) setMembers(data.members);
      else if (Array.isArray(data)) setMembers(data);
      else setMembers([]);
    } catch (e) {
      console.error("Load members failed:", e);
      setError(String(e).slice(0, 800));
      setMembers([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (ownerEmail) loadMembers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ownerEmail]);

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
      const url = apiUrl("team/role");
      await fetchJSONStrict(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, role, ownerEmail, userEmail }),
      });
    } catch (e) {
      alert("Could not change role. Make sure /api/team/role exists.");
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
      const url = apiUrl("team/remove");
      await fetchJSONStrict(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, ownerEmail, userEmail }),
      });
    } catch (e) {
      alert("Could not remove. Make sure /api/team/remove exists.");
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
        <div
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
          <div style={{ fontWeight: 900, marginBottom: 6 }}>
            Team API error (blocked / wrong route)
          </div>
          <pre style={{ margin: 0 }}>{error}</pre>
        </div>
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
            No members found (or access blocked).
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
              <div style={{ color: "#fff", fontWeight: 700 }}>{m.name || "—"}</div>
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