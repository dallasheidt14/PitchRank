'use client';

import { isServer, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { isNetworkError } from '@/lib/errors';

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Optimized for rankings data that updates infrequently (weekly/daily)
        // Increased from 1 minute to 5 minutes to reduce unnecessary refetches
        staleTime: 5 * 60 * 1000, // 5 minutes (rankings update weekly)

        // Garbage collection time - how long unused cache is kept
        gcTime: 10 * 60 * 1000, // 10 minutes (increased from default 5 min)

        refetchOnWindowFocus: false,

        // Only refetch on mount if data is stale (default behavior when staleTime is set)
        // refetchOnMount defaults to true, which respects staleTime

        // Automatic request deduplication in React Query v5 based on query keys

        // Retry all errors at least once to handle transient Supabase issues
        // Network errors get more retries since they're typically recoverable
        retry: (failureCount, error) => {
          if (isNetworkError(error)) return failureCount < 3;
          return failureCount < 1;
        },

        // Exponential backoff for retries
        retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      },
    },
  });
}

export function DataProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(makeQueryClient);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

// One client for the browser session, so Back from a team page finds the cohort already loaded.
// A fresh client would show a skeleton on the unseeded /rankings landing and only the server seed
// on a large board: too short a page to restore the saved position into.
// Rankings data is public; never route user-scoped keys like ['watchlist'] through this client,
// which outlives a sign-out (sign-out navigates client-side).
let rankingsBrowserClient: QueryClient | undefined;

function getRankingsQueryClient() {
  if (isServer) return makeQueryClient();
  rankingsBrowserClient ??= makeQueryClient();
  return rankingsBrowserClient;
}

export function RankingsDataProviders({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={getRankingsQueryClient()}>{children}</QueryClientProvider>;
}
