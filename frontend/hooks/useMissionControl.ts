'use client';

import { useQuery } from '@tanstack/react-query';
import type { MissionControlSnapshot } from '@/types/mission-control';

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: 'Unknown error' }));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export function useMissionControlSnapshot() {
  return useQuery<MissionControlSnapshot>({
    queryKey: ['mission-control', 'model-snapshot'],
    queryFn: () => fetchJson('/api/mission-control/model-snapshot'),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}
