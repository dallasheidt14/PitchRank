'use client';

import { Bell, BellOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useState, useEffect, useCallback } from 'react';
import { useUser, hasPremiumAccess } from '@/hooks/useUser';
import { toast } from '@/components/ui/Toaster';

/**
 * NotificationBell — lets users subscribe to push notifications for ranking changes.
 * Shows on the team detail page and watchlist.
 * Requires premium access and browser push support.
 */
export function NotificationBell() {
  const { profile, isLoading: userLoading } = useUser();
  const isPremium = !userLoading && hasPremiumAccess(profile);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [supported, setSupported] = useState(false);

  useEffect(() => {
    setSupported(typeof window !== 'undefined' && 'Notification' in window && 'serviceWorker' in navigator);
  }, []);

  // Check current push state
  useEffect(() => {
    if (!supported || !isPremium) return;

    const checkState = async () => {
      const permission = Notification.permission;
      if (permission === 'granted') {
        const reg = await navigator.serviceWorker.getRegistration('/sw.js');
        const sub = await reg?.pushManager.getSubscription();
        setPushEnabled(!!sub);
      }
    };
    checkState();
  }, [supported, isPremium]);

  const togglePush = useCallback(async () => {
    if (!supported || loading) return;

    setLoading(true);
    try {
      if (pushEnabled) {
        // Unsubscribe
        const reg = await navigator.serviceWorker.getRegistration('/sw.js');
        const sub = await reg?.pushManager.getSubscription();
        if (sub) {
          await sub.unsubscribe();
          await fetch('/api/notifications/subscribe', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ endpoint: sub.endpoint }),
          });
        }
        setPushEnabled(false);
        toast({ title: 'Notifications disabled', description: 'You won\'t receive push alerts', variant: 'default' });
      } else {
        // Subscribe
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
          toast({ title: 'Permission denied', description: 'Please enable notifications in your browser settings', variant: 'warning' });
          return;
        }

        // Register service worker
        const reg = await navigator.serviceWorker.register('/sw.js');
        await navigator.serviceWorker.ready;

        const vapidKey = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
        if (!vapidKey) {
          console.error('VAPID public key not configured');
          toast({ title: 'Setup required', description: 'Push notifications are not yet configured', variant: 'error' });
          return;
        }

        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: vapidKey,
        });

        const subJson = sub.toJSON();
        await fetch('/api/notifications/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            endpoint: subJson.endpoint,
            keys: subJson.keys,
          }),
        });

        setPushEnabled(true);
        toast({ title: 'Notifications enabled!', description: 'You\'ll be notified when your teams\' rankings change', variant: 'success' });
      }
    } catch (err) {
      console.error('Push notification error:', err);
      toast({ title: 'Error', description: 'Failed to update notification settings', variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [supported, loading, pushEnabled]);

  // Don't render for non-premium or unsupported browsers
  if (!supported || !isPremium) return null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          onClick={togglePush}
          disabled={loading}
          className={`gap-2 ${pushEnabled ? 'bg-accent/10 border-accent text-accent' : ''}`}
          aria-label={pushEnabled ? 'Disable notifications' : 'Enable notifications'}
        >
          {pushEnabled ? (
            <Bell className="h-4 w-4 fill-current" />
          ) : (
            <BellOff className="h-4 w-4" />
          )}
          <span className="hidden sm:inline">{loading ? 'Saving...' : pushEnabled ? 'Alerts On' : 'Get Alerts'}</span>
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        <p>{pushEnabled ? 'Turn off push notifications' : 'Get notified when your teams\' rankings change'}</p>
      </TooltipContent>
    </Tooltip>
  );
}
