// frontend/src/apiBase.js

const API_BASE =
  window.__ENV__?.REACT_APP_API_BASE ||
  process.env.REACT_APP_API_BASE ||
  "https://retainai-prod.onrender.com";

// ✅ named export (so: import { API_BASE } works)
export { API_BASE };

// ✅ helper (so: import { apiUrl } works)
export function apiUrl(path = "") {
  const p = String(path || "");
  const cleanPath = p.startsWith("/") ? p : `/${p}`;
  return `${API_BASE}${cleanPath}`;
}

// ✅ default export (so: import API_BASE works too)
export default API_BASE;
