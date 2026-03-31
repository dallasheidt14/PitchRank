'use client';

import { useQuery } from '@tanstack/react-query';
import type { SearchConsoleData, TrafficData, FunnelData } from '@/types/analytics';

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: 'Unknown error' }));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export function useSearchConsole(range: string) {
  return useQuery<SearchConsoleData>({
    queryKey: ['analytics', 'search-console', range],
    queryFn: () => fetchJson(`/api/analytics/search-console?range=${range}`),
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}

export function useTrafficData(range: string) {
  return useQuery<TrafficData>({
    queryKey: ['analytics', 'traffic', range],
    queryFn: () => fetchJson(`/api/analytics/traffic?range=${range}`),
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}

export function useFunnelData(range: string) {
  return useQuery<FunnelData>({
    queryKey: ['analytics', 'funnel', range],
    queryFn: () => fetchJson(`/api/analytics/funnel?range=${range}`),
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}
