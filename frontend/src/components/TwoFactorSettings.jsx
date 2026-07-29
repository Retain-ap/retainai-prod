import React, { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { apiUrl } from "../apiBase";

async function request(path, options = {}) {
  const response = await fetch(apiUrl(`auth/2fa/${path}`), {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Security request failed.");
  return data;
}

export default function TwoFactorSettings() {
  const [status, setStatus] = useState(null);
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [backupCodes, setBackupCodes] = useState([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () =>
    request("status")
      .then(setStatus)
      .catch((error) => setMessage(error.message));

  useEffect(() => {
    refresh();
  }, []);

  const begin = async () => {
    setBusy(true);
    setMessage("");
    try {
      setSetup(await request("setup", { method: "POST", body: "{}" }));
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setMessage("");
    try {
      const data = await request("confirm", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setBackupCodes(data.backupCodes || []);
      setSetup(null);
      setCode("");
      setMessage("Authenticator protection is now enabled.");
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    setMessage("");
    try {
      await request("disable", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setCode("");
      setMessage("Authenticator protection was disabled.");
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="account-card two-factor-card">
      <div className="account-card-copy">
        <h3>Authenticator app</h3>
        <p>
          Protect your account with Microsoft Authenticator, Google
          Authenticator, 1Password, Authy, or another TOTP-compatible app.
        </p>
      </div>
      <div className="account-card-content">
        <div className="account-detail-box">
          Status: <strong>{status?.enabled ? "Enabled" : "Not enabled"}</strong>
          {status?.required && !status?.enabled
            ? " · Required for platform owners"
            : ""}
          {status?.enabled
            ? ` · ${status.backupCodesRemaining} recovery codes remaining`
            : ""}
        </div>

        {setup && (
          <div className="two-factor-setup">
            <div className="two-factor-qr">
              <QRCodeSVG value={setup.uri} size={180} level="M" />
            </div>
            <div>
              <strong>Scan this code with your authenticator app</strong>
              <p>If scanning is unavailable, enter this setup key:</p>
              <code>{setup.secret}</code>
            </div>
          </div>
        )}

        {(setup || status?.enabled) && (
          <input
            className="field-input"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder={
              status?.enabled
                ? "Authenticator or recovery code"
                : "Enter the six-digit code"
            }
            autoComplete="one-time-code"
          />
        )}

        {backupCodes.length > 0 && (
          <div className="backup-code-panel">
            <strong>Save these recovery codes now</strong>
            <p>Each code can be used once if you lose your authenticator.</p>
            <div className="backup-code-grid">
              {backupCodes.map((value) => (
                <code key={value}>{value}</code>
              ))}
            </div>
          </div>
        )}

        {message && <div className="account-detail-box">{message}</div>}
      </div>
      <div className="account-card-actions">
        {!status?.enabled && !setup && (
          <button className="account-primary-btn" onClick={begin} disabled={busy}>
            Set up authenticator
          </button>
        )}
        {setup && (
          <button
            className="account-primary-btn"
            onClick={confirm}
            disabled={busy || !code.trim()}
          >
            Verify and enable
          </button>
        )}
        {status?.enabled && (
          <button
            className="account-secondary-btn"
            onClick={disable}
            disabled={busy || !code.trim()}
          >
            Disable with code
          </button>
        )}
      </div>
    </article>
  );
}
