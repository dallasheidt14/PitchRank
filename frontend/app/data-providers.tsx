'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { isNetworkError } from '@/lib/errors';

export function DataProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => {
    const client = new QueryClient({
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

    return client;
  });

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
