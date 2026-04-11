'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { Lock, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { explainGameBreakdown } from '@/lib/gameExplainer';
import { trackPaywallImpression, trackPaywallUpgradeClicked } from '@/lib/events';
import type { GameExplainability } from '@/lib/types';

interface GameBreakdownPanelProps {
  teamId: string;
  gameId: string;
  breakdown?: GameExplainability;
  isPremium: boolean;
  isLoading: boolean;
}

function toneClasses(tone: 'positive' | 'negative' | 'neutral') {
  if (tone === 'positive') {
    return 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-300 border-emerald-500/20';
  }
  if (tone === 'negative') {
    return 'bg-rose-500/12 text-rose-700 dark:text-rose-300 border-rose-500/20';
  }
  return 'bg-muted text-muted-foreground border-border';
}

function toneTextClasses(tone: 'positive' | 'negative' | 'neutral') {
  if (tone === 'positive') return 'text-emerald-700 dark:text-emerald-300';
  if (tone === 'negative') return 'text-rose-700 dark:text-rose-300';
  return 'text-foreground';
}

export function GameBreakdownPanel({ teamId, gameId, breakdown, isPremium, isLoading }: GameBreakdownPanelProps) {
  useEffect(() => {
    if (!isPremium) {
      trackPaywallImpression({
        feature: 'game_explainability',
        location: 'game_history_table',
        team_id: teamId,
      });
    }
  }, [isPremium, teamId]);

  if (!isPremium) {
    return (
      <div className="relative overflow-hidden rounded-xl border bg-background p-4">
        <div className="space-y-4 blur-[2px] select-none" aria-hidden="true">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border px-2.5 py-1 text-xs font-semibold text-emerald-700 border-emerald-500/20 bg-emerald-500/12">
              Meaningful rating swing
            </span>
            <span className="rounded-full border px-2.5 py-1 text-xs font-semibold text-slate-700 border-slate-400/20 bg-slate-500/8">
              Recent result carried extra weight
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            <div className="rounded-lg border bg-muted/30 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Expected result</p>
              <p className="mt-1 text-sm font-semibold">58%</p>
            </div>
            <div className="rounded-lg border bg-muted/30 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Actual result</p>
              <p className="mt-1 text-sm font-semibold">81%</p>
            </div>
            <div className="rounded-lg border bg-muted/30 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Rating impact</p>
              <p className="mt-1 text-sm font-semibold">+0.142</p>
            </div>
            <div className="rounded-lg border bg-muted/30 p-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Recency weight</p>
              <p className="mt-1 text-sm font-semibold">High</p>
            </div>
          </div>
        </div>

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-background/70 text-center backdrop-blur-[1px]">
          <Lock className="h-5 w-5 text-muted-foreground" />
          <p className="max-w-sm text-sm text-muted-foreground">
            Unlock the full game breakdown to see why this result moved the rating.
          </p>
          <Link
            href={`/upgrade?source=game_explainability&team=${teamId}&game=${gameId}`}
            onClick={() =>
              trackPaywallUpgradeClicked({
                feature: 'game_explainability',
                location: 'game_history_table',
                team_id: teamId,
              })
            }
          >
            <Button size="sm">
              <Lock className="mr-1 h-3.5 w-3.5" />
              Upgrade to Unlock
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="h-20 animate-pulse rounded-lg border bg-muted/40" />
        ))}
      </div>
    );
  }

  if (!breakdown) {
    return (
      <div className="rounded-xl border border-dashed bg-muted/20 p-4 text-sm text-muted-foreground">
        Breakdown unavailable for this game yet. It may not have been persisted in the latest ranking run.
      </div>
    );
  }

  const explanation = explainGameBreakdown(breakdown);

  return (
    <div className="space-y-4 rounded-xl border bg-background p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <p className="text-sm font-semibold">{explanation.headline}</p>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{explanation.summary}</p>
        </div>
        <span
          className={cn(
            'inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold',
            toneClasses(explanation.impactTone)
          )}
        >
          {explanation.impactLabel}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        {explanation.metrics.map((metric) => (
          <div key={metric.label} className="rounded-lg border bg-muted/20 p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{metric.label}</p>
            <p className="mt-1 text-sm font-semibold">{metric.value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {explanation.factors.length > 0 ? (
          explanation.factors.map((factor) => (
            <div key={factor.label} className="rounded-lg border bg-muted/10 p-3">
              <p className={cn('text-sm font-semibold', toneTextClasses(factor.tone))}>
                {factor.label}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">{factor.detail}</p>
            </div>
          ))
        ) : (
          <div className="rounded-lg border border-dashed bg-muted/10 p-3 text-sm text-muted-foreground sm:col-span-2">
            This game looked fairly ordinary relative to expectation, so there were no standout drivers beyond the
            final result itself.
          </div>
        )}
      </div>
    </div>
  );
}
