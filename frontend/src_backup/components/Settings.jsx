// File: frontend/src/components/Settings.jsx
import React, { useState, useEffect, useMemo } from "react";
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

/* ───────────────────────────────────────────────────────────────
   RUNTIME API BASE AUTO-DISCOVERY (PROD-SAFE)

   Key issue you hit:
   - If the frontend uses relative /api/... OR "sameOrigin" is chosen as API base,
     you will call the FRONTEND service which returns SPA HTML → "Expected JSON..."

   Hardening rules:
   - In production (onrender.com), NEVER choose window.location.origin as API.
   - Prefer ENV base if present (REACT_APP_API_BASE or VITE_API_BASE).
   - Try Render "sibling" backend origin (strip -frontend / -<digits>).
   - Probe /api/health accepting JSON OR text containing "ok".
   - Cache only a non-frontend origin.
   ─────────────────────────────────────────────────────────────── */

const ENV_BASE =
  (typeof import.meta !== "undefined" &&
    import.meta.env &&
    import.meta.env.VITE_API_BASE) ||
  (typeof process !== "undefined" &&
    process.env &&
    (process.env.REACT_APP_API_BASE || process.env.REACT_APP_API_URL)) ||
  "";

// "https://x/api" -> "https://x"
function cleanOrigin(s) {
  return (s || "").trim().replace(/\/+$/g, "").replace(/\/api$/i, "");
}

function isOnRenderHost() {
  try {
    return String(window.location.hostname || "").toLowerCase().includes("onrender.com");
  } catch {
    return false;
  }
}

function isFrontendOrigin(origin) {
  const o = String(origin || "").toLowerCase();
  // common patterns
  return o.includes("-frontend.onrender.com") || o.includes("frontend.onrender.com");
}

// Convert "retainai-prod-1-frontend.onrender.com" -> "retainai-prod.onrender.com" (best effort)
function siblingRenderOrigin() {
  try {
    const o = window.location.origin;
    return o
      // remove "-frontend"
      .replace(/-frontend(\.onrender\.com)$/i, "$1")
      // remove "-<digits>" that some render services append
      .replace(/-\d+(\.onrender\.com)$/i, "$1");
  } catch {
    return "";
  }
}

// Probe /api/health. Accepts JSON OR text containing "ok".
async function probe(origin) {
  if (!origin) return null;
  const base = origin.replace(/\/+$/, "");
  const url = `${base}/api/health`;

  try {
    const r = await fetch(url, { credentials: "omit" }); // keep simple for probe
    if (!r.ok) return null;

    const ct = (r.headers.get("content-type") || "").toLowerCase();

    if (ct.includes("application/json")) {
      await r.json();
      return base;
    }

    const t = await r.text();
    if (String(t || "").toLowerCase().includes("ok")) return base;

    return null;
  } catch {
    return null;
  }
}

async function getWorkingApiOrigin() {
  const env = cleanOrigin(ENV_BASE);
  const sib = cleanOrigin(siblingRenderOrigin());

  // reuse if cached
  try {
    const cached = sessionStorage.getItem("__api_origin__");
    if (cached && !isFrontendOrigin(cached)) return cached;
  } catch {
    // ignore
  }

  const prod = isOnRenderHost();

  // In prod: DO NOT try same-origin (frontend) as API base.
  // In dev: allow same-origin for proxy setups.
  const sameOrigin = (() => {
    try {
      return cleanOrigin(window.location.origin);
    } catch {
      return "";
    }
  })();

  const candidates = [
    env,
    sib,
    ...(prod ? [] : [sameOrigin]),
  ].filter(Boolean);

  for (const c of candidates) {
    const ok = await probe(c);
    if (ok) {
      // never cache frontend origin
      if (!isFrontendOrigin(ok)) {
        try {
          sessionStorage.setItem("__api_origin__", ok);
        } catch {
          // ignore
        }
      }
      return ok;
    }
  }

  // fallback rules:
  // If ENV is set, prefer it (even if probe failed) — it's explicit.
  if (env) return env;
  // else sibling if present
  if (sib) return sib;
  // dev-only fallback
  return sameOrigin || "";
}

// Build full URL for API call
async function apiUrl(path) {
  const origin = await getWorkingApiOrigin();
  const p = String(path || "").replace(/^\/+/, "");
  if (/^https?:\/\//i.test(p)) return p;
  return `${origin.replace(/\/+$/, "")}/api/${p}`;
}

/* ───────────────────────────────────────────────────────────────
   Robust JSON fetcher + auth helper
   - Protects against SPA HTML responses.
   - Retries once with legacy headers if 401/403.
   ─────────────────────────────────────────────────────────────── */

function getStoredToken() {
  try {
    const ls = window.localStorage;
    const direct =
      ls.getItem("token") ||
      ls.getItem("access_token") ||
      ls.getItem("auth_token");
    if (direct) return direct;

    const userRaw = ls.getItem("user");
    if (userRaw) {
      const u = JSON.parse(userRaw);
      return u?.token || u?.access_token || u?.auth_token || "";
    }
  } catch {
    // ignore
  }
  return "";
}

function baseHeaders(extra = {}) {
  const token = getStoredToken();
  const h = { Accept: "application/json", ...(extra || {}) };
  if (token && !h.Authorization) h.Authorization = `Bearer ${token}`;
  return h;
}

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, {
    credentials: "include",
    ...opts,
    headers: baseHeaders(opts.headers || {}),
  });

  const ct = (res.headers.get("content-type") || "").toLowerCase();
  const raw = await res.text();

  if (!res.ok) {
    throw new Error(
      `HTTP ${res.status} ${res.statusText} @ ${url}\n${raw.slice(0, 400)}`
    );
  }

  if (!ct.includes("application/json")) {
    if (raw.toLowerCase().includes("<!doctype html") || raw.includes("</html>")) {
      throw new Error(
        `Expected JSON but got HTML (SPA fallback) @ ${url}\nLikely wrong API base.`
      );
    }
    throw new Error(
      `Expected JSON but got ${ct || "unknown content-type"} @ ${url}\n${raw.slice(
        0,
        200
      )}`
    );
  }

  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`Failed to parse JSON @ ${url}: ${e}\n${raw.slice(0, 200)}`);
  }
}

async function apiFetchJSON(path, opts = {}, authContext = {}) {
  const url = await apiUrl(path);

  try {
    return await fetchJSON(url, opts);
  } catch (err) {
    const msg = String(err || "");
    if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
      const ownerEmail = authContext?.ownerEmail || "";
      const userEmail = authContext?.userEmail || ownerEmail || "";

      // Retry once with common headers some Flask apps expect
      const retryHeaders = {
        ...(opts.headers || {}),
        "X-User-Email": userEmail || "",
        "X-Owner-Email": ownerEmail || userEmail || "",
        "X-Auth-Email": userEmail || "", // legacy
      };

      if (ownerEmail || userEmail) {
        return await fetchJSON(url, { ...opts, headers: retryHeaders });
      }
    }
    throw err;
  }
}

/* ───────────────────────────────────────────────────────────────
   Helpers
   ─────────────────────────────────────────────────────────────── */

function normalizeProfileResponse(raw, fallbackEmail) {
  const base = (raw && (raw.profile || raw.user || raw)) || {};
  const out = { ...base };
  if (!out.email && fallbackEmail) out.email = fallbackEmail;
  if (!out.business && out.businessName) out.business = out.businessName;
  if (!out.businessName && out.business) out.businessName = out.business;
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

  const loadProfile = async () => {
    try {
      setBootError("");
      setBooting(true);

      if (!user?.email) {
        setProfile(null);
        setBootError("No user email found. Please sign in again.");
        return;
      }

      const raw = await apiFetchJSON(
        `profile?email=${encodeURIComponent(user.email)}`
      );

      const prof = normalizeProfileResponse(raw, user.email);

      setProfile(prof);
      setForm({
        name: prof.name || "",
        email: prof.email || "",
        business: prof.business || prof.businessName || "",
        type: prof.businessType || "",
        location: prof.location || "",
        teamSize: prof.people || prof.teamSize || prof.teamSize === 0 ? prof.teamSize : "",
      });

      try {
        localStorage.setItem("user", JSON.stringify(prof));
      } catch {
        // ignore
      }
    } catch (err) {
      console.error("Failed to load profile:", err);
      setBootError(String(err).slice(0, 900));
      setProfile(null);
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

      const raw = await apiFetchJSON("profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const prof = normalizeProfileResponse(raw, form.email);
      setProfile(prof);
      setForm((f) => ({
        ...f,
        name: prof.name || f.name,
        email: prof.email || f.email,
        business: prof.business || prof.businessName || f.business,
        type: prof.businessType || f.type,
        location: prof.location || f.location,
        teamSize: prof.people || prof.teamSize || f.teamSize,
      }));
      setEditMode(false);
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
              : "Your profile request failed. This is usually a session/auth or API base issue."}
          </div>

          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button
              className="btn"
              onClick={async () => {
                try {
                  sessionStorage.removeItem("__api_origin__");
                } catch {}
                await loadProfile();
              }}
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
            apiFetchJSON={apiFetchJSON}
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
              <a href="mailto:owner@retainai.ca">owner@retainai.ca</a> or see our{" "}
              <a href="https://docs.retainai.ca" target="_blank" rel="noreferrer">
                documentation
              </a>
              .
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
function TeamTab({ ownerEmail, userEmail, maxWidth, apiFetchJSON }) {
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
      const data = await apiFetchJSON(
        `team/members?ownerEmail=${encodeURIComponent(ownerEmail)}`,
        {},
        { ownerEmail, userEmail }
      );

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
      await apiFetchJSON(
        "team/role",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, role, ownerEmail }),
        },
        { ownerEmail, userEmail }
      );
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
      await apiFetchJSON(
        "team/remove",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, ownerEmail }),
        },
        { ownerEmail, userEmail }
      );
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
            Team API error (blocked / unauthorized)
          </div>
          <div style={{ color: "#bbb", marginBottom: 10 }}>
            If profile loads but team fails, your backend likely enforces extra auth
            on team routes. Our client retries with common headers.
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
