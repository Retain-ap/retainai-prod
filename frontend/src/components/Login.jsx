// src/components/Login.jsx
import React, { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { GoogleLogin } from "@react-oauth/google";
import logo from "../assets/logo.png";
import defaultAvatar from "../assets/default-avatar.png";
import { API_BASE, apiUrl } from "../apiBase";

// ---- Theme ----
const BG = {
  page: "#0B0C0E",
  card: "#15171B",
  line: "#24262B",
  gold: "#F5D87E",
  goldDeep: "#D7BB66",
  text60: "rgba(255,255,255,.60)",
  text80: "rgba(255,255,255,.80)",
};

// Small input
function Input({
  type = "text",
  value,
  onChange,
  placeholder,
  onKeyDown,
  rightEl,
  autoComplete,
}) {
  return (
    <div style={{ position: "relative" }}>
      <input
        type={type}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoComplete={autoComplete}
        style={{
          width: "100%",
          padding: "12px 14px",
          paddingRight: rightEl ? 54 : 14,
          borderRadius: 12,
          border: `1px solid ${BG.line}`,
          background: "#0E1013",
          color: "#fff",
          outline: "none",
          fontSize: 16,
        }}
      />
      {rightEl ? (
        <div
          style={{
            position: "absolute",
            right: 10,
            top: "50%",
            transform: "translateY(-50%)",
          }}
        >
          {rightEl}
        </div>
      ) : null}
    </div>
  );
}

function normEmail(e) {
  return (e || "").trim().toLowerCase();
}

function normalizeUserForStorage(u = {}, fallbackEmail = "") {
  return {
    email: u.email || normEmail(fallbackEmail),
    name: u.name || "",
    logo: u.logo || defaultAvatar,

    businessType: u.businessType || u.lineOfBusiness || "",
    business: u.business || u.businessName || "",
    businessName: u.businessName || u.business || "",
    location: u.location || "",

    people:
      u.people !== undefined && u.people !== null && u.people !== ""
        ? u.people
        : u.teamSize ?? "",
    teamSize:
      u.teamSize !== undefined && u.teamSize !== null && u.teamSize !== ""
        ? u.teamSize
        : u.people ?? "",

    status: u.status || "",

    stripe_connected: Boolean(u.stripe_connected),
    stripe_account_id: u.stripe_account_id || "",

    gcal_connected: Boolean(u.gcal_connected),
    gcal_calendars: Array.isArray(u.gcal_calendars) ? u.gcal_calendars : [],

    role: u.role || "",
    org_id: u.org_id || "",
    orgOwnerEmail: u.orgOwnerEmail || "",

    canInviteTeam: Boolean(u.canInviteTeam),
    canEditBusiness: Boolean(u.canEditBusiness),
    canManageBilling: Boolean(u.canManageBilling),
    platformOwner: Boolean(u.platformOwner),
    trialActive: Boolean(u.trialActive),
    trialDaysRemaining: Number(u.trialDaysRemaining || 0),
    trialEndsAt: u.trialEndsAt || "",
    billingRequired: Boolean(u.billingRequired),
  };
}

function persistUser(u, remember) {
  const normalized = normalizeUserForStorage(u, u?.email || "");
  localStorage.setItem("user", JSON.stringify(normalized));
  localStorage.setItem("userEmail", normalized.email || "");

  if (remember) {
    localStorage.setItem("rememberEmail", normalized.email || "");
    localStorage.setItem("rememberFlag", "1");
  } else {
    localStorage.removeItem("rememberEmail");
    localStorage.setItem("rememberFlag", "0");
  }
}

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [remember, setRemember] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [billingState, setBillingState] = useState(null);
  const [resetToken] = useState(
    () => new URLSearchParams(window.location.search).get("reset_token") || ""
  );
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const navigate = useNavigate();

  // Authentication cookies are first-party when the public frontend and API
  // share retainai.ca. Render's temporary hostname makes the API cookie
  // cross-site and some browsers block it, even after a valid password.
  useEffect(() => {
    const host = String(window.location.hostname || "").toLowerCase();
    if (host === "retainai-prod-1-frontend.onrender.com") {
      window.location.replace(
        `https://www.retainai.ca${window.location.pathname}${window.location.search}${window.location.hash}`
      );
    }
  }, []);

  async function enterWorkspace(user, fallbackEmail = "") {
    const sessionResponse = await fetch(apiUrl("session"), {
      credentials: "include",
      cache: "no-store",
    });
    const sessionData = await sessionResponse.json().catch(() => ({}));
    if (!sessionResponse.ok || !sessionData?.authenticated || !sessionData?.user) {
      throw new Error(
        "Your sign-in was accepted, but the secure session could not be verified. Open www.retainai.ca/login and try again."
      );
    }
    persistUser(
      normalizeUserForStorage(sessionData.user || user || {}, fallbackEmail),
      remember
    );
    navigate("/app", { replace: true });
  }

  // Prefill remembered email
  useEffect(() => {
    const saved = localStorage.getItem("rememberEmail");
    if (saved) setEmail(saved);

    const savedFlag = localStorage.getItem("rememberFlag");
    if (savedFlag) setRemember(savedFlag === "1");
    if (new URLSearchParams(window.location.search).get("password_reset") === "success") {
      setError("Password updated. Sign in with your new password.");
      window.history.replaceState({}, "", "/login");
    }
  }, []);

  const handleForgot = async () => {
    const cleanedEmail = normEmail(email);
    if (!cleanedEmail) {
      setError("Enter your account email first.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch(apiUrl("auth/password/forgot"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: cleanedEmail }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Could not request a reset link.");
      setError(data.message || "Check your email for a secure reset link.");
    } catch (requestError) {
      setError(requestError.message || "Could not request a reset link.");
    } finally {
      setSubmitting(false);
    }
  };

  const handlePasswordReset = async (event) => {
    event.preventDefault();
    setError("");
    if (newPassword.length < 12) {
      setError("Use at least 12 characters for your new password.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetch(apiUrl("auth/password/reset"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: resetToken, password: newPassword }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Could not reset your password.");
      window.location.assign("/login?password_reset=success");
    } catch (requestError) {
      setError(requestError.message || "Could not reset your password.");
      setSubmitting(false);
    }
  };

  // ---- Google OAuth handler ----
  const handleGoogleSuccess = async (credentialResponse) => {
    setSubmitting(true);
    setError("");

    try {
      const token = credentialResponse.credential;

      const res = await fetch(`${API_BASE}/api/oauth/google`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: token, remember }),
      });

      const data = await res.json();

      if (res.status === 202 && data.mfaRequired) {
        setMfaRequired(true);
        setSubmitting(false);
        return;
      }
      if (!res.ok) {
        if (res.status === 404) {
          setError("No account found for this Google email. Please sign up first.");
        } else if ((res.status === 402 || res.status === 403) && (data.code === "billing_required" || data.account)) {
          setBillingState(data.account || {});
          setError(data.error || "Your trial has ended. Choose a plan to restore access.");
        } else {
          setError(data.error || "Google login failed.");
        }
        setSubmitting(false);
        return;
      }

      await enterWorkspace(data.user || {}, data.user?.email || "");
    } catch (requestError) {
      setError(requestError.message || "Google login error.");
      setSubmitting(false);
    }
  };

  // Email/password login
  async function handleLogin(e) {
    e.preventDefault();
    if (submitting) return;

    setError("");
    setBillingState(null);

    if (!email || !password) {
      setError("All fields required.");
      return;
    }

    setSubmitting(true);

    try {
      const cleanedEmail = normEmail(email);

      const res = await fetch(`${API_BASE}/api/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: cleanedEmail, password, remember }),
      });

      const data = await res.json();

      if (res.status === 202 && data.mfaRequired) {
        setMfaRequired(true);
        setSubmitting(false);
        return;
      }
      if (res.status === 402 && data.code === "billing_required") {
        setBillingState(data.account || {});
        setError(data.error || "Your trial has ended.");
        setSubmitting(false);
        return;
      }
      if (!res.ok) {
        setError(data.error || "Login failed.");
        setSubmitting(false);
        return;
      }

      await enterWorkspace(data.user || {}, cleanedEmail);
    } catch (requestError) {
      setError(requestError.message || "Login error.");
      setSubmitting(false);
    }
  }

  async function continueToCheckout() {
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch(email && password ? `${API_BASE}/api/login` : apiUrl("billing/checkout"), {
        method: "POST",
        credentials: "include",
        headers: email && password ? { "Content-Type": "application/json" } : undefined,
        body: email && password
          ? JSON.stringify({ email: normEmail(email), password, remember })
          : undefined,
      });
      const data = await response.json().catch(() => ({}));
      const checkoutUrl = data.url || data.account?.checkoutUrl;
      if ((!response.ok && response.status !== 402) || !checkoutUrl) {
        throw new Error(data.error || "Secure checkout is temporarily unavailable.");
      }
      window.location.assign(checkoutUrl);
    } catch (checkoutError) {
      setError(checkoutError.message || "Secure checkout is temporarily unavailable.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleMfa(e) {
    e.preventDefault();
    if (submitting || !mfaCode.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch(apiUrl("auth/2fa/verify-login"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: mfaCode.trim() }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Verification failed.");
      await enterWorkspace(data.user || {}, email);
    } catch (requestError) {
      setError(requestError.message || "Verification failed.");
      setSubmitting(false);
    }
  }

  const onEnter = (e, fn) => {
    if (e.key === "Enter") fn(e);
  };

  // ---------- UI ----------
  return (
    <div style={{ minHeight: "100vh", background: BG.page, color: "#fff" }}>
      {/* gold glows */}
      <div
        aria-hidden
        style={{
          position: "fixed",
          inset: 0,
          pointerEvents: "none",
          zIndex: 0,
        }}
      >
        <div
          style={{
            position: "absolute",
            top: -240,
            right: -200,
            width: 900,
            height: 900,
            borderRadius: "9999px",
            filter: "blur(140px)",
            opacity: 0.2,
            background: BG.gold,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: "35%",
            left: "50%",
            transform: "translateX(-50%)",
            width: "70vw",
            height: "60vh",
            borderRadius: "9999px",
            filter: "blur(120px)",
            opacity: 0.1,
            background: `linear-gradient(90deg, ${BG.gold}, transparent)`,
          }}
        />
      </div>

      {/* top bar */}
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 5,
          background: "#0C0D10",
          borderBottom: `1px solid ${BG.line}`,
        }}
      >
        <div
          style={{
            maxWidth: 1120,
            margin: "0 auto",
            padding: "12px 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <img
              src={logo}
              alt="RetainAI"
              style={{ width: 28, height: 28, borderRadius: 6 }}
            />
            <span style={{ color: BG.gold, fontWeight: 900, letterSpacing: 0.2 }}>
              RetainAI
            </span>
          </div>

          <div style={{ fontSize: 13, color: BG.text60 }}>
            New here?{" "}
            <Link
              to="/signup"
              style={{ color: BG.goldDeep, textDecoration: "underline" }}
            >
              Create account
            </Link>
          </div>
        </div>
      </div>

      {/* content */}
      <div
        style={{
          position: "relative",
          zIndex: 1,
          maxWidth: 1120,
          margin: "0 auto",
          padding: "64px 24px",
          display: "grid",
          gridTemplateColumns: "1fr 460px",
          gap: 24,
        }}
      >
        {/* left brand card */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 24,
            border: `1px solid ${BG.line}`,
            background:
              "radial-gradient(1200px 800px at -10% 100%, rgba(245,216,126,.12), transparent 60%), #101216",
            minHeight: 520,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <img
              src={logo}
              alt="RetainAI"
              style={{
                width: 84,
                height: 84,
                borderRadius: 18,
                background: "#111",
                objectFit: "cover",
              }}
            />
            <div>
              <div
                style={{
                  fontSize: 40,
                  fontWeight: 900,
                  letterSpacing: 0.4,
                  color: BG.gold,
                }}
              >
                RetainAI
              </div>
              <div style={{ color: BG.text80, marginTop: 6, fontSize: 16 }}>
                Client relationships. Done right.
              </div>
            </div>
          </div>
        </div>

        {/* right login card */}
        <div
          style={{
            borderRadius: 24,
            border: `1px solid ${BG.line}`,
            background: BG.card,
            padding: 28,
            minHeight: 520,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
          }}
        >
          <h2
            style={{
              color: BG.gold,
              fontWeight: 800,
              fontSize: 28,
              marginBottom: 12,
            }}
          >
            {resetToken ? "Choose a new password" : "Welcome back"}
          </h2>

          <form onSubmit={resetToken ? handlePasswordReset : (mfaRequired ? handleMfa : handleLogin)}>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {resetToken ? (
                <>
                  <div style={{ color: BG.text80, lineHeight: 1.6 }}>
                    Use at least 12 characters. This secure link can only be used once.
                  </div>
                  <Input
                    type={showPw ? "text" : "password"}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="New password"
                    autoComplete="new-password"
                  />
                  <Input
                    type={showPw ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm new password"
                    autoComplete="new-password"
                  />
                  <label style={{ color: BG.text80, fontSize: 14 }}>
                    <input
                      type="checkbox"
                      checked={showPw}
                      onChange={(e) => setShowPw(e.target.checked)}
                      style={{ accentColor: BG.gold, marginRight: 8 }}
                    />
                    Show passwords
                  </label>
                </>
              ) : mfaRequired ? (
                <>
                  <div style={{ color: BG.text80, lineHeight: 1.6 }}>
                    Enter the current code from your authenticator app, or use
                    one of your RetainAI recovery codes.
                  </div>
                  <Input
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value)}
                    placeholder="Six-digit or recovery code"
                    autoComplete="one-time-code"
                  />
                </>
              ) : (
                <>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => onEnter(e, handleLogin)}
                placeholder="Email"
                autoComplete="username"
              />

              <Input
                type={showPw ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => onEnter(e, handleLogin)}
                placeholder="Password"
                autoComplete="current-password"
                rightEl={
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    style={{
                      fontSize: 12,
                      color: BG.text60,
                      background: "transparent",
                      border: 0,
                      cursor: "pointer",
                    }}
                    aria-label={showPw ? "Hide password" : "Show password"}
                  >
                    {showPw ? "Hide" : "Show"}
                  </button>
                }
              />

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginTop: 2,
                }}
              >
                <label
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    color: BG.text80,
                    fontSize: 14,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                    style={{ accentColor: BG.gold }}
                  />
                  Remember me
                </label>

                <button
                  type="button"
                  onClick={handleForgot}
                  style={{
                    color: BG.goldDeep,
                    fontSize: 14,
                    textDecoration: "underline",
                    background: "transparent",
                    border: 0,
                    cursor: "pointer",
                  }}
                >
                  Forgot password?
                </button>
              </div>
                </>
              )}

              {error && (
                <div
                  style={{
                    background: "#1a1306",
                    border: "1px solid #6b4e00",
                    color: BG.gold,
                    borderRadius: 10,
                    padding: "8px 10px",
                    fontSize: 14,
                  }}
                >
                  {error}
                </div>
              )}

              {billingState && (
                <div
                  style={{
                    border: `1px solid ${BG.goldDeep}`,
                    borderRadius: 12,
                    padding: 14,
                    background: "rgba(245,216,126,.08)",
                  }}
                >
                  <strong style={{ color: BG.gold }}>Your data is safe.</strong>
                  <p style={{ color: BG.text80, margin: "8px 0 12px", lineHeight: 1.5 }}>
                    Choose a plan to restore your workspace and continue where
                    you left off.
                  </p>
                  {billingState.checkoutUrl ? (
                    <a
                      href={billingState.checkoutUrl}
                      style={{
                        display: "block",
                        textAlign: "center",
                        background: BG.gold,
                        color: "#0B0B0C",
                        borderRadius: 10,
                        padding: "11px 14px",
                        fontWeight: 900,
                        textDecoration: "none",
                      }}
                    >
                      Continue to secure checkout
                    </a>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={continueToCheckout}
                        disabled={submitting}
                        style={{
                          width: "100%",
                          textAlign: "center",
                          background: BG.gold,
                          color: "#0B0B0C",
                          border: 0,
                          borderRadius: 10,
                          padding: "11px 14px",
                          fontWeight: 900,
                        }}
                      >
                        {submitting ? "Opening secure checkout…" : "Choose a plan and continue"}
                      </button>
                      <small style={{ display: "block", color: BG.text60, marginTop: 10 }}>
                        {billingState.billingError || "You can review the plan and price before paying."}
                      </small>
                    </>
                  )}
                </div>
              )}

              <button
                type="submit"
                disabled={
                  submitting ||
                  (resetToken
                    ? !newPassword || !confirmPassword
                    : mfaRequired ? !mfaCode.trim() : !email || !password)
                }
                style={{
                  background: BG.gold,
                  color: "#0B0B0C",
                  fontWeight: 800,
                  border: 0,
                  borderRadius: 12,
                  padding: "12px 0",
                  fontSize: 16,
                  cursor: submitting ? "not-allowed" : "pointer",
                  opacity:
                    submitting ||
                    (resetToken
                      ? !newPassword || !confirmPassword
                      : mfaRequired ? !mfaCode.trim() : !email || !password)
                      ? 0.7
                      : 1,
                }}
              >
                {submitting
                  ? (resetToken ? "Updating password…" : "Signing in…")
                  : (resetToken ? "Update password" : "Login")}
              </button>

              {!resetToken && (
                <>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  color: BG.text60,
                  fontWeight: 700,
                  fontSize: 14,
                  margin: "6px 0",
                }}
              >
                <div style={{ flex: 1, borderBottom: `1px solid ${BG.line}` }} />
                <span>or</span>
                <div style={{ flex: 1, borderBottom: `1px solid ${BG.line}` }} />
              </div>

              <GoogleLogin
                onSuccess={handleGoogleSuccess}
                onError={() => setError("Google Login Failed")}
                width="370"
                shape="pill"
                theme="filled_black"
                text="signin_with"
              />
                </>
              )}

              <div
                style={{
                  marginTop: 8,
                  textAlign: "center",
                  color: BG.text60,
                  fontSize: 12,
                }}
              >
                We’ll never post or share without permission.
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
