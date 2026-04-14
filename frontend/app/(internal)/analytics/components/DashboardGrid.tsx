'use client';
import { useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DEFAULT_PRESET, REACT_QUERY_STALE_MS, REACT_QUERY_GC_MS } from '@/lib/internal-analytics/constants';
import type { DateRangePreset } from '@/lib/internal-analytics/types';
import { DateRangePicker } from './DateRangePicker';
import { TrafficOverviewTile } from './tiles/TrafficOverviewTile';
import { TopPagesTile } from './tiles/TopPagesTile';
import { UpgradeViewsTile } from './tiles/UpgradeViewsTile';
import { SearchPerformanceTile } from './tiles/SearchPerformanceTile';
import { TopQueriesTile } from './tiles/TopQueriesTile';
import { LandingPagesTile } from './tiles/LandingPagesTile';
import { ChatSidebar } from './chat/ChatSidebar';

export function DashboardGrid() {
  const [client] = useState(
    () =>
      new QueryClient({ defaultOptions: { queries: { staleTime: REACT_QUERY_STALE_MS, gcTime: REACT_QUERY_GC_MS } } })
  );
  const params = useSearchParams();
  const range = (params.get('range') as DateRangePreset) ?? DEFAULT_PRESET;

  return (
    <QueryClientProvider client={client}>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Internal Analytics</h1>
          <DateRangePicker />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-4">
            <TrafficOverviewTile range={range} />
            <UpgradeViewsTile range={range} />
            <TopPagesTile range={range} />
            <SearchPerformanceTile range={range} />
            <TopQueriesTile range={range} />
            <LandingPagesTile range={range} />
          </div>
          <div className="lg:col-span-1">
            <ChatSidebar range={range} />
          </div>
        </div>
      </div>
    </QueryClientProvider>
  );
}
