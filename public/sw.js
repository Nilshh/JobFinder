// JobPipeline Service Worker
const CACHE_NAME = "jobpipeline-v1";
const STATIC_ASSETS = ["/", "/index.html", "/style.css", "/app.js", "/favicon.svg", "/manifest.json"];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Network-first für API (damit Daten aktuell bleiben)
  if (url.pathname.startsWith("/jobs") || url.pathname.startsWith("/user") ||
      url.pathname.startsWith("/auth") || url.pathname.startsWith("/admin") ||
      url.pathname.startsWith("/watch") || url.pathname.startsWith("/search") ||
      url.pathname.startsWith("/boards") || url.pathname.startsWith("/jira")) {
    event.respondWith(fetch(req).catch(() => caches.match(req)));
    return;
  }
  // Cache-first für statische Assets
  event.respondWith(
    caches.match(req).then(cached => cached || fetch(req).then(res => {
      if (res && res.status === 200) {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
      }
      return res;
    }))
  );
});

// Web-Push-Empfang
self.addEventListener("push", event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch(e) { data = {title: "JobPipeline", body: event.data ? event.data.text() : ""}; }
  const title = data.title || "JobPipeline";
  const options = {
    body: data.body || "Neue Stelle gefunden",
    icon: "/favicon.svg",
    badge: "/favicon.svg",
    data: data.url || "/",
    tag: data.tag || "jobpipeline-push",
    requireInteraction: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = event.notification.data || "/";
  event.waitUntil(
    self.clients.matchAll({type: "window"}).then(clients => {
      for (const client of clients) {
        if (client.url.includes(url) && "focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
