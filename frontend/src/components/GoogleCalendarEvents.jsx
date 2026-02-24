// src/components/GoogleCalendarEvents.jsx
import React, { useState, useEffect, useRef, useCallback } from "react";
import { SiGooglecalendar } from "react-icons/si";
import { apiUrl } from "../apiBase";

// Key for storing selected calendar per user in localStorage
function getUserCalKey(email) {
  return `retainai_selected_calendar_${email}`;
}

async function safeJson(res) {
  const ct = (res.headers.get("content-type") || "").toLowerCase();
  const raw = await res.text();

  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${res.statusText}\n${raw.slice(0, 300)}`);
  }

  if (!ct.includes("application/json")) {
    if (raw.toLowerCase().includes("<!doctype html") || raw.toLowerCase().includes("</html>")) {
      throw new Error("Expected JSON but got HTML. Likely wrong API base / proxy route.");
    }
    throw new Error(`Expected JSON but got ${ct || "unknown"}\n${raw.slice(0, 200)}`);
  }

  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`Bad JSON: ${e}\n${raw.slice(0, 200)}`);
  }
}

export default function GoogleCalendarEvents({ user, onEvents, onStatus, onCalendarChange }) {
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [calendars, setCalendars] = useState([]);
  const [calendarId, setCalendarId] = useState("");
  const [error, setError] = useState("");

  const pollingRef = useRef(null);
  const popupRef = useRef(null);
  const tickRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    tickRef.current = 0;
  }, []);

  const refreshStatus = useCallback(async () => {
    if (!user?.email) return;

    setLoading(true);
    setError("");
    try {
      const res = await fetch(apiUrl(`google/status/${encodeURIComponent(user.email)}`), {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const data = await safeJson(res);

      const isConnected = !!data.connected;
      const cals = data.calendars || [];

      setConnected(isConnected);
      setCalendars(cals);

      const savedId = localStorage.getItem(getUserCalKey(user.email));
      const fallbackId = cals.find((c) => c.primary)?.id || (cals?.[0]?.id ?? "");
      const nextId = savedId && cals.some((c) => c.id === savedId) ? savedId : fallbackId;

      setCalendarId(nextId || "");
      if (onStatus) onStatus(isConnected ? "loaded" : "not_connected");
    } catch (e) {
      setError(e?.message || "Failed to check Google connection.");
      if (onStatus) onStatus("error");
    } finally {
      setLoading(false);
    }
  }, [user?.email, onStatus]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (user?.email && calendarId) {
      try {
        localStorage.setItem(getUserCalKey(user.email), calendarId);
      } catch {}
      if (onCalendarChange) onCalendarChange(calendarId);
    }
    // eslint-disable-next-line
  }, [calendarId, user?.email]);

  const fetchAuthUrl = useCallback(async () => {
    if (!user?.email) return "";
    const res = await fetch(apiUrl(`google/auth-url?user_email=${encodeURIComponent(user.email)}`), {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    const data = await safeJson(res);
    return data?.url || "";
  }, [user?.email]);

  const tryClosePopup = useCallback(() => {
    // COOP can block access to popup window in different ways.
    // We attempt close, but NEVER read popup.closed (can trigger COOP warnings).
    try {
      if (popupRef.current) popupRef.current.close();
    } catch {}
  }, []);

  const handleConnect = async () => {
    if (!user?.email) return;

    setLoading(true);
    setError("");

    try {
      const url = await fetchAuthUrl();
      if (!url) {
        setLoading(false);
        setError("Failed to get Google auth URL.");
        return;
      }

      // Open popup
      popupRef.current = window.open(url, "googleConnect", "width=520,height=720");
      stopPolling();

      // Poll connection status only (no popup.closed checks)
      pollingRef.current = setInterval(async () => {
        tickRef.current += 1;

        // stop after ~2 minutes (1200ms * 100 = 120s)
        if (tickRef.current > 100) {
          stopPolling();
          setLoading(false);
          // best-effort close
          tryClosePopup();
          return;
        }

        try {
          const res = await fetch(apiUrl(`google/status/${encodeURIComponent(user.email)}`), {
            credentials: "include",
            headers: { Accept: "application/json" },
          });
          const data = await safeJson(res);

          if (data.connected) {
            stopPolling();
            tryClosePopup();

            const cals = data.calendars || [];
            setConnected(true);
            setCalendars(cals);

            const savedId = localStorage.getItem(getUserCalKey(user.email));
            const fallbackId = cals.find((c) => c.primary)?.id || (cals?.[0]?.id ?? "");
            setCalendarId(savedId && cals.some((c) => c.id === savedId) ? savedId : fallbackId);

            setError("");
            setLoading(false);
            if (onStatus) onStatus("loaded");
          }
        } catch {
          // ignore polling blips
        }
      }, 1200);
    } catch (e) {
      setLoading(false);
      setError(e?.message || "Failed to start Google connection.");
      if (onStatus) onStatus("error");
    }
  };

  const handleDisconnect = async () => {
    if (!user?.email) return;

    setLoading(true);
    setError("");

    try {
      await fetch(apiUrl(`google/disconnect/${encodeURIComponent(user.email)}`), {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
      }).catch(() => {});

      setConnected(false);
      setCalendars([]);
      setCalendarId("");

      if (onEvents) onEvents([]);
      if (onStatus) onStatus("not_connected");

      stopPolling();
      tryClosePopup();

      try {
        localStorage.removeItem(getUserCalKey(user.email));
      } catch {}
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    return () => {
      stopPolling();
      tryClosePopup();
    };
  }, [stopPolling, tryClosePopup]);

  return (
    <div className="integration-card-inner">
      <div className="integration-center" style={{ alignItems: "center" }}>
        <SiGooglecalendar size={38} style={{ color: "#4885ed", marginBottom: 12 }} />
        <div className="integration-title" style={{ marginBottom: 3 }}>
          Google Calendar
        </div>
        <div className="integration-desc" style={{ marginBottom: 18 }}>
          Connect your Google Calendar for seamless sync.
        </div>

        {!connected ? (
          <>
            <button
              className="integration-btn"
              onClick={handleConnect}
              disabled={loading}
              style={{
                marginTop: 12,
                width: "100%",
                background: "#4885ed",
                color: "#fff",
                border: "none",
                boxShadow: "0 2px 7px rgba(72,133,237,0.08)",
              }}
            >
              {loading ? "Connecting…" : "Connect Google Calendar"}
            </button>

            <button
              className="integration-btn"
              onClick={refreshStatus}
              disabled={loading || !user?.email}
              style={{
                marginTop: 10,
                width: "100%",
                background: "#191919",
                color: "#cfcfcf",
                border: "1px solid #2a2a2a",
                boxShadow: "none",
              }}
            >
              Refresh status
            </button>

            {error && <div className="integration-error">{error}</div>}
          </>
        ) : (
          <>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                marginBottom: 16,
                width: "100%",
              }}
            >
              <span className="integration-dot" />
              <span className="integration-connected" style={{ marginRight: 10 }}>
                Connected
              </span>
              <button
                className="integration-btn"
                onClick={handleDisconnect}
                disabled={loading}
                style={{
                  marginLeft: 16,
                  minWidth: 120,
                  background: "#191919",
                  color: "#4885ed",
                  border: "2px solid #4885ed",
                  boxShadow: "none",
                }}
              >
                {loading ? "…" : "Disconnect"}
              </button>
            </div>

            {calendars.length > 0 && (
              <div style={{ width: "100%", marginBottom: 10 }}>
                <label
                  style={{
                    color: "#c8c8c8",
                    fontWeight: 500,
                    fontSize: "1em",
                    marginRight: 8,
                    display: "block",
                    textAlign: "center",
                  }}
                >
                  Calendar:
                </label>
                <div style={{ display: "flex", justifyContent: "center", width: "100%" }}>
                  <select
                    className="integration-select"
                    value={calendarId}
                    onChange={(e) => setCalendarId(e.target.value)}
                    style={{ minWidth: 240, maxWidth: 330, margin: "0 auto", textAlign: "center" }}
                  >
                    {calendars.map((cal) => (
                      <option key={cal.id} value={cal.id}>
                        {cal.summary}
                        {cal.primary ? " (Primary)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            <button
              className="integration-btn"
              onClick={refreshStatus}
              disabled={loading || !user?.email}
              style={{
                marginTop: 6,
                width: "100%",
                background: "#191919",
                color: "#cfcfcf",
                border: "1px solid #2a2a2a",
                boxShadow: "none",
              }}
            >
              Refresh status
            </button>

            {error && <div className="integration-error">{error}</div>}
          </>
        )}
      </div>
    </div>
  );
}