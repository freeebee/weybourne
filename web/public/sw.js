/* Minimal service worker: cache-first for static assets so the installed app
   opens instantly; API calls always go to the network. */
const CACHE = "weybourne-v1";

self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(clients.claim()));

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit ||
      fetch(e.request).then((res) => {
        if (res.ok && (url.pathname.startsWith("/assets/")
          || url.pathname.startsWith("/brand/")
          || url.pathname.startsWith("/mascot/"))) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match("/")),
    ),
  );
});
