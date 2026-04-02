'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { DateRangeSelector } from '@/components/analytics/DateRangeSelector';
import { SearchConsoleTab } from '@/components/analytics/SearchConsoleTab';
import { TrafficTab } from '@/components/analytics/TrafficTab';
import { FunnelTab } from '@/components/analytics/FunnelTab';
import { useUser, hasAdminAccess } from '@/hooks/useUser';

export default function MissionControlPage() {
  const { user, profile, isLoading: userLoading } = useUser();
  const [range, setRange] = useState('28d');

  if (userLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-black">
        <div className="container mx-auto p-6">
          <div className="animate-pulse space-y-6">
            <div className="h-12 bg-white/5 rounded-xl w-64" />
            <div className="h-96 bg-white/5 rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  if (!user || !hasAdminAccess(profile)) {
    return (
      <div className="min-h-screen bg-background">
        <div className="container px-4 py-16">
          <div className="text-center max-w-md mx-auto">
            <h1 className="text-2xl font-display mb-3">Page Not Found</h1>
            <p className="text-muted-foreground mb-6">The page you are looking for does not exist.</p>
            <Link href="/">
              <Button size="lg">Go Home</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

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
