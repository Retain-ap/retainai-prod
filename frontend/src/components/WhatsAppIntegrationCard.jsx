import React, { useEffect, useMemo, useState } from "react";
import { SiWhatsapp } from "react-icons/si";
import { API_BASE } from "../config";

// Add any country codes you want here
const COUNTRIES = [
  { code: "+1", name: "USA/Canada" },
  { code: "+44", name: "UK" },
  { code: "+61", name: "Australia" },
  { code: "+91", name: "India" },
  { code: "+49", name: "Germany" },
  { code: "+33", name: "France" },
  { code: "+34", name: "Spain" },
  { code: "+39", name: "Italy" },
  { code: "+81", name: "Japan" },
  { code: "+55", name: "Brazil" },
];

function splitCountry(number) {
  for (const c of COUNTRIES) {
    if (number?.startsWith(c.code)) {
      return { country: c.code, number: number.slice(c.code.length) };
    }
  }
  return { country: "+1", number: number?.replace(/^\+?1/, "") || "" };
}

function formatPhone(raw, country = "+1") {
  if (country === "+1" && /^\+1\d{10}$/.test(raw)) {
    const digits = raw.slice(2);
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }

  if (/^\+\d{7,15}$/.test(raw)) {
    const countryLen = country.length;
    let groups = [];
    let n = raw.slice(countryLen);

    while (n.length > 0) {
      if (n.length > 4) {
        groups.push(n.slice(0, 3));
        n = n.slice(3);
      } else {
        groups.push(n);
        n = "";
      }
    }

    return `${country} ${groups.join(" ")}`;
  }

  return raw;
}

export default function WhatsAppIntegrationCard({ user }) {
  const API = useMemo(() => {
    const env = (v) => (v && v.trim()) || "";
    const fromEnv =
      env(process.env.REACT_APP_API_URL) ||
      env(process.env.REACT_APP_API_BASE);

    if (fromEnv) return fromEnv.replace(/\/$/, "");
    return API_BASE;
  }, []);

  const [loading, setLoading] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [country, setCountry] = useState("+1");
  const [number, setNumber] = useState("");
  const [savedNumber, setSavedNumber] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    async function fetchWhatsApp() {
      if (!user?.email) return;

      setLoading(true);
      setError("");
      setSuccess("");

      try {
        const res = await fetch(`${API}/api/user/${encodeURIComponent(user.email)}`);
        if (!res.ok) throw new Error("Failed to fetch user");

        const data = await res.json();
        const wa = data?.whatsapp || "";

        setSavedNumber(wa);

        if (wa) {
          const parsed = splitCountry(wa);
          setCountry(parsed.country);
          setNumber(parsed.number);
        } else {
          setCountry("+1");
          setNumber("");
        }
      } catch (e) {
        setError("Failed to load WhatsApp number.");
      } finally {
        setLoading(false);
      }
    }

    fetchWhatsApp();
  }, [API, user?.email]);

  async function handleSave(e) {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (!number || !/^\d{7,15}$/.test(number)) {
      setError("Enter a valid phone number using 7–15 digits.");
      return;
    }

    setLoading(true);
    const fullNumber = `${country}${number}`;

    try {
      const res = await fetch(`${API}/api/integrations/whatsapp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: user.email, whatsapp: fullNumber }),
      });

      if (!res.ok) throw new Error("Save failed");

      setSavedNumber(fullNumber);
      setEditMode(false);
      setSuccess("WhatsApp number saved.");
    } catch (e) {
      setError("Failed to save WhatsApp number.");
    } finally {
      setLoading(false);
    }
  }

  async function handleDisconnect() {
    setLoading(true);
    setError("");
    setSuccess("");

    try {
      const res = await fetch(`${API}/api/integrations/whatsapp`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: user.email }),
      });

      if (!res.ok) throw new Error("Failed to disconnect");

      setSavedNumber("");
      setNumber("");
      setCountry("+1");
      setEditMode(false);
      setSuccess("WhatsApp number removed.");
    } catch (e) {
      setError("Failed to disconnect WhatsApp number.");
    } finally {
      setLoading(false);
    }
  }

  function handleCancel(e) {
    e.preventDefault();
    setEditMode(false);
    setError("");
    setSuccess("");

    const parsed = splitCountry(savedNumber);
    setCountry(parsed.country);
    setNumber(parsed.number);
  }

  return (
    <div
      className="integration-card"
      style={{
        minWidth: 320,
        maxWidth: 380,
        alignItems: "center",
      }}
    >
      <span style={{ fontSize: 32, color: "#25D366", marginBottom: 10 }}>
        <SiWhatsapp className="integration-icon whatsapp" />
      </span>

      <div className="integration-center" style={{ width: "100%", alignItems: "center" }}>
        <div className="integration-title" style={{ marginBottom: 4 }}>
          WhatsApp
        </div>

        <div className="integration-desc" style={{ marginBottom: 12, textAlign: "center", lineHeight: 1.45 }}>
          {savedNumber
            ? "Your business WhatsApp number is saved for messaging setup."
            : "Add the business WhatsApp number you want to use with your messaging setup."}
        </div>

        <div
          style={{
            width: "100%",
            background: "#1b1d20",
            border: "1px solid #2b2f33",
            borderRadius: 10,
            padding: "10px 12px",
            marginBottom: 14,
            color: "#9aa3ab",
            fontSize: 12,
            lineHeight: 1.45,
          }}
        >
          This saves your business WhatsApp number in RetainAI. Your WhatsApp templates and sending still depend on your Meta WhatsApp Cloud API setup.
        </div>

        {savedNumber && !editMode ? (
          <div
            style={{
              color: "#25D366",
              fontWeight: 700,
              fontSize: 17,
              marginBottom: 14,
              letterSpacing: "0.01em",
            }}
          >
            <span
              style={{
                background: "#232323",
                padding: "8px 18px",
                borderRadius: 8,
                fontWeight: 900,
                fontSize: 17,
                border: "1.5px solid #25D366",
                display: "inline-block",
              }}
            >
              {formatPhone(savedNumber, splitCountry(savedNumber).country)}
            </span>
          </div>
        ) : null}

        {editMode ? (
          <form style={{ width: "100%", marginBottom: 12 }} onSubmit={handleSave}>
            <div style={{ color: "#9aa3ab", fontSize: 12, marginBottom: 8 }}>
              Enter the full number without spaces or symbols in the number field.
            </div>

            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <select
                value={country}
                onChange={(e) => {
                  setCountry(e.target.value);
                  setNumber("");
                }}
                style={{
                  fontSize: 15,
                  borderRadius: 6,
                  padding: "7px 10px",
                  border: "1.7px solid #25D366",
                  background: "#191a1d",
                  color: "#fff",
                  flex: "0 0 120px",
                }}
                disabled={loading}
              >
                {COUNTRIES.map((c) => (
                  <option value={c.code} key={c.code}>
                    {c.name} ({c.code})
                  </option>
                ))}
              </select>

              <input
                type="tel"
                className="field-input"
                placeholder="Phone number"
                style={{
                  padding: "10px 16px",
                  width: "100%",
                  borderRadius: 7,
                  border: "1.7px solid #25D366",
                  fontSize: 17,
                  color: "#fff",
                  background: "#191a1d",
                }}
                value={number}
                onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))}
                disabled={loading}
                autoFocus
                maxLength={15}
              />
            </div>

            <div
              style={{
                background: "#141618",
                border: "1px solid #2b2f33",
                borderRadius: 8,
                padding: "8px 10px",
                color: "#f3f4f5",
                fontSize: 13,
                marginBottom: 10,
              }}
            >
              Preview: <span style={{ color: "#25D366", fontWeight: 800 }}>{country}{number || "…"}</span>
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
              <button
                className="integration-btn"
                style={{ background: "#25D366", color: "#232323", flex: 1 }}
                type="submit"
                disabled={loading}
              >
                {loading ? "Saving..." : "Save"}
              </button>

              <button
                className="integration-btn-outline"
                onClick={handleCancel}
                style={{ flex: 1 }}
                disabled={loading}
                type="button"
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div style={{ display: "flex", gap: 10, width: "100%" }}>
            {savedNumber ? (
              <>
                <button
                  className="integration-btn"
                  style={{ background: "#25D366", color: "#232323", flex: 1 }}
                  onClick={() => {
                    setEditMode(true);
                    setError("");
                    setSuccess("");
                  }}
                  disabled={loading}
                >
                  Edit
                </button>

                <button
                  className="integration-btn-outline"
                  onClick={handleDisconnect}
                  style={{ flex: 1, borderColor: "#e66565", color: "#e66565" }}
                  disabled={loading}
                >
                  {loading ? "Removing..." : "Disconnect"}
                </button>
              </>
            ) : (
              <button
                className="integration-btn"
                style={{ background: "#25D366", color: "#232323", flex: 1 }}
                onClick={() => {
                  setEditMode(true);
                  setError("");
                  setSuccess("");
                }}
                disabled={loading}
              >
                Connect
              </button>
            )}
          </div>
        )}

        {error && (
          <div
            className="integration-error"
            style={{ marginTop: 10, color: "#e66565", textAlign: "center" }}
          >
            {error}
          </div>
        )}

        {success && (
          <div
            style={{ marginTop: 10, color: "#25D366", textAlign: "center", fontSize: 13, fontWeight: 700 }}
          >
            {success}
          </div>
        )}
      </div>
    </div>
  );
}