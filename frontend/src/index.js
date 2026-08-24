// src/index.js
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "./retainai-ui.css";
import GoogleAuthWrapper from "./components/GoogleAuthProvider";
import { apiUrl } from "./apiBase";
import "./pwaInstall";

// All backend calls use the signed, HttpOnly session cookie. Keeping this in
// one place also covers older components that did not set credentials.
const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
  const url = typeof input === "string" ? input : input?.url || "";
  const backendOrigin = new URL(apiUrl("")).origin;
  if (url && new URL(url, window.location.origin).origin === backendOrigin) {
    return nativeFetch(input, { ...init, credentials: "include" });
  }
  return nativeFetch(input, init);
};

// helper to convert VAPID key
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

function getUserEmail() {
  try {
    const u = JSON.parse(localStorage.getItem("user") || "null");
    return (u?.org_id || u?.email || "").toString().trim().toLowerCase();
  } catch {
    return "";
  }
}

// Register service worker + Push (PROD SAFE)
async function registerSwAndPush() {
  if (!("serviceWorker" in navigator)) return;

  try {
    const registration = await navigator.serviceWorker.register("/service-worker.js");
    console.log("Service Worker registered:", registration);

    // Only attempt push if we have a VAPID key
    const VAPID_PUBLIC_KEY =
      (window.__ENV__ &&
        (window.__ENV__.REACT_APP_VAPID_PUBLIC_KEY ||
          window.__ENV__.VITE_VAPID_PUBLIC_KEY ||
          window.__ENV__.VAPID_PUBLIC_KEY)) ||
      (typeof process !== "undefined" &&
        process.env &&
        process.env.REACT_APP_VAPID_PUBLIC_KEY) ||
      "";

    if (!VAPID_PUBLIC_KEY) return;

    // Ask for push permission (best-effort)
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return;

    // If already subscribed, reuse; otherwise subscribe
    let pushSubscription = await registration.pushManager.getSubscription();
    if (!pushSubscription) {
      const subscribeOptions = {
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
      };
      pushSubscription = await registration.pushManager.subscribe(subscribeOptions);
    }

    console.log("PushSubscription:", pushSubscription);

    const email = getUserEmail();
    if (!email) {
      // user not logged in yet; don't store a subscription against empty email
      return;
    }

    // Send to backend using apiUrl (prevents posting to frontend origin)
    await fetch(apiUrl("save-subscription"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        subscription: pushSubscription,
        email,
      }),
    });
  } catch (err) {
    console.error("SW registration / push setup failed:", err);
  }
}

// ✅ Only register SW/push in production builds.
// CRA sets NODE_ENV=production in builds on Render.
if (process.env.NODE_ENV === "production") {
  window.addEventListener("load", () => {
    registerSwAndPush();
  });

  // If user logs in after page load, try again once (so subscription gets linked to email)
  window.addEventListener("storage", (e) => {
    if (e.key === "user") {
      // Debounce a hair in case other login storage writes happen
      setTimeout(() => {
        registerSwAndPush();
      }, 250);
    }
  });
} else {
  // In dev, avoid SW caching headaches.
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.getRegistrations().then((regs) => regs.forEach((r) => r.unregister()));
  }
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <GoogleAuthWrapper>
    <App />
  </GoogleAuthWrapper>
);
