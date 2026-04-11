'use client';

import { Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import { explainGameBreakdown } from '@/lib/gameExplainer';
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

export function GameBreakdownPanel({ breakdown, isLoading }: GameBreakdownPanelProps) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="h-14 animate-pulse rounded-lg border bg-muted/40" />
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
  const toneLabel =
    explanation.tone === 'positive'
      ? 'Above expectation'
      : explanation.tone === 'negative'
        ? 'Below expectation'
        : 'Close to expectation';

  return (
    <div className="space-y-4 rounded-xl border bg-background p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <p className="text-sm font-semibold">{explanation.headline}</p>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{explanation.expectationLine}</p>
          <p className="mt-1 text-sm text-muted-foreground">{explanation.actualLine}</p>
        </div>
        <span
          className={cn(
            'inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold',
            toneClasses(explanation.tone)
          )}
        >
          {toneLabel}
        </span>
      </div>

      {explanation.details.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {explanation.details.map((detail, index) => (
            <div key={`${detail}-${index}`} className="rounded-lg border bg-muted/10 p-3">
              <p className={cn('text-sm font-semibold', toneTextClasses(explanation.tone))}>{detail}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed bg-muted/10 p-3 text-sm text-muted-foreground">
          Nothing major stood out beyond the result itself.
        </div>
      )}
    </div>
  );
}
