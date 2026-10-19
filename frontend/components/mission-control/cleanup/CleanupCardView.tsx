'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import {
  CLEANUP_DECISIONS,
  DECISION_LABELS,
  changeValue,
  fieldLabel,
  type CardRow,
  type Choice,
  type CleanupDecision,
} from '@/lib/mission-control/cleanup';

const GENDER: Record<string, string> = { Male: 'boys', Female: 'girls' };

/** Each decision's colours: its pressed button, the card's edge and its tally chip. */
export const DECISION_TONE: Record<CleanupDecision, { pressed: string; edge: string; chip: string }> = {
  apply: {
    pressed: 'border-emerald-700 bg-emerald-50 text-emerald-800',
    edge: 'border-l-emerald-700',
    chip: 'bg-emerald-50 text-emerald-800',
  },
  dont_apply: {
    pressed: 'border-red-700 bg-red-50 text-red-800',
    edge: 'border-l-red-700',
    chip: 'bg-red-50 text-red-800',
  },
  unsure: {
    pressed: 'border-amber-600 bg-amber-50 text-amber-800',
    edge: 'border-l-amber-600',
    chip: 'bg-amber-50 text-amber-800',
  },
};

function month(day: string | null): string {
  return day ? day.slice(0, 7) : '—';
}

export function factsLine(row: CardRow): string {
  const t = row.card.team;
  const facts = [t.age || '?', GENDER[t.gender ?? ''] || t.gender || '?', t.state || 'no state', t.club || 'no club'];
  let line = `${[...facts, t.provider || '?'].join(' · ')} · ${t.games} game${t.games === 1 ? '' : 's'}`;
  if (t.games) line += ` · ${month(t.first)} to ${month(t.last)}`;
  if (t.excluded) line += ` · ${t.excluded} excluded`;
  return line;
}

export function CleanupCardView({
  row,
  choice,
  editable,
  bulkBusy,
  alikeUndecided,
  onDecide,
  onDecideAlike,
  onNote,
}: {
  row: CardRow;
  choice: Choice;
  editable: boolean;
  bulkBusy: boolean;
  /** Undecided cards in this card's look-alike set, itself included; the row shows from two. */
  alikeUndecided: number;
  onDecide: (decision: CleanupDecision | null) => void;
  onDecideAlike: (decision: CleanupDecision) => void;
  onNote: (note: string) => void;
}) {
  const { card } = row;
  // The note being typed; outside editing the box shows the saved note.
  const [draft, setDraft] = useState<string | null>(null);

  return (
    <article
      data-testid="cleanup-card"
      data-decision={choice.decision ?? ''}
      className={cn(
        'grid gap-2.5 rounded-lg border border-l-4 bg-card p-3.5',
        choice.decision ? DECISION_TONE[choice.decision].edge : 'border-l-border'
      )}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-display text-sm text-muted-foreground">#{card.n}</span>
        <span className="font-bold break-words">{card.team.name || '(no name)'}</span>
        {card.interest && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-bold tracking-wide text-amber-800 uppercase">
            Followed
          </span>
        )}
      </div>
      {card.team.original && card.team.original !== card.team.name && (
        <div className="text-xs break-words text-muted-foreground">Registered as: {card.team.original}</div>
      )}
      <div className="text-xs break-words text-muted-foreground tabular-nums">{factsLine(row)}</div>
      <div className="rounded-md bg-muted p-2.5 break-words">
        <span className="block text-[11px] tracking-wide text-muted-foreground uppercase">
          {fieldLabel(card.change.field)}
        </span>
        <span className="text-muted-foreground line-through">{changeValue(card.change.old)}</span>
        {' → '}
        <span className="font-bold">{changeValue(card.change.new)}</span>
      </div>
      {card.why && (
        <p className="m-0 border-l-[3px] border-border pl-2.5 text-sm">
          <b>Why: </b>
          {card.why}
        </p>
      )}
      {card.sure && <p className="m-0 text-sm text-muted-foreground">The evidence already settles it: {card.sure}</p>}
      <div className="flex flex-wrap gap-2">
        {CLEANUP_DECISIONS.map((decision) => (
          <button
            key={decision}
            type="button"
            aria-pressed={choice.decision === decision}
            disabled={!editable}
            onClick={() => onDecide(choice.decision === decision ? null : decision)}
            className={cn(
              'min-h-10 rounded-md border px-3 text-sm font-medium disabled:opacity-50',
              choice.decision === decision ? DECISION_TONE[decision].pressed : 'bg-background'
            )}
          >
            {DECISION_LABELS[decision]}
          </button>
        ))}
      </div>
      {alikeUndecided >= 2 && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid="cleanup-alike">
          <span>All {alikeUndecided} undecided like this (same club, same change):</span>
          {CLEANUP_DECISIONS.map((decision) => (
            <button
              key={decision}
              type="button"
              disabled={!editable || bulkBusy}
              onClick={() => onDecideAlike(decision)}
              className="min-h-10 rounded-md border border-dashed bg-background px-3 text-sm font-medium text-foreground disabled:opacity-50"
            >
              {DECISION_LABELS[decision]}
            </button>
          ))}
        </div>
      )}
      <textarea
        aria-label="Note"
        placeholder="Note (optional)"
        value={draft ?? choice.note}
        disabled={!editable}
        rows={1}
        onFocus={() => setDraft(choice.note)}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          if (draft !== null && draft.trim() !== choice.note.trim()) onNote(draft);
          setDraft(null);
        }}
        className="min-h-10 w-full resize-y rounded-md border bg-background px-2 py-1.5 text-base disabled:opacity-50"
      />
    </article>
  );
}
