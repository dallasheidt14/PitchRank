'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  CLEAN_WEEKS_TO_RAISE,
  survivorFirst,
  type PairSide,
  type SpotCheck,
  type SpotCheckReview as Review,
  type SpotVerdict,
} from '@/lib/mission-control/cleanup';
import { NoteBox, TeamLines } from './CleanupCardView';

const SPOT_CHECK_URL = '/api/mission-control/cleanup/spot-check';
const VERDICT_LABELS: Record<SpotVerdict, string> = { right: 'Right', wrong: 'Wrong' };
const VERDICT_TONE: Record<SpotVerdict, string> = {
  right: 'border-emerald-700 bg-emerald-50 text-emerald-800',
  wrong: 'border-red-700 bg-red-50 text-red-800',
};

function Side({ side, kept }: { side: PairSide; kept: boolean }) {
  return (
    <div className={cn('grid content-start gap-1 rounded-md border p-2.5', kept ? 'border-primary bg-muted' : '')}>
      <span className="text-[11px] tracking-wide text-muted-foreground uppercase">
        {kept ? 'Kept' : 'Merged into the kept team'}
      </span>
      {kept ? (
        <a href={`/teams/${side.team_id}`} className="font-bold break-words underline">
          {side.name || '(no name)'}
        </a>
      ) : (
        <span className="font-bold break-words">{side.name || '(no name)'}</span>
      )}
      <TeamLines team={side} />
    </div>
  );
}

function CheckView({
  check,
  busy,
  onJudge,
}: {
  check: SpotCheck;
  busy: boolean;
  onJudge: (verdict: SpotVerdict | null, note: string) => void;
}) {
  const [kept, merged] = survivorFirst(check.card, check.swap);
  return (
    <article
      data-testid="spot-check"
      data-verdict={check.verdict ?? ''}
      className="grid gap-2.5 rounded-lg border p-3.5"
    >
      <span className="font-display text-sm text-muted-foreground">#{check.position}</span>
      <div className="grid gap-2.5 sm:grid-cols-2">
        <Side side={kept} kept />
        <Side side={merged} kept={false} />
      </div>
      <p className="m-0 border-l-[3px] border-border pl-2.5 text-sm">{check.card.why}</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Was this merge right?">
        {(Object.keys(VERDICT_LABELS) as SpotVerdict[]).map((verdict) => (
          <button
            key={verdict}
            type="button"
            aria-pressed={check.verdict === verdict}
            disabled={busy}
            onClick={() => onJudge(check.verdict === verdict ? null : verdict, check.note ?? '')}
            className={cn(
              'min-h-10 rounded-md border px-3 text-sm font-semibold disabled:opacity-50',
              check.verdict === verdict ? VERDICT_TONE[verdict] : 'bg-background'
            )}
          >
            {VERDICT_LABELS[verdict]}
          </button>
        ))}
      </div>
      <NoteBox note={check.note ?? ''} editable={!busy} onNote={(note) => onJudge(check.verdict, note)} />
    </article>
  );
}

/** The newest runs' samples of their automatic merges, for the owner to mark each right or wrong. */
export function SpotCheckReview() {
  const [review, setReview] = useState<Review | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(SPOT_CHECK_URL, { cache: 'no-store' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      setReview(data as Review);
    } catch (error) {
      setStatus(`Could not load the spot-check: ${error instanceof Error ? error.message : 'try again'}.`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const judge = useCallback(
    async (runId: string, check: SpotCheck, verdict: SpotVerdict | null, note: string) => {
      setBusy(check.cardId);
      try {
        const res = await fetch(SPOT_CHECK_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ runId, cardId: check.cardId, verdict, note }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        setStatus(null);
      } catch (error) {
        setStatus(`Not saved: ${error instanceof Error ? error.message : 'try again'}.`);
      } finally {
        await load();
        setBusy(null);
      }
    },
    [load]
  );

  return (
    <section id="spot-check" aria-label="Spot-check" className="space-y-3 pt-6">
      <h2 className="font-display text-2xl font-bold tracking-tight">Spot-check of automatic merges</h2>
      {status && (
        <p className="text-sm text-muted-foreground" role="status">
          {status}
        </p>
      )}
      {review && (
        <p className="text-sm" data-testid="spot-check-weeks">
          Clean weeks in a row: {review.cleanWeeks} of {CLEAN_WEEKS_TO_RAISE}. The automatic merge cap can double after{' '}
          {CLEAN_WEEKS_TO_RAISE} weeks with every sampled merge marked right.
        </p>
      )}
      {review && !review.runs.length && (
        <p className="text-sm text-muted-foreground">No automatic merges have been sampled yet.</p>
      )}
      {review?.runs.map((run) => (
        <div key={run.runId} className="space-y-2" data-testid="spot-check-run">
          <h3 className="font-bold">
            Run {run.runId}: {run.checks.filter((check) => check.verdict).length} of {run.checks.length} marked
          </h3>
          {run.checks.map((check) => (
            <CheckView
              key={check.cardId}
              check={check}
              busy={busy !== null}
              onJudge={(verdict, note) => void judge(run.runId, check, verdict, note)}
            />
          ))}
        </div>
      ))}
      {!review && !status && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!review && status && (
        <Button variant="outline" size="sm" onClick={() => void load()}>
          Try again
        </Button>
      )}
    </section>
  );
}
