import React, { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { apiUrl } from "../apiBase";

export default function ProtectedRoute({ children }) {
  const location = useLocation();
  const [status, setStatus] = useState("checking");

  useEffect(() => {
    let active = true;
    fetch(apiUrl("session"), { credentials: "include", cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("not_authenticated");
        return response.json();
      })
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

  if (status === "checking") return null;
  if (status !== "authenticated") {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}
