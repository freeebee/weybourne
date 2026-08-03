/* Minimal service worker: cache-first for static assets so the installed app
   opens instantly; API calls always go to the network. */
const CACHE = "weybourne-v2";   // bump to invalidate cached mascots/assets

self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE)
      .map((k) => caches.delete(k))))
    .then(() => clients.claim())
));

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
