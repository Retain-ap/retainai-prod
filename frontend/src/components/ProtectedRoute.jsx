import React, { cloneElement, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { apiUrl } from "../apiBase";

export default function ProtectedRoute({ children }) {
  const location = useLocation();
  const [status, setStatus] = useState("checking");
  const [authenticatedUser, setAuthenticatedUser] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    const verify = async () => {
      let response = null;
      let networkError = null;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          response = await fetch(apiUrl("session"), {
            credentials: "include",
            cache: "no-store",
          });
          networkError = null;
        } catch (error) {
          networkError = error;
        }
        if (response?.ok) break;
        const retryable = networkError || !response || response.status >= 500;
        if (attempt === 0 && retryable) {
          await new Promise((resolve) => setTimeout(resolve, 350));
        }
      }

      if (networkError || !response || response.status >= 500) {
        const error = new Error("session_unavailable");
        error.kind = "unavailable";
        throw error;
      }
      if (response.status === 401 || response.status === 403) {
        const error = new Error("not_authenticated");
        error.kind = "anonymous";
        throw error;
      }
      if (!response.ok) {
        const error = new Error(`session_check_failed_${response.status}`);
        error.kind = "unavailable";
        throw error;
      }
      return response.json();
    };
    verify()
      .then(async (data) => {
        if (!active) return;
        if (!data?.authenticated || !data?.user) {
          const error = new Error("not_authenticated");
          error.kind = "anonymous";
          throw error;
        }
        if (data?.user) {
          let ownerAllowed = Boolean(data.user.platformOwner);
          try {
            const ownerResponse = await fetch(apiUrl("owner/access"), {
              credentials: "include",
              cache: "no-store",
            });
            if (ownerResponse.ok) {
              const ownerData = await ownerResponse.json();
              ownerAllowed = Boolean(ownerData.allowed);
            }
          } catch {}
          const verifiedUser = { ...data.user, platformOwner: ownerAllowed };
          localStorage.setItem("user", JSON.stringify(verifiedUser));
          setAuthenticatedUser(verifiedUser);
        }
        setStatus("authenticated");
      })
      .catch((error) => {
        if (!active) return;
        if (error?.kind === "anonymous") {
          localStorage.removeItem("user");
          setAuthenticatedUser(null);
          setStatus("anonymous");
          return;
        }
        setStatus("unavailable");
      });
    return () => {
      active = false;
    };
  }, [retryKey]);

  if (status === "checking") {
    return (
      <div className="auth-gate">
        <div className="auth-gate-mark">RetainAI</div>
        <div className="auth-gate-spinner" aria-label="Checking your secure session" />
        <p>Securing your workspace…</p>
      </div>
    );
  }
  if (status !== "authenticated") {
    if (status === "unavailable") {
      return (
        <div className="auth-gate" role="alert">
          <div className="auth-gate-mark">RetainAI</div>
          <h1>We could not reach your workspace</h1>
          <p>Your session has not been cleared. Check your connection, then try again.</p>
          <button
            className="auth-gate-retry"
            type="button"
            onClick={() => {
              setStatus("checking");
              setRetryKey((value) => value + 1);
            }}
          >
            Try again
          </button>
        </div>
      );
    }
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return cloneElement(children, { authenticatedUser });
}
