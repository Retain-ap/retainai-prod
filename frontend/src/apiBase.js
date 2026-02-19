// frontend/src/apiBase.js

const API_BASE =
  window.__ENV__?.REACT_APP_API_BASE ||
  process.env.REACT_APP_API_BASE ||
  "https://retainai-prod.onrender.com";

export function apiUrl(path = "") {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${cleanPath}`;
}

export default API_BASE;
