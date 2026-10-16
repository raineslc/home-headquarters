"""Installable phone app (PWA): manifest, service worker and offline page.

These responses are public and contain no household data. The service worker caches only the
static app files and the offline page; family pages are always fetched fresh and never stored
on the phone, so a shared or lost phone does not keep plans offline.
"""
import hashlib
import json
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET

THEME = '#276749'

@require_GET
def manifest(request):
    data = {
        'id': '/', 'name': 'Home Headquarters', 'short_name': 'Home HQ',
        'description': 'Family calendar, tasks and school lunches.',
        'start_url': '/?source=app', 'scope': '/', 'display': 'standalone',
        'background_color': '#ffffff', 'theme_color': THEME,
        'icons': [
            {'src': static('icons/icon-192.png'), 'sizes': '192x192', 'type': 'image/png'},
            {'src': static('icons/icon-512.png'), 'sizes': '512x512', 'type': 'image/png'},
            {'src': static('icons/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        # Long-press shortcuts on the Android home-screen icon.
        'shortcuts': [
            {'name': 'Add activity', 'url': '/plan/activity/new/?source=app', 'icons': [{'src': static('icons/icon-192.png'), 'sizes': '192x192'}]},
            {'name': 'Tasks', 'url': '/tasks/?source=app', 'icons': [{'src': static('icons/icon-192.png'), 'sizes': '192x192'}]},
            {'name': 'Lunches', 'url': '/lunches/?source=app', 'icons': [{'src': static('icons/icon-192.png'), 'sizes': '192x192'}]},
        ],
    }
    return JsonResponse(data, content_type='application/manifest+json')

def shell_files():
    return [static('app.css'), static('planner.js'), static('icons/icon-192.png'), static('icons/favicon-32.png'), '/offline/']

SERVICE_WORKER = """// Home Headquarters service worker. Caches app files only; family pages are never stored.
const CACHE = 'hhq-shell-%(version)s';
const SHELL = %(files)s;
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    // Always load pages from the server; show the offline page only when there is no connection.
    event.respondWith(fetch(request).catch(() => caches.match('/offline/')));
  } else if (url.pathname.startsWith('/static/')) {
    // Static file names include a content hash, so a cached copy never goes stale.
    event.respondWith(caches.match(request).then(hit => hit || fetch(request)));
  }
});
// Phone reminders: show the notification; a tap opens the plan in the app.
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (error) { data = {}; }
  event.waitUntil(self.registration.showNotification(data.title || 'Home Headquarters', {
    body: data.body || '', icon: %(icon)s, badge: %(badge)s, tag: data.tag || undefined, data: {url: data.url || '/'}}));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin);
  const url = target.origin === self.location.origin ? target.href : self.location.origin + '/';
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(windows => {
    for (const client of windows) {
      if (client.url.startsWith(self.location.origin) && 'focus' in client) return client.focus().then(c => c.navigate(url));
    }
    return self.clients.openWindow(url);
  }));
});
"""

@require_GET
def service_worker(request):
    files = shell_files()
    # The hashed file names change whenever the CSS or script changes, which refreshes the cache.
    version = hashlib.sha256('|'.join(files).encode()).hexdigest()[:12]
    body = SERVICE_WORKER % {'version': version, 'files': json.dumps(files), 'icon': json.dumps(static('icons/icon-192.png')),
                             'badge': json.dumps(static('icons/favicon-32.png'))}
    return HttpResponse(body, content_type='application/javascript')

@require_GET
def offline(request):
    return render(request, 'offline.html')
