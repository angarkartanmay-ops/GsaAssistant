// Minimal service worker: makes N.O.V.A. installable on the phone's home screen.
// Network-first and nothing cached, so you never see stale tasks or replies.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
