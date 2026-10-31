'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { STAGE_LABELS, cardUndoStatus, type AppliedChange, type AppliedRun } from '@/lib/mission-control/cleanup';

const UNDO_CARD_URL = '/api/mission-control/cleanup/undo-card';
/** How many matches a search shows at once. */
const SHOWN = 25;

function RunChanges({ run, onUndo }: { run: AppliedRun; onUndo: (change: AppliedChange) => void }) {
  const [query, setQuery] = useState('');
  const matches = useMemo(() => {
    const words = query.trim().toLowerCase();
    return words ? run.changes.filter((change) => change.text.toLowerCase().includes(words)) : [];
  }, [run.changes, query]);

  return (
    <div className="space-y-2" data-testid="applied-run">
      <h3 className="font-bold">
        {run.open ? 'This week' : 'Last run'} ({run.runId}): {run.changes.length} change
        {run.changes.length === 1 ? '' : 's'} applied
      </h3>
      <input
        type="search"
        aria-label={`Find a change of run ${run.runId}`}
        placeholder="Find a team"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        className="min-h-10 w-full rounded-md border bg-background px-2 text-base"
      />
      {query.trim() && !matches.length && <p className="text-sm text-muted-foreground">No change names that.</p>}
      <ul className="space-y-2 text-sm">
        {matches.slice(0, SHOWN).map((change) => (
          <li key={change.cardId} className="flex flex-wrap items-center gap-2" data-testid="applied-change">
            <span className="min-w-0 flex-1 break-words">
              <span className="text-muted-foreground">{STAGE_LABELS[change.stage]}:</span> {change.text}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={change.undo?.status === 'pending' || change.undo?.status === 'done'}
              onClick={() => onUndo(change)}
            >
              Undo
            </Button>
            {change.undo && <span className="w-full text-muted-foreground">{cardUndoStatus(change.undo)}</span>}
          </li>
        ))}
      </ul>
      {matches.length > SHOWN && (
        <p className="text-sm text-muted-foreground">
          Showing {SHOWN} of {matches.length}; type more of the name to narrow it.
        </p>
      )}
    </div>
  );
}

/** Each change the run in review and the last finished run applied, any one of which can be undone alone. */
export function AppliedChanges() {
  const [runs, setRuns] = useState<AppliedRun[] | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [undoing, setUndoing] = useState<{ runId: string; change: AppliedChange } | null>(null);
  const [decline, setDecline] = useState(true);
  const [asking, setAsking] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(UNDO_CARD_URL, { cache: 'no-store' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      setRuns(data.runs as AppliedRun[]);
    } catch (error) {
      setStatus(`Could not load the applied changes: ${error instanceof Error ? error.message : 'try again'}.`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const ask = useCallback(async () => {
    if (!undoing) return;
    setAsking(true);
    try {
      const res = await fetch(UNDO_CARD_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runId: undoing.runId, cardId: undoing.change.cardId, decline }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      setStatus('Undo asked: the next hourly run in the apply window does it.');
    } catch (error) {
      setStatus(`Undo not asked for: ${error instanceof Error ? error.message : 'try again'}.`);
    } finally {
      setUndoing(null);
      setAsking(false);
      await load();
    }
  }, [undoing, decline, load]);

  if (!runs?.length && !status) return null;
  const merge = undoing?.change.stage === 'merges';

  return (
    <section id="undo-one-change" aria-label="Undo one change" className="space-y-3 pt-6">
      <h2 className="font-display text-2xl font-bold tracking-tight">Undo one change</h2>
      <p className="text-sm text-muted-foreground">
        Find a team to undo just its change. The next hourly run in the apply window puts it back.
      </p>
      {status && (
        <p className="text-sm text-muted-foreground" role="status">
          {status}
        </p>
      )}
      {runs?.map((run) => (
        <RunChanges key={run.runId} run={run} onUndo={(change) => setUndoing({ runId: run.runId, change })} />
      ))}
      <Dialog open={undoing !== null} onOpenChange={(open) => !asking && !open && setUndoing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Undo this change?</DialogTitle>
            <DialogDescription>{undoing?.change.text}</DialogDescription>
          </DialogHeader>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={decline} onChange={(event) => setDecline(event.target.checked)} />
            {merge ? 'Keep these two teams separate from now on' : "Don't propose this change again"}
          </label>
          <DialogFooter>
            <Button variant="outline" onClick={() => setUndoing(null)} disabled={asking}>
              Keep it
            </Button>
            <Button onClick={() => void ask()} disabled={asking}>
              {asking ? 'Asking…' : 'Undo'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
