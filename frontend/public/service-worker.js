/* eslint-disable no-restricted-globals */

/* ----- PWA bootstrap (install/activate + tiny cache) ----- */
const CACHE = "retainai-v1";
const PRECACHE = ["/", "/index.html"];

// Optionally allow runtime override of API/Frontend in index.html if you add:
// <script>self.API_BASE="https://retainai-prod.onrender.com"; self.FRONTEND_URL="/";</script>
self.API_BASE = self.API_BASE || "https://retainai-prod.onrender.com";
self.FRONTEND_URL = self.FRONTEND_URL || "/";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(CACHE);
      await cache.addAll(PRECACHE);
    } catch (_) {}
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

/* Cache with network — SAFE:
   - GET only
   - http/https only (skip chrome-extension:// etc.)
   - cache only 200 OK, non-partial, basic/cors responses
*/
self.addEventListener("fetch", (event) => {
  const req = event.request;

  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Skip non-http(s) schemes (fixes "chrome-extension is unsupported")
  if (url.protocol !== "http:" && url.protocol !== "https:") return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);

      // Try cache first
      const cached = await cache.match(req);
      if (cached) return cached;

      // Then network, and only cache "good" responses
      try {
        const res = await fetch(req);

        const isOk = res && res.status === 200;
        const isPartial = res.status === 206 || res.headers.has("content-range");
        const isCacheableType = res.type === "basic" || res.type === "cors";

        if (isOk && !isPartial && isCacheableType) {
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

/* ----- Push notifications ----- */
self.addEventListener("push", (event) => {
  const payload = (() => {
    try { return event.data ? event.data.json() : {}; } catch { return {}; }
  })();

  const title = payload.title || "Reminder";
  const url = payload.url || "/app/dashboard"; // sensible default for your app
  const options = {
    body: payload.body || "⏰ Follow up with your lead!",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: payload.tag || "retainai-reminder",   // collapses duplicates
    renotify: false,
    data: { url },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

/* Focus an existing tab on the right route if possible, otherwise open a new one. */
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  event.waitUntil((async () => {
    const urlToOpen = new URL(event.notification?.data?.url || "/", self.location.origin).href;
    const windowClients = await clients.matchAll({ type: "window", includeUncontrolled: true });

    for (const client of windowClients) {
      if (client.url === urlToOpen || client.url.startsWith(urlToOpen)) {
        return client.focus();
      }
    }

    if (windowClients.length > 0) {
      try {
        const client = windowClients[0];
        await client.navigate(urlToOpen); // same-origin only
        return client.focus();
      } catch { /* fall through */ }
    }
    return clients.openWindow(urlToOpen);
  })());
});

/* (Optional) handy for analytics/debugging
self.addEventListener("notificationclose", (event) => {
  // console.log("Notification dismissed:", event.notification?.tag);
});
*/
