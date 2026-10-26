'use client';

import { cn } from '@/lib/utils';
import {
  PAIR_DECISION_LABELS,
  pairEvidenceLines,
  survivorFirst,
  type Choice,
  type CleanupDecision,
  type PairCardRow,
  type PairSide,
} from '@/lib/mission-control/cleanup';
import { CardReasons, CardShell, DecisionButtons, NoteBox, TeamLines } from './CleanupCardView';

function SideView({ side, kept }: { side: PairSide; kept: boolean }) {
  return (
    <div
      data-testid="cleanup-pair-side"
      data-kept={kept}
      className={cn(
        'grid content-start gap-1 rounded-md border p-2.5',
        kept ? 'border-primary bg-muted' : 'bg-background'
      )}
    >
      <span className="text-[11px] tracking-wide text-muted-foreground uppercase">
        {kept ? 'Kept' : 'Merged into the kept team'}
      </span>
      <span className="font-bold break-words">{side.name || '(no name)'}</span>
      <TeamLines team={side} />
    </div>
  );
}

export function PairCardView({
  row,
  choice,
  editable,
  onDecide,
  onSwap,
  onNote,
}: {
  row: PairCardRow;
  choice: Choice;
  editable: boolean;
  onDecide: (decision: CleanupDecision | null) => void;
  onSwap: (swap: boolean) => void;
  onNote: (note: string) => void;
}) {
  const { card } = row;
  const [kept, merged] = survivorFirst(card, choice.swap);

  return (
    <CardShell n={card.n} title="Possibly one team" interest={card.interest} decision={choice.decision}>
      <div className="grid gap-2.5 sm:grid-cols-2">
        <SideView side={kept} kept />
        <SideView side={merged} kept={false} />
      </div>
      <CardReasons why={card.why} sure={card.sure} evidence={pairEvidenceLines(card.evidence)} />
      <div className="flex flex-wrap items-center gap-2">
        <DecisionButtons
          decision={choice.decision}
          labels={PAIR_DECISION_LABELS}
          editable={editable}
          onDecide={onDecide}
        />
        <button
          type="button"
          aria-pressed={choice.swap}
          disabled={!editable}
          onClick={() => onSwap(!choice.swap)}
          className={cn(
            'min-h-10 rounded-md border border-dashed px-3 text-sm font-medium disabled:opacity-50',
            choice.swap ? 'border-primary bg-muted' : 'bg-background'
          )}
        >
          Keep the other one
        </button>
      </div>
      <NoteBox note={choice.note} editable={editable} onNote={onNote} />
    </CardShell>
  );
}
