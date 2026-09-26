// Present only so the browser considers this dashboard installable as an app
// (some browsers require an active service worker for the install prompt).
// Deliberately does no caching at all - the whole point of this page is live
// status, so a cached/stale response would be actively misleading.
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
