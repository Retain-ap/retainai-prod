// src/apiBase.js
// One source of truth for backend base URL.
// IMPORTANT: set REACT_APP_API_BASE to https://retainai-prod.onrender.com (no /app, no /api)

const raw =
  (process?.env?.REACT_APP_API_BASE || process?.env?.REACT_APP_API_URL || "").trim();

function cleanOrigin(s) {
  return (s || "").trim().replace(/\/+$/g, "").replace(/\/api$/i, "");
}

export const API_BASE = cleanOrigin(raw);

// Use this for building API urls safely
export function apiUrl(path) {
  const p = String(path || "").replace(/^\/+/, "");
  // If env not set, fallback to same-origin (dev proxy only)
  if (!API_BASE) return `/api/${p}`;
  return `${API_BASE}/api/${p}`;
}
