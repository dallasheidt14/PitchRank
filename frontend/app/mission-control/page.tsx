'use client';

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { ModelSnapshotDashboard } from '@/components/mission-control/ModelSnapshotDashboard';
import { useUser, hasAdminAccess } from '@/hooks/useUser';

export default function MissionControlPage() {
  const { user, profile, isLoading: userLoading } = useUser();

  if (userLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-black">
        <div className="container mx-auto p-6">
          <div className="animate-pulse space-y-6">
            <div className="h-12 w-64 rounded-xl bg-white/5" />
            <div className="h-96 rounded-xl bg-white/5" />
          </div>
        </div>
      </div>
    );
  }

  if (!user || !hasAdminAccess(profile)) {
    return (
      <div className="min-h-screen bg-background">
        <div className="container px-4 py-16">
          <div className="mx-auto max-w-md text-center">
            <h1 className="mb-3 text-2xl font-display">Page Not Found</h1>
            <p className="mb-6 text-muted-foreground">The page you are looking for does not exist.</p>
            <Link href="/">
              <Button size="lg">Go Home</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-black text-white">
      <div className="container mx-auto space-y-6 p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-2">
            <h1 className="font-display text-3xl font-bold tracking-tight">Mission Control</h1>
            <p className="max-w-3xl text-sm text-gray-400">
              Live snapshot of model accuracy, prospective evaluation coverage, and point-in-time training readiness.
            </p>
          </div>
          <Link href="/mission-control/subscriptions">
            <Button variant="outline" size="sm">
              Subscriptions →
            </Button>
          </Link>
        </div>

        <ModelSnapshotDashboard />
      </div>
    </div>
  );
}
