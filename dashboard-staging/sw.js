const CACHE_NAME = 'aevus-v60';
const SHELL_ASSETS = [
  '/dashboard/Aevus_Console.html',
  '/dashboard/api-client.js',
  '/dashboard/manifest.json',
  '/dashboard/icons/icon-192.png',
  '/dashboard/icons/icon-512.png'
];

// Install — cache app shell
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate — clean old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch — network-first for API, cache-first for shell
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // API calls — network first, cache last-known response
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).then(resp => {
        if (resp.ok && e.request.method === 'GET') {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
        }
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Static assets — network first, cache fallback (ensures fresh deploys)
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp.ok) {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
      }
      return resp;
    }).catch(() => {
      return caches.match(e.request).then(cached => {
        if (cached) return cached;
        if (e.request.mode === 'navigate') {
          return caches.match('/dashboard/Aevus_Console.html');
        }
      });
    })
  );
});

// Push notifications
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {};
  const title = data.title || 'Aevus Alert';
  const options = {
    body: data.body || 'New alert requires attention',
    icon: '/dashboard/icons/icon-192.png',
    badge: '/dashboard/icons/icon-192.png',
    tag: data.tag || 'aevus-alert',
    vibrate: data.severity === 'critical' ? [200, 100, 200, 100, 200] : [200, 100, 200],
    data: { url: data.url || '/dashboard/Aevus_Console.html#alarms' },
    actions: [
      { action: 'acknowledge', title: 'Acknowledge' },
      { action: 'view', title: 'View Details' }
    ],
    requireInteraction: data.severity === 'critical'
  };
  e.waitUntil(self.registration.showNotification(title, options));
});

// Notification click
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = e.notification.data.url || '/dashboard/Aevus_Console.html#alarms';
  e.waitUntil(
    clients.matchAll({ type: 'window' }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url.includes('/dashboard/') && 'focus' in client) {
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});

// Background sync for queued actions
self.addEventListener('sync', e => {
  if (e.tag === 'aevus-sync') {
    e.waitUntil(syncQueuedActions());
  }
});

async function syncQueuedActions() {
  const cache = await caches.open(CACHE_NAME);
  const queueResp = await cache.match('__action_queue__');
  if (!queueResp) return;
  const queue = await queueResp.json();
  for (const action of queue) {
    try {
      await fetch(action.url, {
        method: action.method,
        headers: action.headers,
        body: action.body
      });
    } catch (e) {
      // Re-queue failed actions
      return;
    }
  }
  await cache.delete('__action_queue__');
}
