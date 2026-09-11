/* eslint-env serviceworker */
/* eslint-disable no-restricted-globals */

const VERSION    = "retainai-sw-v1";
const CACHE_NAME = `retainai-cache-${VERSION}`;

// Backend + frontend origins. Can be overridden from index.html like:
// <script>self.API_BASE="https://retainai-prod.onrender.com"; self.FRONTEND_URL="https://your-frontend.onrender.com";</script>
const API_BASE      = self.API_BASE      || "https://retainai-prod.onrender.com";
const FRONTEND_URL  = self.FRONTEND_URL  || "/";

/* -------------------- INSTALL -------------------- */
self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll([
        "/",               // SPA shell (Render rewrite handles this)
        "/index.html",
        "/manifest.webmanifest",
        "/icons/icon-192.png",
        "/icons/icon-512.png",
      ]).catch(() => {})
    )
  );
});

/* -------------------- ACTIVATE -------------------- */
self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((n) => n.startsWith("retainai-cache-") && n !== CACHE_NAME)
          .map((n) => caches.delete(n))
      );
      await self.clients.claim();
    })()
  );
});

/* -------------------- FETCH (cache with network) -------------------- */
self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Only cache GETs
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Skip non-http(s) schemes (e.g., chrome-extension://)
  if (url.protocol !== "http:" && url.protocol !== "https:") return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE_NAME);

      // Cache-first
      const cached = await cache.match(req);
      if (cached) return cached;

      try {
        const res = await fetch(req);

        // Only cache clean 200 responses (no partial 206)
        const isOk        = res && res.status === 200;
        const isPartial   = res.status === 206 || res.headers.has("content-range");
        const cacheable   = isOk && !isPartial && (res.type === "basic" || res.type === "cors");

        if (cacheable) {
          try { await cache.put(req, res.clone()); } catch (_) {}
        }

        return res;
      } catch (_) {
        // Offline fallback
        return cached || Response.error();
      }
    })()
  );
});

/* -------------------- PUSH: display notification -------------------- */
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) {}

  const title = data.title || "RetainAI";
  const body  = data.body  || "⏰ Time to follow up with a lead!";
  const url   = data.url   || FRONTEND_URL;
  const icon  = data.icon  || "/icons/icon-192.png";
  const tag   = data.tag   || "retainai-notification";

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon,
      badge: icon,
      tag,
      data: { url },
    })
  );
});

/* -------------------- CLICK: focus/open app -------------------- */
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || FRONTEND_URL;

  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of all) {
        if ("focus" in client) {
          // Focus any open tab of our app
          if (client.url && client.url.indexOf(new URL(url, self.location.origin).origin) === 0) {
            return client.focus();
          }
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })()
  );
});

/* -------------------- MESSAGE: send backend-triggered notification -------------------- */
/**
 * Post from your page code:
 * navigator.serviceWorker.controller?.postMessage({
 *   type: "SEND_NOTIFICATION",
 *   payload: { email, message: "Your custom text" }
 * });
 */
self.addEventListener("message", (event) => {
  const { type, payload } = event.data || {};
  if (type !== "SEND_NOTIFICATION") return;

  const email   = payload?.email;
  const message = payload?.message || "⏰ Time to follow up with a lead!";
  if (!email) return; // nothing to do

  event.waitUntil(
    fetch(`${API_BASE}/api/send-notification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, message }),
      // no credentials needed unless your endpoint requires cookies
    }).catch(() => {})
  );
});
