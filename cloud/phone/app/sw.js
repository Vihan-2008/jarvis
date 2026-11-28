// The phone app's service worker: keeps the app's own files for opening offline, and shows notifications.
// A push carries only {kind, unread}: never message text, never a file name.
const VERSION = 'jarvis-app-__VERSION__';
const FILES = ['./', 'index.html', 'app.js', 'proto.js', 'md.js', 'app.css', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png'];
const SHOWN = { reply: 'JARVIS replied', ask: 'JARVIS needs your answer', done: 'Your computer finished a task' };

self.addEventListener('install', event => {
  event.waitUntil(caches.open(VERSION).then(cache => cache.addAll(FILES)));
});
self.addEventListener('message', event => { if (event.data === 'take-over') self.skipWaiting(); });
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name !== VERSION && name.startsWith('jarvis-app-')) await caches.delete(name);
    await self.clients.claim();
  })());
});

// Only the app's own files are served from the cache. config.json and the relay always go to the network.
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.endsWith('/config.json')) return;
  event.respondWith(caches.match(event.request, { ignoreSearch: true }).then(hit => hit || fetch(event.request)));
});

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch {}
  const kind = SHOWN[data.kind] ? data.kind : 'reply';
  // Every push shows a notification (iPhones stop delivering pushes that show nothing). Replies collapse into one.
  event.waitUntil((async () => {
    await self.registration.showNotification(SHOWN[kind], { tag: kind === 'ask' ? 'ask' : 'reply', renotify: kind === 'ask', icon: 'icon-192.png', badge: 'icon-192.png' });
    if (navigator.setAppBadge && Number.isInteger(data.unread)) await navigator.setAppBadge(data.unread).catch(() => {});
  })());
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    if (open.length) return open[0].focus();
    return self.clients.openWindow('./');
  })());
});
