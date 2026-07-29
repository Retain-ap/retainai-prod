import React, { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { apiUrl } from "../apiBase";

export default function ProtectedRoute({ children }) {
  const location = useLocation();
  const [status, setStatus] = useState("checking");

  useEffect(() => {
    let active = true;
    const verify = async () => {
      let response;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        response = await fetch(apiUrl("session"), {
          credentials: "include",
          cache: "no-store",
        });
        if (response.ok) break;
        if (attempt === 0 && response.status >= 500) {
          await new Promise((resolve) => setTimeout(resolve, 350));
        }
      }
      if (!response?.ok) throw new Error("not_authenticated");
      return response.json();
    };
    verify()
      .then((data) => {
        if (!active) return;
        if (!data?.authenticated || !data?.user) {
          throw new Error("not_authenticated");
        }
        if (data?.user) localStorage.setItem("user", JSON.stringify(data.user));
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        localStorage.removeItem("user");
        setStatus("anonymous");
      });
    return () => {
      active = false;
    };
  }, []);

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
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}
