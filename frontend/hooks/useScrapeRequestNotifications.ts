'use client';

import { useEffect, useRef } from 'react';
import { supabase } from '@/lib/supabaseClient';
import { toast } from '@/components/ui/Toaster';

/**
 * Hook to listen for completed scrape requests and show notifications
 * Tracks request IDs from localStorage (submitted from this browser session)
 */
export function useScrapeRequestNotifications() {
  const subscriptionRef = useRef<any>(null);
  const processedRequestsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    // Get request IDs from localStorage (requests submitted in this session)
    const getTrackedRequestIds = (): string[] => {
      try {
        const stored = localStorage.getItem('scrape_request_ids');
        return stored ? JSON.parse(stored) : [];
      } catch {
        return [];
      }
    };

    // Mark a request as processed to avoid duplicate notifications
    const markAsProcessed = (requestId: string) => {
      processedRequestsRef.current.add(requestId);
    };

    // Check if we've already notified about this request
    const isProcessed = (requestId: string): boolean => {
      return processedRequestsRef.current.has(requestId);
    };

    // Set up Supabase Realtime subscription to listen for changes
    const channel = supabase
      .channel('scrape_requests_changes')
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'scrape_requests',
          filter: 'status=eq.completed',
        },
        (payload) => {
          const requestId = payload.new.id as string;
          const requestData = payload.new as any;

          // Only notify if:
          // 1. We haven't already processed this request
          // 2. This request was submitted from this browser session
          if (!isProcessed(requestId)) {
            const trackedIds = getTrackedRequestIds();
            if (trackedIds.includes(requestId)) {
              markAsProcessed(requestId);

              const gamesFound = requestData.games_found ?? 0;
              const teamName = requestData.team_name || 'the team';
              const gameDate = requestData.game_date;

              if (gamesFound > 0) {
                toast({
                  title: 'Game Data Added!',
                  description: `Found ${gamesFound} game${gamesFound > 1 ? 's' : ''} for ${teamName} on ${gameDate}. Check the game history!`,
                  variant: 'success',
                  duration: 8000,
                });
              } else {
                toast({
                  title: 'No Games Found',
                  description: `No games were found for ${teamName} on ${gameDate}. The game may not exist in the source data.`,
                  variant: 'warning',
                  duration: 6000,
                });
              }

              // Remove from tracked IDs after notification
              const updatedIds = trackedIds.filter((id) => id !== requestId);
              localStorage.setItem('scrape_request_ids', JSON.stringify(updatedIds));
            }
          }
        }
      )
      .subscribe();

    subscriptionRef.current = channel;

    // Cleanup subscription on unmount
    return () => {
      if (subscriptionRef.current) {
        supabase.removeChannel(subscriptionRef.current);
      }
    };
  }, []);
}

/**
 * Track a scrape request ID so we can notify when it completes
 */
export function trackScrapeRequest(requestId: string) {
  try {
    const stored = localStorage.getItem('scrape_request_ids');
    const ids: string[] = stored ? JSON.parse(stored) : [];
    if (!ids.includes(requestId)) {
      ids.push(requestId);
      localStorage.setItem('scrape_request_ids', JSON.stringify(ids));
    }
  } catch (error) {
    console.error('Failed to track scrape request:', error);
  }
}

