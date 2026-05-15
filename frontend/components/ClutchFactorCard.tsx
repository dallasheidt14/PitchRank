'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import { Flame, Lock, Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useUser, hasPremiumAccess } from '@/hooks/useUser';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { trackPaywallImpression, trackPaywallUpgradeClicked } from '@/lib/events';

interface ClutchFactorCardProps {
  teamId: string;
}

interface ClutchBucket {
  wins: number;
  losses: number;
  winPct: number | null;
}

interface ClutchResponse {
  oneGoal: ClutchBucket;
  twoGoal: ClutchBucket;
  threePlus: ClutchBucket;
}

const BUCKETS: Array<{ key: keyof ClutchResponse; label: string }> = [
  { key: 'oneGoal', label: '1-Goal Games' },
  { key: 'twoGoal', label: '2-Goal Games' },
  { key: 'threePlus', label: '3+ Goal Games' },
];

function formatPct(winPct: number | null): string {
  if (winPct === null) return '—';
  return `${Math.round(winPct * 100)}%`;
}

function pctColor(winPct: number | null): string {
  if (winPct === null) return 'text-muted-foreground';
  if (winPct >= 0.7) return 'text-green-600 dark:text-green-400';
  if (winPct >= 0.5) return 'text-blue-600 dark:text-blue-400';
  if (winPct >= 0.3) return 'text-amber-600 dark:text-amber-400';
  return 'text-red-600 dark:text-red-400';
}

/**
 * Clutch Factor card — team's W-L and win % bucketed by goal differential
 * (1-goal, 2-goal, 3+ goal). Ties are excluded. Premium-only.
 */
export function ClutchFactorCard({ teamId }: ClutchFactorCardProps) {
  const { profile, isLoading: userLoading } = useUser();
  const [data, setData] = useState<ClutchResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPremium = hasPremiumAccess(profile);

  const fetchData = useCallback(async () => {
    if (!isPremium) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/teams/${teamId}/clutch`);
      const body = await response.json();

      if (!response.ok) {
        throw new Error(body.error || 'Failed to fetch clutch factor');
      }

      setData(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load clutch factor');
    } finally {
      setIsLoading(false);
    }
  }, [teamId, isPremium]);

  useEffect(() => {
    if (isPremium && teamId) {
      fetchData();
    }
  }, [isPremium, teamId, fetchData]);

  useEffect(() => {
    if (!isPremium && !userLoading) {
      trackPaywallImpression({
        feature: 'clutch_factor',
        location: 'team_detail_page',
        team_id: teamId,
      });
    }
  }, [isPremium, userLoading, teamId]);

  if (userLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Flame className="h-4 w-4" />
            Clutch Factor (last 30 games)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={60} />
        </CardContent>
      </Card>
    );
  }

  if (!isPremium) {
    return (
      <Card className="border-l-4 border-l-amber-500/50 overflow-hidden">
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Flame className="h-4 w-4" />
            Clutch Factor (last 30 games)
          </CardTitle>
          <CardDescription>Record in close vs. blowout games</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="relative">
            <div className="blur-sm pointer-events-none select-none space-y-2" aria-hidden="true">
              {BUCKETS.map((b) => (
                <div key={b.key} className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{b.label}</span>
                  <span className="font-mono font-semibold">8–4 (67%)</span>
                </div>
              ))}
            </div>
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/60 backdrop-blur-[1px]">
              <Lock className="h-5 w-5 text-muted-foreground mb-2" />
              <p className="text-xs text-muted-foreground mb-2">Unlock clutch-game splits</p>
              <Link
                href={`/upgrade?source=clutch_factor&team=${teamId}`}
                onClick={() =>
                  trackPaywallUpgradeClicked({
                    feature: 'clutch_factor',
                    location: 'team_detail_page',
                    team_id: teamId,
                  })
                }
              >
                <Button size="sm" className="text-xs">
                  <Lock className="w-3 h-3 mr-1" />
                  Upgrade to Unlock
                </Button>
              </Link>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card className="border-l-4 border-l-primary">
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Flame className="h-4 w-4" />
            Clutch Factor (last 30 games)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={80} />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-l-4 border-l-destructive/50">
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Flame className="h-4 w-4" />
            Clutch Factor (last 30 games)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-2">Unable to load clutch factor</p>
        </CardContent>
      </Card>
    );
  }

  const totalGames = data
    ? data.oneGoal.wins +
      data.oneGoal.losses +
      data.twoGoal.wins +
      data.twoGoal.losses +
      data.threePlus.wins +
      data.threePlus.losses
    : 0;

  if (!data || totalGames === 0) {
    return (
      <Card className="border-l-4 border-l-muted">
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Flame className="h-4 w-4" />
            Clutch Factor (last 30 games)
          </CardTitle>
          <CardDescription>Record in close vs. blowout games</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-2">No decided games yet</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-l-4 border-l-primary">
      <CardHeader className="pb-3">
        <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
          <Flame className="h-4 w-4 text-primary" />
          Clutch Factor (last 30 games)
          <Tooltip>
            <TooltipTrigger asChild>
              <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
            </TooltipTrigger>
            <TooltipContent side="right" className="max-w-[280px]">
              <p className="font-semibold mb-1">Clutch Factor</p>
              <p className="text-xs">
                Wins and losses split by goal differential. Draws are excluded. A strong record in 1-goal games suggests
                a team that closes out tight matches; a weak one suggests they fade when it matters.
              </p>
            </TooltipContent>
          </Tooltip>
        </CardTitle>
        <CardDescription>Record in close vs. blowout games</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {BUCKETS.map(({ key, label }) => {
          const bucket = data[key];
          const total = bucket.wins + bucket.losses;
          return (
            <div key={key} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{label}</span>
              <div className="flex items-center gap-2 font-mono">
                <span className="font-semibold tabular-nums">
                  {bucket.wins}–{bucket.losses}
                </span>
                <span className={cn('text-xs font-medium tabular-nums w-10 text-right', pctColor(bucket.winPct))}>
                  {total > 0 ? formatPct(bucket.winPct) : '—'}
                </span>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
