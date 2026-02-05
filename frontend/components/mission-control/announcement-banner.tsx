'use client';

import React, { useState, useEffect } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Megaphone, Plus, X, Wifi } from 'lucide-react';
import { createSupabaseBrowserClient } from '@/lib/supabaseBrowserClient';

interface Announcement {
  id: string;
  message: string;
  author: string;
  created_at: string;
}

export function AnnouncementBanner() {
  const [announcement, setAnnouncement] = useState<Announcement | null>(null);
  const [loading, setLoading] = useState(true);
  const [dismissed, setDismissed] = useState(false);
  const [newMessage, setNewMessage] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [isRealtime, setIsRealtime] = useState(false);

  const fetchAnnouncement = async () => {
    try {
      const res = await fetch('/api/announcements?limit=1');
      if (res.ok) {
        const data = await res.json();
        if (data.announcements && data.announcements.length > 0) {
          const latest = data.announcements[0];
          // Only show if it's from the last 7 days
          const created = new Date(latest.created_at);
          const weekAgo = new Date();
          weekAgo.setDate(weekAgo.getDate() - 7);
          if (created > weekAgo) {
            setAnnouncement(latest);
            setDismissed(false); // Reset dismissed state for new announcements
          }
        }
      }
    } catch (e) {
      console.error('Failed to fetch announcement:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnnouncement();

    // Set up Supabase Realtime subscription for announcements
    const supabase = createSupabaseBrowserClient();
    
    const channel = supabase
      .channel('announcements_changes')
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'announcements',
        },
        (payload) => {
          console.log('New announcement:', payload);
          const newAnnouncement = payload.new as Announcement;
          setAnnouncement(newAnnouncement);
          setDismissed(false); // Show new announcement
        }
      )
      .subscribe((status) => {
        console.log('Announcements realtime status:', status);
        setIsRealtime(status === 'SUBSCRIBED');
      });

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const handleCreateAnnouncement = async () => {
    if (!newMessage.trim()) return;
    setSubmitting(true);
    try {
      const res = await fetch('/api/announcements', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: newMessage.trim(),
          author: 'D H', // TODO: Get from auth
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setAnnouncement(data.announcement);
        setNewMessage('');
        setDialogOpen(false);
        setDismissed(false);
      }
    } catch (e) {
      console.error('Failed to create announcement:', e);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return null;

  // Show create button if no announcement or dismissed
  if (!announcement || dismissed) {
    return (
      <div className="flex justify-end mb-4">
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1">
              <Megaphone className="h-4 w-4" />
              New Announcement
              {isRealtime && <Wifi className="h-3 w-3 text-green-500 ml-1" />}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Megaphone className="h-5 w-5" />
                Create Announcement
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-4 pt-2">
              <Input
                placeholder="Type your announcement..."
                value={newMessage}
                onChange={(e) => setNewMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreateAnnouncement();
                }}
              />
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>
                  Cancel
                </Button>
                <Button onClick={handleCreateAnnouncement} disabled={!newMessage.trim() || submitting}>
                  {submitting ? 'Posting...' : 'Post'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  const time = new Date(announcement.created_at);
  const timeStr = time.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });

  return (
    <Card className="mb-4 border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950/50">
      <CardContent className="py-3 px-4">
        <div className="flex items-start gap-3">
          <Megaphone className="h-5 w-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-blue-900 dark:text-blue-100">
              {announcement.message}
            </p>
            <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
              — {announcement.author} • {timeStr}
              {isRealtime && (
                <span title="Real-time updates active">
                  <Wifi className="inline h-3 w-3 text-green-500 ml-2" />
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button variant="ghost" size="sm" className="h-7 px-2">
                  <Plus className="h-4 w-4" />
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <Megaphone className="h-5 w-5" />
                    New Announcement
                  </DialogTitle>
                </DialogHeader>
                <div className="space-y-4 pt-2">
                  <Input
                    placeholder="Type your announcement..."
                    value={newMessage}
                    onChange={(e) => setNewMessage(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleCreateAnnouncement();
                    }}
                  />
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" onClick={() => setDialogOpen(false)}>
                      Cancel
                    </Button>
                    <Button onClick={handleCreateAnnouncement} disabled={!newMessage.trim() || submitting}>
                      {submitting ? 'Posting...' : 'Post'}
                    </Button>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={() => setDismissed(true)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
