'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import {
  Brain,
  Target,
  Swords,
  TrendingUp,
  TrendingDown,
  Flame,
  Snowflake,
  Lock,
  Info,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useUser, hasPremiumAccess } from '@/hooks/useUser';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type {
  TeamInsightsResponse,
  SeasonTruthInsight,
  ConsistencyInsight,
  PersonaInsight,
} from '@/lib/insights/types';

interface TeamInsightsCardProps {
  teamId: string;
}

/**
 * Compact insights card for team detail page
 * Shows Season Truth, Consistency Score, and Persona in a condensed format
 * Premium-only feature
 */
export function TeamInsightsCard({ teamId }: TeamInsightsCardProps) {
  const { profile, isLoading: userLoading } = useUser();
  const [insights, setInsights] = useState<TeamInsightsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPremium = hasPremiumAccess(profile);

  const fetchInsights = useCallback(async () => {
    if (!isPremium) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/insights/${teamId}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to fetch insights');
      }

      setInsights(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load insights');
    } finally {
      setIsLoading(false);
    }
  }, [teamId, isPremium]);

  useEffect(() => {
    if (isPremium && teamId) {
      fetchInsights();
    }
  }, [isPremium, teamId, fetchInsights]);

  const seasonTruth = insights?.insights.find(
    (i) => i.type === 'season_truth'
  ) as SeasonTruthInsight | undefined;

  const consistency = insights?.insights.find(
    (i) => i.type === 'consistency_score'
  ) as ConsistencyInsight | undefined;

  const persona = insights?.insights.find(
    (i) => i.type === 'persona'
  ) as PersonaInsight | undefined;

  // Loading state for user check
  if (userLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Brain className="h-4 w-4" />
            Team Insights
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={60} />
        </CardContent>
      </Card>
    );
  }

  // Non-premium users see upgrade prompt
  if (!isPremium) {
    return (
      <Card className="border-l-4 border-l-amber-500/50">
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Brain className="h-4 w-4" />
            Team Insights
          </CardTitle>
          <CardDescription>AI-powered scouting analysis</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-4 text-center">
            <Lock className="h-8 w-8 text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground mb-3">
              Premium feature
            </p>
            <Link href="/upgrade">
              <Button size="sm" variant="outline" className="text-xs">
                Upgrade to unlock
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Loading insights
  if (isLoading) {
    return (
      <Card className="border-l-4 border-l-primary">
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Brain className="h-4 w-4" />
            Team Insights
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={80} />
        </CardContent>
      </Card>
    );
  }

  // Error state
  if (error) {
    return (
      <Card className="border-l-4 border-l-destructive/50">
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Brain className="h-4 w-4" />
            Team Insights
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-2">
            Unable to load insights
          </p>
        </CardContent>
      </Card>
    );
  }

  // No insights data available
  if (!insights || !persona || !consistency || !seasonTruth) {
    return (
      <Card className="border-l-4 border-l-muted">
        <CardHeader className="pb-3">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <Brain className="h-4 w-4" />
            Team Insights
          </CardTitle>
          <CardDescription>AI-powered scouting analysis</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-2">
            Insights not available for this team yet
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-l-4 border-l-primary">
      <CardHeader className="pb-3">
        <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
          <Brain className="h-4 w-4 text-primary" />
          Team Insights
        </CardTitle>
        <CardDescription>AI-powered scouting analysis</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Persona Badge - Most visual, show first */}
        {persona && (
          <div className="flex items-center gap-2">
            <div
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold text-sm',
                persona.label === 'Giant Killer'
                  ? 'bg-purple-500/20 text-purple-700 dark:text-purple-300'
                  : persona.label === 'Flat Track Bully'
                    ? 'bg-orange-500/20 text-orange-700 dark:text-orange-300'
                    : persona.label === 'Gatekeeper'
                      ? 'bg-cyan-500/20 text-cyan-700 dark:text-cyan-300'
                      : 'bg-gray-500/20 text-gray-700 dark:text-gray-300'
              )}
            >
              <Swords className="h-4 w-4" />
              {persona.label === 'Giant Killer' && '🗡️'}
              {persona.label === 'Flat Track Bully' && '💪'}
              {persona.label === 'Gatekeeper' && '🛡️'}
              {persona.label === 'Wildcard' && '🃏'}
              {persona.label}
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="h-4 w-4 text-muted-foreground cursor-help" />
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-[280px]">
                <p className="font-semibold mb-1">Team Persona</p>
                <p className="text-xs">
                  {persona.label === 'Giant Killer'
                    ? 'This team punches above their weight - they consistently beat higher-ranked opponents.'
                    : persona.label === 'Flat Track Bully'
                      ? 'This team dominates weaker opponents but struggles against top competition.'
                      : persona.label === 'Gatekeeper'
                        ? 'A solid, reliable team that wins the games they should and keeps things competitive against stronger teams.'
                        : 'Unpredictable results - this team can beat anyone or lose to anyone on any given day.'}
                </p>
              </TooltipContent>
            </Tooltip>
          </div>
        )}

        {/* Consistency Score */}
        {consistency && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              <Target className="h-4 w-4 text-blue-500" />
              <span className="text-muted-foreground">Consistency</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[280px]">
                  <p className="font-semibold mb-1">Consistency Score (0-100)</p>
                  <p className="text-xs">
                    How predictable is this team? Higher scores mean they perform
                    at a steady level game-to-game. Lower scores mean their results
                    vary wildly - big wins followed by unexpected losses.
                  </p>
                  <p className="text-xs mt-1 text-muted-foreground">
                    75+: Very reliable | 55-74: Steady | 35-54: Unpredictable | &lt;35: Volatile
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-16 h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    consistency.score >= 75
                      ? 'bg-green-500'
                      : consistency.score >= 55
                        ? 'bg-blue-500'
                        : consistency.score >= 35
                          ? 'bg-amber-500'
                          : 'bg-red-500'
                  )}
                  style={{ width: `${consistency.score}%` }}
                />
              </div>
              <span
                className={cn(
                  'text-sm font-mono font-semibold',
                  consistency.score >= 75
                    ? 'text-green-600 dark:text-green-400'
                    : consistency.score >= 55
                      ? 'text-blue-600 dark:text-blue-400'
                      : consistency.score >= 35
                        ? 'text-amber-600 dark:text-amber-400'
                        : 'text-red-600 dark:text-red-400'
                )}
              >
                {consistency.score}
              </span>
            </div>
          </div>
        )}

        {/* Season Truth - Structured list with labels */}
        {seasonTruth && (
          <div className="space-y-2 text-sm">
            {/* Rank Trajectory - Based on recent form (perf_centered) */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Rank Trend</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-[280px]">
                    <p className="font-semibold mb-1">Rank Trend</p>
                    <p className="text-xs">
                      Based on recent game results compared to expectations.
                      Rising means the team is overperforming and their rank will likely
                      improve. Falling means recent results suggest their rank may drop.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <span
                className={cn(
                  'inline-flex items-center gap-1 px-2 py-0.5 rounded font-medium',
                  seasonTruth.details.rankTrajectory === 'rising'
                    ? 'bg-green-500/20 text-green-700 dark:text-green-400'
                    : seasonTruth.details.rankTrajectory === 'falling'
                      ? 'bg-red-500/20 text-red-700 dark:text-red-400'
                      : 'bg-muted text-muted-foreground'
                )}
              >
                {seasonTruth.details.rankTrajectory === 'rising' && <TrendingUp className="h-3 w-3" />}
                {seasonTruth.details.rankTrajectory === 'falling' && <TrendingDown className="h-3 w-3" />}
                {seasonTruth.details.rankTrajectory === 'rising'
                  ? 'Rising'
                  : seasonTruth.details.rankTrajectory === 'falling'
                    ? 'Falling'
                    : 'Stable'}
              </span>
            </div>

            {/* Schedule Strength - Informational context */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Schedule Strength</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-[280px]">
                    <p className="font-semibold mb-1">Strength of Schedule (SOS)</p>
                    <p className="text-xs">
                      How tough are the opponents this team has faced? Higher percentile
                      means tougher competition. A team at 90th percentile has played
                      one of the hardest schedules in their age group.
                    </p>
                    <p className="text-xs mt-1 text-muted-foreground">
                      Note: Our ranking already factors in schedule strength.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <span className="font-mono font-medium">
                {seasonTruth.details.sosPercentile}th %ile
              </span>
            </div>

            {/* Form/Momentum - Only show notable streaks */}
            {seasonTruth.details.formSignal &&
             (seasonTruth.details.formSignal === 'hot_streak' || seasonTruth.details.formSignal === 'cold_streak') && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">Current Form</span>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-[280px]">
                      <p className="font-semibold mb-1">Current Form</p>
                      <p className="text-xs">
                        {seasonTruth.details.formSignal === 'hot_streak'
                          ? 'This team is on fire! They\'re winning games they\'re expected to lose and dominating matches they should win.'
                          : 'This team is struggling. Recent results are below what you\'d expect based on their overall talent level.'}
                      </p>
                    </TooltipContent>
                  </Tooltip>
                </div>
                <span
                  className={cn(
                    'inline-flex items-center gap-1 px-2 py-0.5 rounded font-medium',
                    seasonTruth.details.formSignal === 'hot_streak'
                      ? 'bg-orange-500/20 text-orange-700 dark:text-orange-400'
                      : 'bg-blue-500/20 text-blue-700 dark:text-blue-400'
                  )}
                >
                  {seasonTruth.details.formSignal === 'hot_streak' && <Flame className="h-3 w-3" />}
                  {seasonTruth.details.formSignal === 'cold_streak' && <Snowflake className="h-3 w-3" />}
                  {seasonTruth.details.formSignal === 'hot_streak' ? 'Hot Streak' : 'Cold Streak'}
                </span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
