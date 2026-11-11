import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { GoogleLogin } from "@react-oauth/google";
import { jwtDecode } from "jwt-decode";
import logo from "../assets/logo.png";
import { API_BASE } from "../apiBase";
import "./signup.css";

const EMAIL_STEPS = ["email", "password", "name", "review"];
const GOOGLE_STEPS = ["email", "name", "review"];
const PASSWORD_HELP = "Use 12 or more characters with uppercase and lowercase letters, a number, and a symbol.";

function validPassword(value) {
  return value.length >= 12 && value.length <= 256 && /[a-z]/.test(value)
    && /[A-Z]/.test(value) && /[0-9]/.test(value) && /[^A-Za-z0-9]/.test(value);
}

export default function Signup() {
  const [step, setStep] = useState("email");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [name, setName] = useState("");
  const [googleCredential, setGoogleCredential] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const pending = useRef(false);
  const previousStep = useRef(step);
  const steps = googleCredential ? GOOGLE_STEPS : EMAIL_STEPS;
  const position = steps.indexOf(step);
  const validEmail = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) && email.trim().length <= 320;

  useEffect(() => {
    if (previousStep.current !== step) document.getElementById(`signup-${step}`)?.focus();
    previousStep.current = step;
  }, [step]);

  function changeStep(next) {
    setError("");
    setStep(next);
  }

  function handleGoogleSuccess(response) {
    try {
      const credential = response.credential;
      const preview = jwtDecode(credential);
      if (!preview.email) throw new Error("Missing email");
      // This is a form preview. The server verifies the signed token, audience,
      // issuer and verified email before it creates any account.
      setGoogleCredential(credential);
      setEmail(preview.email);
      setName(preview.name || "");
      setPassword("");
      changeStep("name");
    } catch {
      setError("Google sign-up did not finish. Try again or use your email.");
    }
  }

  function back() {
    const previous = steps[position - 1];
    if (previous === "email") setGoogleCredential("");
    changeStep(previous);
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (pending.current) return;
    setError("");
    if (!validEmail) {
      setStep("email");
      setError("Enter a valid email address.");
      return;
    }
    if (step === "email") return changeStep("password");
    if (!googleCredential && !validPassword(password)) {
      setStep("password");
      setError(PASSWORD_HELP);
      return;
    }
    if (step === "password") return changeStep("name");
    if (!name.trim() || name.trim().length > 120) {
      setStep("name");
      setError("Enter your name (120 characters or fewer).");
      return;
    }
    if (step === "name") return changeStep("review");
    if (!agree) return setError("Please agree to the Terms and Privacy Policy.");

    pending.current = true;
    setSubmitting(true);
    try {
      const response = await fetch(`${API_BASE}/api/auth/signup`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          name: name.trim(),
          ...(googleCredential ? { googleCredential } : { password }),
          termsAccepted: agree,
          termsVersion: "2026-09-13",
          privacyVersion: "2026-09-13",
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        if (data.code === "google_token_invalid") {
          setGoogleCredential("");
          setStep("email");
        }
        setError(data.error || "We could not create your account. Please try again.");
        return;
      }
      if (!data.checkoutUrl) throw new Error("checkout_missing");
      window.location.assign(data.checkoutUrl);
    } catch {
      setError("We could not open checkout. Please try again. Your trial starts only after checkout is complete.");
    } finally {
      pending.current = false;
      setSubmitting(false);
    }
  }

  return (
    <div className="signup-page">
      <header className="signup-header">
        <Link to="/" className="signup-brand" aria-label="RetainAI home">
          <img src={logo} alt="" width="30" height="30" />RetainAI
        </Link>
        <Link to="/login">Log in</Link>
      </header>
      <main className="signup-layout">
        <aside className="signup-intro" aria-label="Your RetainAI trial">
          <p className="signup-kicker">For Canadian service businesses</p>
          <p className="signup-intro-title">Keep up with your customers, without keeping it all in your head.</p>
          <p>Bring customer conversations, follow-ups and appointments into one workspace.</p>
          <ul>
            <li>See who needs attention and who is ready to rebook.</li>
            <li>Review and adjust AI drafts before you send them.</li>
            <li>Add your business details and import contacts after you sign in.</li>
          </ul>
          <p className="signup-help">Need a hand? <a href="mailto:owner@retainai.ca">Email Mateo at RetainAI</a>.</p>
        </aside>
        <section className="signup-card" aria-labelledby="signup-title">
          <p className="signup-kicker">Start your 14-day trial</p>
          <h1 id="signup-title">Create your account</h1>
          <p className="signup-progress" aria-live="polite">Step {position + 1} of {steps.length} · {step === "review" ? "Review your trial" : step === "name" ? "Your name" : step === "password" ? "Your password" : "Your email"}</p>
          <div className="signup-progress-track" aria-hidden="true"><span style={{ width: `${((position + 1) / steps.length) * 100}%` }} /></div>
          <form onSubmit={handleSubmit} noValidate>
            <fieldset disabled={submitting}>
              {step === "email" && <>
                <div className="signup-google">
                  <GoogleLogin onSuccess={handleGoogleSuccess} onError={() => setError("Google sign-up did not finish. Try again or use your email.")} text="signup_with" theme="filled_black" shape="rectangular" size="large" width="280" />
                </div>
                <p className="signup-divider">or use your email</p>
                <label htmlFor="signup-email">Email address</label>
                <input id="signup-email" type="email" inputMode="email" autoComplete="email" autoCapitalize="none" spellCheck="false" required maxLength={320} value={email} onChange={(event) => { setEmail(event.target.value); setGoogleCredential(""); }} placeholder="you@business.com" aria-describedby="signup-email-help" />
                <p id="signup-email-help" className="signup-hint">Use the email you want to sign in with.</p>
              </>}
              {step === "password" && <>
                <label htmlFor="signup-password">Create a password</label>
                <div className="signup-password">
                  <input id="signup-password" type={showPassword ? "text" : "password"} autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} aria-describedby="signup-password-help" />
                  <button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? "Hide" : "Show"}</button>
                </div>
                <p id="signup-password-help" className="signup-hint">{PASSWORD_HELP}</p>
              </>}
              {step === "name" && <>
                {googleCredential && <p className="signup-identity">Using Google: <strong>{email}</strong></p>}
                <label htmlFor="signup-name">Your name</label>
                <input id="signup-name" autoComplete="name" required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Your name" aria-describedby="signup-name-help" />
                <p id="signup-name-help" className="signup-hint">Business name, location, team size and your photo can wait until you’re inside.</p>
              </>}
              {step === "review" && <>
                <p className="signup-identity">Your account: <strong>{email}</strong></p>
                <div className="signup-trial">
                  <h2 id="signup-review" tabIndex={-1}>Full workspace for 14 days</h2>
                  <p><strong>C$20 per month after your trial.</strong> Confirm your total at checkout.</p>
                  <p>A payment method is required and kept on file by Stripe. Your trial starts after checkout. Cancel in Settings → Billing before it ends to avoid the subscription charge.</p>
                  <p>The trial is available once per customer. If you have already used it, checkout shows the subscription charge before you confirm.</p>
                  <p>After checkout, sign in and complete your business profile in Settings. You can import contacts and explore your workspace right away.</p>
                  {!googleCredential && <p>We’ll also send a link to verify your email.</p>}
                </div>
                <label className="signup-consent">
                  <input type="checkbox" checked={agree} onChange={(event) => setAgree(event.target.checked)} />
                  <span>I agree to the <Link to="/terms-of-service" target="_blank" rel="noopener noreferrer">Terms</Link> and <Link to="/privacy-policy" target="_blank" rel="noopener noreferrer">Privacy Policy</Link>.</span>
                </label>
              </>}
              {error && <p className="signup-error" role="alert">{error}</p>}
              <div className="signup-actions">
                {position > 0 && <button type="button" className="signup-back" onClick={back}>Back</button>}
                <button type="submit" className="signup-continue">{submitting ? "Opening secure checkout…" : step === "review" ? "Continue to Stripe checkout" : "Continue"}</button>
              </div>
            </fieldset>
          </form>
          {step !== "review" && <p className="signup-billing-note">C$20/month after 14 days. Payment method required at Stripe checkout. Cancel anytime in Settings → Billing.</p>}
          <p className="signup-login">Already have an account? <Link to="/login">Log in</Link></p>
        </section>
      </main>
    </div>
  );
}
