// ------------------------------------------------------------------
// TOMBSTONE service worker (cache generation retired: aevus-v60 and older).
// The broad Aevus console is parked (see git tag retired/old-dashboard).
// Aevus Comms at /comms/ is the only served application, and it lives
// outside this worker's scope.
//
// This replaces the old caching worker. A returning browser that still has
// the old worker registered picks this file up on its next update check; on
// activation it deletes EVERY cache (including the cached old console shell)
// and unregisters itself. It intercepts no requests, so every navigation
// goes to the network.
//
// Do not reintroduce a caching worker or a precache list here: a stale shell
// is exactly how the retired console would come back to life client-side.
// ------------------------------------------------------------------
self.addEventListener('install', function () { self.skipWaiting(); });

self.addEventListener('activate', function (e) {
  e.waitUntil((async function () {
    try {
      var keys = await caches.keys();
      await Promise.all(keys.map(function (k) { return caches.delete(k); }));
    } catch (_) {}
    try { await self.registration.unregister(); } catch (_) {}
    try { await self.clients.claim(); } catch (_) {}
  })());
});

// No fetch handler: the network (and nginx) serve every request.
