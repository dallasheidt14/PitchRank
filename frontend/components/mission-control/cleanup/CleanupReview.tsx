'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { AppError } from '@/lib/errors';
import { cn } from '@/lib/utils';
import {
  CLEANUP_DECISIONS,
  CLEANUP_LANES,
  EMPTY_CHOICE,
  MAX_CARDS_PER_WRITE,
  STAGE_LABELS,
  UNDO_LABELS,
  alikeSets,
  changeValue,
  choiceOf,
  fieldLabel,
  groupCards,
  isPairRow,
  survivorFirst,
  tally,
  undoStatus,
  type CardRow,
  type Choice,
  type CleanupDecision,
  type CleanupLane,
  type CleanupReview as Review,
  type CleanupStage,
  type PairCardRow,
  type PreviousRun,
  type StageReview,
  type TeamCardRow,
  type UndoRequest,
} from '@/lib/mission-control/cleanup';
import { CleanupCardView, DECISION_TONE } from './CleanupCardView';
import { PairCardView } from './PairCardView';

const REVIEW_URL = '/api/mission-control/cleanup';
const DECISIONS_URL = '/api/mission-control/cleanup/decisions';
const DONE_URL = '/api/mission-control/cleanup/done';
const UNDO_URL = '/api/mission-control/cleanup/undo';
const TALLY_LABELS: Record<CleanupDecision, string> = { apply: 'apply', dont_apply: "don't apply", unsure: 'unsure' };
const PAIR_TALLY_LABELS: Record<CleanupDecision, string> = {
  apply: 'merge',
  dont_apply: 'keep separate',
  unsure: 'unsure',
};

type Choices = Record<string, Choice>;
type Patch = { decision?: CleanupDecision | null; note?: string; swap?: boolean };
type Saved = { card_id: string } & Pick<CardRow, 'decision' | 'note' | 'swap'>;

/** GET the URL, or POST `body` to it as JSON. A refusal throws an AppError carrying its status. */
async function requestJson<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(
    url,
    body === undefined
      ? { cache: 'no-store' }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new AppError(data.error || `HTTP ${res.status}`, undefined, res.status);
  return data as T;
}

function isConflict(error: unknown): boolean {
  return error instanceof AppError && error.statusCode === 409;
}

function reasonOf(error: unknown): string {
  return error instanceof Error ? error.message : 'try again in a moment';
}

function choicesOf(review: Review): Choices {
  const choices: Choices = {};
  for (const stage of review.stages) {
    for (const row of stage.cards) choices[row.card_id] = choiceOf(row);
  }
  return choices;
}

function chunks<T>(items: T[], size: number): T[][] {
  return Array.from({ length: Math.ceil(items.length / size) }, (_, i) => items.slice(i * size, (i + 1) * size));
}

export function CleanupReview() {
  const [review, setReview] = useState<Review | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [choices, setChoices] = useState<Choices>({});
  const [active, setActive] = useState<CleanupStage | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [marking, setMarking] = useState(false);
  const [undoing, setUndoing] = useState<{ runId: string; stage: CleanupStage; lane: CleanupLane } | null>(null);
  const [asking, setAsking] = useState(false);
  // The choices as shown, ahead of the database while saves are in flight; the database's, as last loaded
  // or saved, for a failed save to go back to; the saves still to land per card; how many have failed, and
  // how many had when Done was asked for. One save runs at a time, so a decision and a note on one card land
  // in the order they were made.
  const shownChoices = useRef<Choices>({});
  const confirmed = useRef<Choices>({});
  const pending = useRef<Record<string, number>>({});
  const failures = useRef(0);
  const failuresAtDone = useRef(0);
  const queue = useRef<Promise<void>>(Promise.resolve());

  const showChoices = useCallback((next: Choices) => {
    shownChoices.current = next;
    setChoices(next);
  }, []);

  const load = useCallback(async () => {
    try {
      const next = await requestJson<Review>(REVIEW_URL);
      confirmed.current = choicesOf(next);
      setReview(next);
      showChoices(choicesOf(next));
      setLoadError(null);
      setActive((current) =>
        current && next.stages.some((s) => s.stage === current) ? current : (next.stages[0]?.stage ?? null)
      );
    } catch (error) {
      setLoadError(reasonOf(error));
    }
  }, [showChoices]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = review?.run ?? null;
  const locked = !run || run.status !== 'reviewing' || !!run.ownerDoneAt;
  const editable = !locked && !marking;

  const save = useCallback(
    (stage: StageReview, ids: string[], patch: Patch, onlyUndecided = false): Promise<void> => {
      if (!run) return Promise.resolve();
      const current = shownChoices.current;
      const targets = ids.filter((id) => !(onlyUndecided && current[id]?.decision));
      if (!targets.length) return Promise.resolve();
      const next = { ...current };
      for (const id of targets) {
        next[id] = {
          decision: 'decision' in patch ? (patch.decision ?? null) : current[id].decision,
          note: 'note' in patch ? (patch.note ?? '').trim() : current[id].note,
          swap: patch.swap ?? current[id].swap,
        };
        pending.current[id] = (pending.current[id] ?? 0) + 1;
      }
      showChoices(next);

      const body = {
        runId: run.runId,
        stage: stage.stage,
        pageRun: stage.pageRun,
        cardIds: targets,
        ...patch,
        ...(onlyUndecided ? { onlyUndecided: true } : {}),
      };
      const task = queue.current.then(async () => {
        let failed: unknown = null;
        try {
          const { updated } = await requestJson<{ updated: Saved[] }>(DECISIONS_URL, body);
          const saved = { ...confirmed.current };
          for (const row of updated) saved[row.card_id] = choiceOf(row);
          confirmed.current = saved;
        } catch (error) {
          failed = error;
          failures.current += 1;
        }
        // Once a card's last save lands it shows the last choice the database confirmed: what this save stored,
        // or, when the save failed or left the card alone (decided meanwhile elsewhere), the choice last loaded
        // or saved.
        const shown = { ...shownChoices.current };
        for (const id of targets) {
          pending.current[id] -= 1;
          if (pending.current[id] > 0) continue;
          delete pending.current[id];
          shown[id] = confirmed.current[id];
        }
        showChoices(shown);
        if (failed) {
          setStatus(
            isConflict(failed)
              ? `Not saved: ${reasonOf(failed)}. The page has been reloaded.`
              : `Not saved: ${reasonOf(failed)}.`
          );
          if (isConflict(failed)) void load();
        }
      });
      queue.current = task;
      return task;
    },
    [run, showChoices, load]
  );

  const decideOpen = useCallback(
    async (stage: StageReview, ids: string[], decision: CleanupDecision) => {
      setBulkBusy(true);
      try {
        // Every part joins the queue now, so a Done clicked meanwhile waits for all of them.
        await Promise.all(chunks(ids, MAX_CARDS_PER_WRITE).map((part) => save(stage, part, { decision }, true)));
      } finally {
        setBulkBusy(false);
      }
    },
    [save]
  );

  const markDone = useCallback(async () => {
    if (!run) return;
    setMarking(true);
    await queue.current;
    if (failures.current > failuresAtDone.current) {
      setConfirming(false);
      setMarking(false);
      setStatus('A choice did not save, so the review is not marked done. Check the cards and try again.');
      return;
    }
    try {
      await requestJson(DONE_URL, { runId: run.runId });
      setConfirming(false);
      setStatus('Marked done. Your choices are locked.');
      await load();
    } catch (error) {
      setStatus(`Not marked done: ${reasonOf(error)}.`);
      if (isConflict(error)) await load();
    } finally {
      setMarking(false);
    }
  }, [run, load]);

  const askUndo = useCallback(async () => {
    if (!undoing) return;
    setAsking(true);
    try {
      await requestJson(UNDO_URL, undoing);
      setStatus(`${UNDO_LABELS[undoing.lane].replace('Undo', 'Undoing')}: asked, the next hourly run does it.`);
      await load();
    } catch (error) {
      setStatus(`Undo not asked for: ${reasonOf(error)}.`);
      if (isConflict(error)) await load();
    } finally {
      setUndoing(null);
      setAsking(false);
    }
  }, [undoing, load]);

  const stage = review?.stages.find((s) => s.stage === active) ?? null;
  const undecidedTotal = useMemo(
    () => (review?.stages ?? []).reduce((n, s) => n + tally(s.cards, choices).undecided, 0),
    [review, choices]
  );

  if (!review) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">{loadError ? `Could not load: ${loadError}` : 'Loading…'}</p>
        {loadError && (
          <Button variant="outline" size="sm" onClick={() => void load()}>
            Try again
          </Button>
        )}
      </div>
    );
  }

  const undoDialog = (
    <Dialog open={undoing !== null} onOpenChange={(open) => !asking && !open && setUndoing(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{undoing && `${UNDO_LABELS[undoing.lane]} in ${STAGE_LABELS[undoing.stage]}?`}</DialogTitle>
          <DialogDescription>
            The next hourly run puts back every one of these changes that has been applied, or undoes them as soon as
            they apply. An undone change is not applied automatically again.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setUndoing(null)} disabled={asking}>
            Keep them
          </Button>
          <Button onClick={() => void askUndo()} disabled={asking}>
            {asking ? 'Asking…' : 'Undo'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
  const previous = review.previous && (
    <PreviousRunUndo
      previous={review.previous}
      onUndo={(stage, lane) => setUndoing({ runId: review.previous!.runId, stage, lane })}
    />
  );

  if (!run) {
    return (
      <div className="space-y-4">
        <p className="text-muted-foreground">No cleanup run is open right now.</p>
        {status && (
          <p className="text-sm text-muted-foreground" role="status">
            {status}
          </p>
        )}
        {previous}
        {undoDialog}
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-24">
      <div className="space-y-1">
        <p className="text-sm text-muted-foreground">
          Run {run.runId} · {run.states.join(', ')}
        </p>
        {run.ownerDoneAt ? (
          <p className="rounded-md border bg-muted p-2.5 text-sm" data-testid="cleanup-locked">
            Marked done {run.ownerDoneLabel}
            {run.ownerDoneBy === 'deadline' ? ' at the deadline' : ''}. Your choices are locked.
          </p>
        ) : run.status === 'proposing' ? (
          <p className="rounded-md border bg-muted p-2.5 text-sm" data-testid="cleanup-locked">
            This run is still proposing changes, so its review has not started.
          </p>
        ) : (
          run.status !== 'reviewing' && (
            <p className="rounded-md border bg-muted p-2.5 text-sm" data-testid="cleanup-locked">
              This run is past review, so its choices are locked.
            </p>
          )
        )}
      </div>

      {review.stages.length === 0 ? (
        <p className="text-muted-foreground">No review page is published for this run yet.</p>
      ) : (
        <div role="tablist" aria-label="Stages" className="flex flex-wrap gap-2">
          {review.stages.map((s) => (
            <button
              key={s.stage}
              type="button"
              role="tab"
              aria-selected={s.stage === active}
              onClick={() => setActive(s.stage)}
              className={cn(
                'min-h-10 rounded-full border px-4 text-sm font-medium',
                s.stage === active ? 'border-primary bg-primary text-primary-foreground' : 'bg-background'
              )}
            >
              {STAGE_LABELS[s.stage]} · {tally(s.cards, choices).undecided} left
            </button>
          ))}
        </div>
      )}

      {status && (
        <p className="text-sm text-muted-foreground" role="status">
          {status}
        </p>
      )}

      {stage && (
        <StageView
          key={stage.stage}
          stage={stage}
          choices={choices}
          editable={editable}
          bulkBusy={bulkBusy}
          onSave={save}
          onDecideOpen={decideOpen}
          undo={run.status === 'reviewing' ? (review.undo ?? []).filter((r) => r.stage === stage.stage) : null}
          onUndo={(lane) => setUndoing({ runId: run.runId, stage: stage.stage, lane })}
        />
      )}

      {run.status === 'reviewing' && !run.ownerDoneAt && review.stages.length > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-10 border-t bg-background/95 px-4 py-3 backdrop-blur">
          <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
            <span className="text-sm text-muted-foreground">{undecidedTotal} undecided in all stages</span>
            <Button
              onClick={() => {
                failuresAtDone.current = failures.current;
                setConfirming(true);
              }}
              disabled={marking}
            >
              Mark review done
            </Button>
          </div>
        </div>
      )}

      {previous}
      {undoDialog}

      <Dialog open={confirming} onOpenChange={(open) => !marking && setConfirming(open)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Mark this week&apos;s review done?</DialogTitle>
            <DialogDescription>
              Your choices lock. The cards you decided are applied, and the {undecidedTotal} you left undecided come
              back next week.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)} disabled={marking}>
              Keep reviewing
            </Button>
            <Button onClick={() => void markDone()} disabled={marking}>
              {marking ? 'Marking…' : 'Mark done'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StageView({
  stage,
  choices,
  editable,
  bulkBusy,
  onSave,
  onDecideOpen,
  undo,
  onUndo,
}: {
  stage: StageReview;
  choices: Choices;
  editable: boolean;
  bulkBusy: boolean;
  onSave: (stage: StageReview, ids: string[], patch: Patch, onlyUndecided?: boolean) => Promise<void>;
  onDecideOpen: (stage: StageReview, ids: string[], decision: CleanupDecision) => Promise<void>;
  /** The stage's latest undo request per lane; null when the run is past review and nothing can be undone here. */
  undo: UndoRequest[] | null;
  onUndo: (lane: CleanupLane) => void;
}) {
  const [show, setShow] = useState('');
  const groups = useMemo(() => groupCards(stage.cards), [stage.cards]);
  const alike = useMemo(() => alikeSets(stage.cards), [stage.cards]);
  const counts = tally(stage.cards, choices);
  const undecided = (ids: string[]) => ids.filter((id) => !choices[id]?.decision);
  const cleared = undecided(
    stage.cards.filter((row) => isPairRow(row) && row.card.capped === 'merge').map((row) => row.card_id)
  );
  const visible = (row: CardRow) =>
    (show !== 'open' || !choices[row.card_id]?.decision) && (!show.startsWith('g:') || show === `g:${row.card.group}`);

  return (
    <section className="space-y-4" aria-label={`${STAGE_LABELS[stage.stage]} review`}>
      {stage.stage === 'merges' ? (
        <p className="max-w-prose text-sm text-muted-foreground">
          {stage.cards.length} pair{stage.cards.length === 1 ? '' : 's'} of teams that may be one team. Choose Merge
          them, Keep separate or Not sure on each, and Keep the other one to keep the team the card would merge away.
          Keep separate is remembered, so the pair is not proposed again. Choices save as you go.
        </p>
      ) : (
        <p className="max-w-prose text-sm text-muted-foreground">
          {stage.cards.length} proposed change{stage.cards.length === 1 ? '' : 's'}. Choose Apply, Don&apos;t apply or
          Not sure on each, and add a note if you know something the data doesn&apos;t. Don&apos;t apply is remembered,
          so the same change is not proposed again. Choices save as you go.
        </p>
      )}

      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2.5 border-b bg-background py-2.5">
        <label htmlFor="cleanup-show" className="text-sm">
          Show
        </label>
        <select
          id="cleanup-show"
          value={show}
          onChange={(event) => setShow(event.target.value)}
          className="min-h-10 rounded-md border bg-background px-2 text-base"
        >
          <option value="">All</option>
          <option value="open">Not decided</option>
          {groups.map((g) => (
            <option key={g.group} value={`g:${g.group}`}>
              Tier {g.group}
            </option>
          ))}
        </select>
        <div className="ml-auto flex flex-wrap gap-2 text-xs tabular-nums" data-testid="cleanup-tally">
          {CLEANUP_DECISIONS.map((decision) => (
            <span key={decision} className={cn('rounded-full px-2 py-0.5', DECISION_TONE[decision].chip)}>
              {counts[decision]} {(stage.stage === 'merges' ? PAIR_TALLY_LABELS : TALLY_LABELS)[decision]}
            </span>
          ))}
          <span className="rounded-full bg-muted px-2 py-0.5">{counts.undecided} left</span>
        </div>
        {cleared.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            disabled={!editable || bulkBusy}
            onClick={() => void onDecideOpen(stage, cleared, 'apply')}
          >
            {cleared.length === 1
              ? 'Merge the one the reviewers cleared'
              : `Merge all ${cleared.length} the reviewers cleared`}
          </Button>
        )}
      </div>

      {groups.map((g) => {
        const rows = g.cards.filter(visible);
        if (!rows.length) return null;
        const open = undecided(g.cards.map((row) => row.card_id));
        return (
          <div key={g.group} className="space-y-2.5">
            <div className="flex flex-wrap items-center gap-2.5 pt-1.5">
              <h2 className="font-display text-lg font-medium">Tier {g.group}</h2>
              <span className="text-sm text-muted-foreground tabular-nums">
                {g.cards.length} card{g.cards.length === 1 ? '' : 's'}, {open.length} undecided
              </span>
              {g.whole && stage.stage !== 'merges' && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!editable || !open.length || bulkBusy}
                  onClick={() => void onDecideOpen(stage, open, 'apply')}
                >
                  Apply every undecided card here
                </Button>
              )}
            </div>
            {rows.map((row) => {
              const set = row.card.alike ? (alike.get(row.card.alike) ?? []) : [];
              const choice = choices[row.card_id] ?? EMPTY_CHOICE;
              if (isPairRow(row)) {
                return (
                  <PairCardView
                    key={row.card_id}
                    row={row}
                    choice={choice}
                    editable={editable}
                    onDecide={(decision) => void onSave(stage, [row.card_id], { decision })}
                    onSwap={(swap) => void onSave(stage, [row.card_id], { swap })}
                    onNote={(note) => void onSave(stage, [row.card_id], { note })}
                  />
                );
              }
              return (
                <CleanupCardView
                  key={row.card_id}
                  row={row}
                  choice={choice}
                  editable={editable}
                  bulkBusy={bulkBusy}
                  alikeUndecided={set.length > 1 ? undecided(set).length : 0}
                  onDecide={(decision) => void onSave(stage, [row.card_id], { decision })}
                  onDecideAlike={(decision) => void onDecideOpen(stage, undecided(set), decision)}
                  onNote={(note) => void onSave(stage, [row.card_id], { note })}
                />
              );
            })}
          </div>
        );
      })}

      {stage.auto.length > 0 && (
        <details className="rounded-lg border bg-card p-3.5" data-testid="cleanup-auto">
          <summary className="cursor-pointer font-medium">
            {stage.auto.length} change{stage.auto.length === 1 ? '' : 's'} the evidence settles, applied without a card
          </summary>
          <ul className="mt-2.5 space-y-2 text-sm">
            {stage.auto.map((row) => (
              <li key={row.card_id} className="break-words">
                {isPairRow(row) ? <AutoPair row={row} /> : <AutoChange row={row} />}
                {row.card.sure && <span className="text-muted-foreground"> ({row.card.sure})</span>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {undo && (
        <div className="space-y-2 rounded-lg border bg-card p-3.5 text-sm" data-testid="cleanup-undo">
          <div className="flex flex-wrap gap-2">
            {(stage.auto.length > 0 ? (['auto', 'owner'] as const) : (['owner'] as const)).map((lane) => (
              <Button
                key={lane}
                variant="outline"
                size="sm"
                disabled={undo.some((r) => r.lane === lane && r.status === 'pending')}
                onClick={() => onUndo(lane)}
              >
                {UNDO_LABELS[lane]}
              </Button>
            ))}
          </div>
          {undo.map((r) => (
            <p key={r.lane} className="m-0 text-muted-foreground">
              {undoStatus(r)}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

/** An automatic merge on one line: the team merged away, then the one it is kept as; or the two teams the
 * reviewers found to be different, kept separate. */
function AutoPair({ row }: { row: PairCardRow }) {
  const [kept, merged] = survivorFirst(row.card, row.swap);
  if (row.card.keep_separate) {
    return (
      <>
        <span className="font-medium">{merged.name || '(no name)'}</span> and{' '}
        <span className="font-medium">{kept.name || '(no name)'}</span> kept separate
      </>
    );
  }
  return (
    <>
      <span className="font-medium">{merged.name || '(no name)'}</span> → kept as{' '}
      <span className="font-medium">{kept.name || '(no name)'}</span>
    </>
  );
}

function AutoChange({ row }: { row: TeamCardRow }) {
  const { team, change } = row.card;
  const name = <span className="font-medium">{team.name || '(no name)'}</span>;
  if (row.card.keep_as_is) {
    const declined = change.new === change.old ? '' : `, not ${changeValue(change.new)}`;
    return (
      <>
        {name}: {fieldLabel(change.field)} kept as {changeValue(change.old)}
        {declined}
      </>
    );
  }
  return (
    <>
      {name}: {fieldLabel(change.field)} {changeValue(change.old)} → {changeValue(change.new)}
    </>
  );
}

/** The last finished run's lanes, each with an Undo button and its latest request's status. */
function PreviousRunUndo({
  previous,
  onUndo,
}: {
  previous: PreviousRun;
  onUndo: (stage: CleanupStage, lane: CleanupLane) => void;
}) {
  return (
    <section
      className="space-y-3 rounded-lg border bg-card p-3.5 text-sm"
      aria-label="Last run's changes"
      data-testid="cleanup-previous"
    >
      <div className="space-y-1">
        <h2 className="font-display text-lg font-medium">Last run&apos;s changes ({previous.runId})</h2>
        <p className="m-0 text-muted-foreground">
          If something it applied looks wrong, undo that category&apos;s changes and the next hourly run puts them back.
        </p>
      </div>
      {previous.stages.map((stage) => {
        const requests = previous.undo.filter((r) => r.stage === stage);
        return (
          <div key={stage} className="space-y-1.5" data-testid="cleanup-previous-stage">
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-24 font-medium">{STAGE_LABELS[stage]}</span>
              {CLEANUP_LANES.map((lane) => (
                <Button
                  key={lane}
                  variant="outline"
                  size="sm"
                  disabled={requests.some((r) => r.lane === lane && r.status === 'pending')}
                  onClick={() => onUndo(stage, lane)}
                >
                  {UNDO_LABELS[lane]}
                </Button>
              ))}
            </div>
            {requests.map((r) => (
              <p key={r.lane} className="m-0 text-muted-foreground">
                {undoStatus(r)}
              </p>
            ))}
          </div>
        );
      })}
    </section>
  );
}
