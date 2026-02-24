/* eslint-disable no-restricted-globals */

/**
 * RetainAI Service Worker (CRA + Render safe)
 * - Network-first for navigations (prevents stale index.html after deploy)
 * - Cache-first for static assets (fast)
 * - Never cache API responses (/api/*)
 * - Cleans old caches on activate
 */

const VERSION = "retainai-v3"; // bump when you change SW behavior
const STATIC_CACHE = `${VERSION}-static`;
const HTML_CACHE = `${VERSION}-html`;

// Precache only the app shell entry (not "/")
const PRECACHE_HTML = ["/index.html"];

// If you optionally inject these in index.html, we won't break:
self.API_BASE = self.API_BASE || "https://retainai-prod.onrender.com";
self.FRONTEND_URL = self.FRONTEND_URL || "/";

function isHttp(url) {
  return url.protocol === "http:" || url.protocol === "https:";
}

function isApiRequest(url) {
  // Avoid caching your backend API or any /api route (same-origin)
  if (url.pathname.startsWith("/api/")) return true;

  // Also exclude requests to API_BASE host (if frontend ever fetches full URLs)
  try {
    const api = new URL(self.API_BASE);
    if (url.origin === api.origin && url.pathname.startsWith("/api/")) return true;
  } catch (_) {}

  return false;
}

function isNavigationRequest(req) {
  // Navigation requests are typically mode === 'navigate'
  // Some browsers also send Accept: text/html
  if (req.mode === "navigate") return true;
  const accept = (req.headers.get("accept") || "").toLowerCase();
  return accept.includes("text/html");
}

function looksLikeStaticAsset(url) {
  // crude but effective
  return (
    url.pathname.match(/\.(?:js|css|map|png|jpg|jpeg|gif|webp|svg|ico|woff|woff2|ttf|eot)$/i) ||
    url.pathname.startsWith("/static/")
  );
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      try {
        const htmlCache = await caches.open(HTML_CACHE);
        await htmlCache.addAll(PRECACHE_HTML);
      } catch (_) {}
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Clean old caches
      try {
        const keys = await caches.keys();
        await Promise.all(
          keys.map((k) => {
            if (k.startsWith("retainai-") && ![STATIC_CACHE, HTML_CACHE].includes(k)) {
              return caches.delete(k);
            }
            return Promise.resolve();
          })
        );
      } catch (_) {}
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Skip non-http(s) schemes (fixes chrome-extension:// etc.)
  if (!isHttp(url)) return;

  // Never cache API calls
  if (isApiRequest(url)) return;

  // 1) NAVIGATION (SPA routes): network-first, fallback to cached index.html
  if (isNavigationRequest(req) && !looksLikeStaticAsset(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(HTML_CACHE);
        try {
          // Always try fresh HTML first (prevents stale deploy mismatch)
          const fresh = await fetch(req);
          // Only cache a valid HTML response
          if (fresh && fresh.ok) {
            const ct = (fresh.headers.get("content-type") || "").toLowerCase();
            if (ct.includes("text/html")) {
              try {
                await cache.put("/index.html", fresh.clone());
              } catch (_) {}
            }
          }
          return fresh;
        } catch (_) {
          // Offline: serve app shell
          const cached = await cache.match("/index.html");
          return cached || Response.error();
        }
      })()
    );
    return;
  }

  // 2) STATIC ASSETS: cache-first, update in background
  if (looksLikeStaticAsset(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(STATIC_CACHE);

        const cached = await cache.match(req);
        if (cached) {
          // update in background
          event.waitUntil(
            (async () => {
              try {
                const fresh = await fetch(req);
                if (fresh && fresh.ok && (fresh.type === "basic" || fresh.type === "cors")) {
                  await cache.put(req, fresh.clone());
                }
              } catch (_) {}
            })()
          );
          return cached;
        }

        // not cached: fetch and store
        try {
          const fresh = await fetch(req);
          if (fresh && fresh.ok && (fresh.type === "basic" || fresh.type === "cors")) {
            try {
              await cache.put(req, fresh.clone());
            } catch (_) {}
          }
          return fresh;
        } catch (_) {
          return Response.error();
        }
      })()
    );
    return;
  }

  // 3) Other GETs: network-first (safe default)
  event.respondWith(
    (async () => {
      try {
        return await fetch(req);
      } catch (_) {
        const cache = await caches.open(STATIC_CACHE);
        const cached = await cache.match(req);
        return cached || Response.error();
      }
    })()
  );
});

/* ----- Push notifications ----- */
self.addEventListener("push", (event) => {
  const payload = (() => {
    try {
      return event.data ? event.data.json() : {};
    } catch {
      return {};
    }
  })();

  const title = payload.title || "Reminder";
  const url = payload.url || "/app/dashboard";
  const options = {
    body: payload.body || "⏰ Follow up with your lead!",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: payload.tag || "retainai-reminder",
    renotify: false,
    data: { url },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  event.waitUntil(
    (async () => {
      const urlToOpen = new URL(
        event.notification?.data?.url || "/",
        self.location.origin
      ).href;

      const windowClients = await clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });

      for (const client of windowClients) {
        if (client.url === urlToOpen || client.url.startsWith(urlToOpen)) {
          return client.focus();
        }
      }

      if (windowClients.length > 0) {
        try {
          const client = windowClients[0];
          await client.navigate(urlToOpen);
          return client.focus();
        } catch {
          /* fall through */
        }
      }

      return clients.openWindow(urlToOpen);
    })()
  );
});