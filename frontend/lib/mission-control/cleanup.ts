/**
 * The weekly team cleanup's review page: the cards `scripts/team_cleanup/pages.py --publish --execute` writes
 * to team_cleanup_cards, and the choices the owner saves on them.
 */

export const CLEANUP_STAGES = ['clubs', 'states', 'ages'] as const;
export type CleanupStage = (typeof CLEANUP_STAGES)[number];

export const CLEANUP_DECISIONS = ['apply', 'dont_apply', 'unsure'] as const;
export type CleanupDecision = (typeof CLEANUP_DECISIONS)[number];

export const DECISION_LABELS: Record<CleanupDecision, string> = {
  apply: 'Apply',
  dont_apply: "Don't apply",
  unsure: 'Not sure',
};

/** As pages.py titles each stage's page. */
export const STAGE_LABELS: Record<CleanupStage, string> = {
  clubs: 'Club names',
  states: 'States',
  ages: 'Age groups',
};

const FIELD_LABELS: Record<string, string> = { club_name: 'Club', state_code: 'State', age_group: 'Age group' };

/** team_cleanup_cards' CHECK on note. */
export const MAX_NOTE_LENGTH = 2000;
/** The most cards one write may name: the ids go into the request's URL, which the repo keeps to 100 ids. */
export const MAX_CARDS_PER_WRITE = 100;
const MAX_ID_LENGTH = 200;

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

export function changeValue(value: string | null): string {
  return value == null || value === '' ? '(none)' : value;
}

/** What the states skill reads beside a state card's proposal: shown to the owner, never used to decide it. */
export interface StateCardEvidence {
  /** Distinct opponents per stored state; those with no state count only in opponents_total. */
  opponents: Record<string, number>;
  opponents_total: number;
  /** The team's club-mates per stored state, the team itself left out. */
  club: Record<string, number>;
  gotsport: string | null;
  name: { state: string | null; how: string };
}

const NAME_SOURCE: Record<string, string> = {
  team: 'the team name',
  club: 'the club name',
  town: 'a town in the name',
};

function byCount(perState: Record<string, number>): string {
  return Object.entries(perState)
    .sort(([a, x], [b, y]) => y - x || a.localeCompare(b))
    .map(([state, n]) => `${state} ${n}`)
    .join(' · ');
}

/** A state card's evidence as plain lines, most common state first (the stored card is JSONB, whose keys
 * carry no order). */
export function evidenceLines(evidence: StateCardEvidence | undefined): string[] {
  if (!evidence) return [];
  const lines: string[] = [];
  if (evidence.opponents_total) {
    const placed = Object.keys(evidence.opponents).length ? byCount(evidence.opponents) : 'none with a state';
    lines.push(`Opponents: ${placed} (of ${evidence.opponents_total} teams played)`);
  }
  if (Object.keys(evidence.club).length) lines.push(`Club-mates: ${byCount(evidence.club)}`);
  if (evidence.gotsport) lines.push(`GotSport says: ${evidence.gotsport}`);
  if (evidence.name.state) {
    lines.push(`Name points to ${evidence.name.state} (${NAME_SOURCE[evidence.name.how] ?? 'the name'})`);
  } else if (evidence.name.how === 'conflict') {
    lines.push('Name points two ways');
  } else if (evidence.name.how === 'unplaced') {
    lines.push("Name mentions a state it can't be placed by");
  }
  return lines;
}

export interface CleanupCard {
  id: string;
  n: number;
  group: string;
  whole: boolean;
  alike: string | null;
  interest: boolean;
  sure: string | null;
  change: { field: string; old: string | null; new: string | null };
  why: string;
  team: {
    name: string | null;
    original: string | null;
    club: string | null;
    state: string | null;
    age: string | null;
    gender: string | null;
    provider: string | null;
    games: number;
    excluded: number;
    first: string | null;
    last: string | null;
  };
  /** On state cards of a page that changes a state. */
  evidence?: StateCardEvidence;
}

export interface CardRow {
  card_id: string;
  stage: CleanupStage;
  lane: 'owner' | 'auto';
  page_run: string;
  position: number;
  card: CleanupCard;
  decision: CleanupDecision | null;
  note: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface StageReview {
  stage: CleanupStage;
  pageRun: string;
  cards: CardRow[];
  auto: CardRow[];
}

export interface CleanupRun {
  runId: string;
  states: string[];
  status: string;
  ownerDoneAt: string | null;
  ownerDoneBy: string | null;
  /** ownerDoneAt in the business timezone, which only the server knows. */
  ownerDoneLabel: string | null;
}

export interface CleanupReview {
  run: CleanupRun | null;
  stages: StageReview[];
}

export interface Choice {
  decision: CleanupDecision | null;
  note: string;
}

export function isDecision(value: unknown): value is CleanupDecision {
  return (CLEANUP_DECISIONS as readonly unknown[]).includes(value);
}

export function isStage(value: unknown): value is CleanupStage {
  return (CLEANUP_STAGES as readonly unknown[]).includes(value);
}

export function isId(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= MAX_ID_LENGTH;
}

/**
 * The build of a page saved to the table last. A page run is stamped when its build starts reading, so two
 * overlapping builds can publish in the other order, and two in one second sort by their random suffix:
 * only created_at orders them.
 */
export function newestBuild(rows: ReadonlyArray<Pick<CardRow, 'page_run' | 'created_at'>>): string | null {
  let newest: { pageRun: string; at: number } | null = null;
  for (const row of rows) {
    const at = Date.parse(row.created_at);
    if (!newest || at > newest.at) newest = { pageRun: row.page_run, at };
  }
  return newest?.pageRun ?? null;
}

/** Each stage's newest build, its owner cards and automatic changes in page order, stages in run order. */
export function stageReviews(rows: readonly CardRow[]): StageReview[] {
  return CLEANUP_STAGES.flatMap((stage) => {
    const ofStage = rows.filter((row) => row.stage === stage);
    const pageRun = newestBuild(ofStage);
    if (!pageRun) return [];
    const build = ofStage.filter((row) => row.page_run === pageRun).sort((a, b) => a.position - b.position);
    return [
      {
        stage,
        pageRun,
        cards: build.filter((row) => row.lane === 'owner'),
        auto: build.filter((row) => row.lane === 'auto'),
      },
    ];
  });
}

export interface CardGroup {
  group: string;
  whole: boolean;
  cards: CardRow[];
}

/** The page's groups in the order their first card appears. */
export function groupCards(cards: readonly CardRow[]): CardGroup[] {
  const groups = new Map<string, CardGroup>();
  for (const row of cards) {
    const { group, whole } = row.card;
    if (!groups.has(group)) groups.set(group, { group, whole, cards: [] });
    groups.get(group)!.cards.push(row);
  }
  return [...groups.values()];
}

/** Cards in one group from one club proposing the same change, by the key they share. */
export function alikeSets(cards: readonly CardRow[]): Map<string, string[]> {
  const sets = new Map<string, string[]>();
  for (const row of cards) {
    const key = row.card.alike;
    if (!key) continue;
    if (!sets.has(key)) sets.set(key, []);
    sets.get(key)!.push(row.card_id);
  }
  return sets;
}

export function tally(cards: readonly CardRow[], choices: Readonly<Record<string, Choice>>) {
  const counts = { apply: 0, dont_apply: 0, unsure: 0, undecided: 0 };
  for (const row of cards) {
    const decision = choices[row.card_id]?.decision;
    if (decision) counts[decision] += 1;
    else counts.undecided += 1;
  }
  return counts;
}
