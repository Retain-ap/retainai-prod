// frontend/src/apiBase.js

// Goal:
// - API_BASE should be the BACKEND ORIGIN (no trailing /api)
// - apiUrl("profile?x=1") => `${API_BASE}/api/profile?x=1`
// - Never crash if `process` is undefined (some builds/bundlers)

// Read env safely
function readEnvBase() {
  // 1) Runtime injected env (optional)
  const runtime =
    (typeof window !== "undefined" && window.__ENV__ && (
      window.__ENV__.REACT_APP_API_BASE ||
      window.__ENV__.VITE_API_BASE ||
      window.__ENV__.API_BASE
    )) || "";

  if (runtime) return runtime;

  // 2) Build-time env (CRA)
  const cra =
    (typeof process !== "undefined" &&
      process.env &&
      (process.env.REACT_APP_API_BASE || process.env.REACT_APP_API_URL)) ||
    "";

  return cra;
}

// Normalize to origin (remove trailing slashes, remove trailing /api)
function cleanOrigin(s) {
  return String(s || "")
    .trim()
    .replace(/\/+$/g, "")
    .replace(/\/api$/i, "");
}

// Default backend origin (your Render backend)
const FALLBACK = "https://retainai-prod.onrender.com";

// ✅ BACKEND ORIGIN ONLY
const API_BASE = cleanOrigin(readEnvBase() || FALLBACK);

// ✅ named export (so: import { API_BASE } works)
export { API_BASE };

// ✅ helper: always returns BACKEND /api/* URL
export function apiUrl(path = "") {
  const p = String(path || "").trim();

  // If already a full URL, return as-is
  if (/^https?:\/\//i.test(p)) return p;

  // Remove any leading "/api" so we don't double-prefix
  const noLeadingApi = p.replace(/^\/?api\/?/i, "");

  // Ensure exactly one leading slash after /api
  const cleanPath = noLeadingApi.replace(/^\/+/, "");

  return `${API_BASE}/api/${cleanPath}`;
}

// ✅ default export (so: import API_BASE works too)
export default API_BASE;
