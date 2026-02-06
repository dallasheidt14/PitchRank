// PitchRank Push Notification Service Worker

self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};

  const title = data.title || 'PitchRank';
  const options = {
    body: data.body || 'Your team rankings have been updated!',
    icon: '/logos/pitchrank-icon-192.png',
    badge: '/logos/pitchrank-badge-72.png',
    tag: data.tag || 'pitchrank-notification',
    data: {
      url: data.url || '/',
    },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Handle notification click — open the relevant page
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const url = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // If a PitchRank tab is already open, focus it and navigate
      for (const client of clientList) {
        if (client.url.includes('pitchrank') && 'focus' in client) {
          client.focus();
          client.navigate(url);
          return;
        }
      }
      // Otherwise open a new tab
      return clients.openWindow(url);
    })
  );
});
