'use client';

import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DateRangeSelector } from '@/components/analytics/DateRangeSelector';
import { SearchConsoleTab } from '@/components/analytics/SearchConsoleTab';
import { TrafficTab } from '@/components/analytics/TrafficTab';
import { FunnelTab } from '@/components/analytics/FunnelTab';

export default function MissionControlPage() {
  const [range, setRange] = useState('28d');

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-black text-white">
      <div className="container mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight">Mission Control</h1>
            <p className="mt-1 text-sm text-gray-400">Traffic, search performance, and conversion analytics</p>
          </div>
          <DateRangeSelector value={range} onChange={setRange} />
        </div>

        {/* Tabs */}
        <Tabs defaultValue="search-console">
          <TabsList className="bg-white/5 border border-white/10">
            <TabsTrigger
              value="search-console"
              className="data-[state=active]:bg-white/10 data-[state=active]:text-white text-gray-400"
            >
              Search Console
            </TabsTrigger>
            <TabsTrigger
              value="traffic"
              className="data-[state=active]:bg-white/10 data-[state=active]:text-white text-gray-400"
            >
              Traffic
            </TabsTrigger>
            <TabsTrigger
              value="funnel"
              className="data-[state=active]:bg-white/10 data-[state=active]:text-white text-gray-400"
            >
              Funnel
            </TabsTrigger>
          </TabsList>

          <TabsContent value="search-console" className="mt-6">
            <SearchConsoleTab range={range} />
          </TabsContent>

          <TabsContent value="traffic" className="mt-6">
            <TrafficTab range={range} />
          </TabsContent>

          <TabsContent value="funnel" className="mt-6">
            <FunnelTab range={range} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
