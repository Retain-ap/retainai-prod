// src/apiBase.js
// Works in BOTH CRA and Vite builds safely

const envApi =
  (typeof import.meta !== "undefined" &&
    import.meta.env &&
    import.meta.env.VITE_API_BASE) ||
  (typeof process !== "undefined" &&
    process.env &&
    process.env.REACT_APP_API_BASE) ||
  "";

export const API_BASE = envApi.replace(/\/+$/, "");
