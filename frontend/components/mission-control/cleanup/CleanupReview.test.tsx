import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { makeCleanupCardRow, makePairCardRow } from '@/test/fixtures';
import type { CardRow, Choice, CleanupReview as Review, PairCard } from '@/lib/mission-control/cleanup';
import { CleanupReview } from './CleanupReview';

const RUN = '2026-10-21-all';
const PAGE = '20261021T180000Z-a1b2c3';
const DECISIONS = '/api/mission-control/cleanup/decisions';
const DONE = '/api/mission-control/cleanup/done';
const UNDO = '/api/mission-control/cleanup/undo';

function team(name: string) {
  return { ...makeCleanupCardRow().card.team, name };
}

function review(run: Partial<NonNullable<Review['run']>> = {}, cards?: CardRow[]): Review {
  const alike = { group: 'B', whole: false, alike: 'k1' };
  const whole = { group: 'A', whole: true, alike: null };
  return {
    run: {
      runId: RUN,
      states: ['ALL'],
      status: 'reviewing',
      ownerDoneAt: null,
      ownerDoneBy: null,
      ownerDoneLabel: null,
      ...run,
    },
    stages: [
      {
        stage: 'states',
        pageRun: PAGE,
        cards: cards ?? [
          makeCleanupCardRow({ card_id: 'c1', position: 1, card: { ...alike, team: team('One') } }),
          makeCleanupCardRow({ card_id: 'c2', position: 2, card: { ...alike, team: team('Two') } }),
          makeCleanupCardRow({
            card_id: 'c3',
            position: 3,
            decision: 'dont_apply',
            decided_at: '2026-10-21T19:00:00+00:00',
            card: { ...alike, team: team('Three') },
          }),
          makeCleanupCardRow({ card_id: 'c4', position: 4, card: { ...whole, team: team('Four') } }),
          makeCleanupCardRow({
            card_id: 'c5',
            position: 5,
            decision: 'unsure',
            decided_at: '2026-10-21T19:00:00+00:00',
            card: { ...whole, team: team('Five') },
          }),
        ],
        auto: [
          makeCleanupCardRow({
            card_id: 'a1',
            lane: 'auto',
            decision: 'apply',
            card: { sure: 'a blank state filled from its club, which nothing disputes', team: team('Auto') },
          }),
        ],
      },
    ],
    undo: [],
    previous: null,
  };
}

const MERGES_PAGE = '20261021T200000Z-d4e5f6';
const KEEP = 'Phoenix Rising 2013 Boys';
const MERGE = 'Phoenix Rising B13 Premier';

/** A run whose only page is the duplicate teams: one pair for the owner, one merged automatically. */
function pairs({
  card,
  swap = false,
  run,
}: { card?: Partial<PairCard>; swap?: boolean; run?: Partial<NonNullable<Review['run']>> } = {}): Review {
  return {
    ...review(run),
    stages: [
      {
        stage: 'merges',
        pageRun: MERGES_PAGE,
        cards: [makePairCardRow({ card_id: 'p1', page_run: MERGES_PAGE, swap, card })],
        auto: [
          makePairCardRow({
            card_id: 'pa',
            lane: 'auto',
            decision: 'apply',
            page_run: MERGES_PAGE,
            card: { sure: 'one row holds no games and its alias already points at the other' },
          }),
        ],
      },
    ],
  };
}

type Post = { url: string; body: Record<string, unknown> };
type Held = Post & { release: (status?: number) => void };

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let served: Review;
// What the database holds, which a save from the page may find already decided elsewhere.
let stored: Record<string, Choice>;
let refusal: { status: number; error: string } | null;
let holding: boolean;
let gets: number;
const posts: Post[] = [];
const held: Held[] = [];

function serve(next: Review) {
  served = next;
  stored = {};
  for (const row of next.stages.flatMap((s) => s.cards)) {
    stored[row.card_id] = { decision: row.decision, note: row.note ?? '', swap: row.swap };
  }
}

/** The decisions route as the table answers it: a note trimmed, and only the cards it changed come back. */
function answer({ url, body }: Post): Response {
  if (url === DONE) return Response.json({ ownerDoneAt: '2026-10-22T01:00:00+00:00', ownerDoneBy: 'owner' });
  if (url === UNDO) {
    served = {
      ...served,
      undo: [
        {
          stage: body.stage as 'states',
          lane: body.lane as 'auto',
          status: 'pending',
          requestedLabel: 'Thu, Oct 22, 12:00 PM',
          handledLabel: null,
          result: null,
        },
      ],
    };
    return Response.json({ requested: true });
  }
  const updated = (body.cardIds as string[])
    .filter((id) => !(body.onlyUndecided && stored[id].decision))
    .map((id) => {
      stored[id] = {
        decision: 'decision' in body ? (body.decision as Choice['decision']) : stored[id].decision,
        note: 'note' in body ? ((body.note as string | null) ?? '').trim() : stored[id].note,
        swap: 'swap' in body ? (body.swap as boolean) : stored[id].swap,
      };
      return { card_id: id, decision: stored[id].decision, note: stored[id].note || null, swap: stored[id].swap };
    });
  return Response.json({ updated });
}

beforeEach(() => {
  serve(review());
  refusal = null;
  holding = false;
  gets = 0;
  posts.length = 0;
  held.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (!init || init.method !== 'POST') {
        gets += 1;
        return Response.json(served);
      }
      const post = { url, body: JSON.parse(String(init.body)) };
      posts.push(post);
      if (refusal) return Response.json({ error: refusal.error }, { status: refusal.status });
      if (holding && url === DECISIONS) {
        return new Promise<Response>((resolve) =>
          held.push({
            ...post,
            release: (status = 200) =>
              resolve(
                status === 200 ? answer(post) : Response.json({ error: 'Could not save the choice' }, { status })
              ),
          })
        );
      }
      return answer(post);
    })
  );
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function render() {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(CleanupReview)));
  await settle();
}

function card(name: string): HTMLElement {
  return [...container!.querySelectorAll<HTMLElement>('[data-testid="cleanup-card"]')].find((el) =>
    el.textContent!.includes(name)
  )!;
}

function button(scope: ParentNode, text: string): HTMLButtonElement {
  return [...scope.querySelectorAll<HTMLButtonElement>('button')].find((b) => b.textContent === text)!;
}

async function click(target: HTMLElement) {
  await act(async () => target.click());
  await settle();
}

async function release(status?: number) {
  await act(async () => held.shift()!.release(status));
  await settle();
}

async function typeNote(name: string, text: string) {
  const box = card(name).querySelector('textarea')!;
  await act(async () => box.focus());
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(box, text);
    box.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => box.blur());
  await settle();
}

async function confirmDone() {
  await click(button(container!, 'Mark review done'));
  await click(button(document.body, 'Mark done'));
}

describe('the team cleanup review page', () => {
  it("shows the page's cards, what is left to decide and the automatic changes", async () => {
    await render();

    expect(container!.querySelectorAll('[data-testid="cleanup-card"]')).toHaveLength(5);
    expect(container!.querySelector('[data-testid="cleanup-tally"]')!.textContent).toContain('3 left');
    expect(container!.querySelector('[data-testid="cleanup-auto"]')!.textContent).toContain(
      '1 change the evidence settles, applied without a card'
    );
  });

  it('saves a decision for one card and shows it chosen', async () => {
    await render();

    await click(button(card('One'), 'Apply'));

    expect(posts).toEqual([
      { url: DECISIONS, body: { runId: RUN, stage: 'states', pageRun: PAGE, cardIds: ['c1'], decision: 'apply' } },
    ]);
    expect(button(card('One'), 'Apply').getAttribute('aria-pressed')).toBe('true');
  });

  it('puts the choice back and says so when the save is refused', async () => {
    refusal = { status: 500, error: 'Could not save the choice' };
    await render();

    await click(button(card('One'), 'Apply'));

    expect(button(card('One'), 'Apply').getAttribute('aria-pressed')).toBe('false');
    expect(container!.textContent).toContain('Not saved: Could not save the choice.');
  });

  it('shows what the database holds when two queued saves of a card both fail', async () => {
    holding = true;
    await render();

    await click(button(card('One'), 'Apply'));
    await click(button(card('One'), "Don't apply"));
    await release(500);
    await release(500);

    expect(card('One').dataset.decision).toBe('');
  });

  it('decides the undecided look-alikes in one save, leaving the decided one as it is', async () => {
    await render();
    const row = card('One').querySelector<HTMLElement>('[data-testid="cleanup-alike"]')!;
    expect(row.textContent).toContain('All 2 undecided like this');

    await click(button(row, "Don't apply"));

    expect(posts.map((p) => p.body)).toEqual([
      {
        runId: RUN,
        stage: 'states',
        pageRun: PAGE,
        cardIds: ['c1', 'c2'],
        decision: 'dont_apply',
        onlyUndecided: true,
      },
    ]);
    expect(card('Three').dataset.decision).toBe('dont_apply');
  });

  it('shows the last loaded choice on a look-alike the save left alone, decided meanwhile elsewhere', async () => {
    await render();
    stored.c2 = { decision: 'apply', note: '', swap: false };

    await click(button(card('One').querySelector<HTMLElement>('[data-testid="cleanup-alike"]')!, "Don't apply"));

    expect(card('One').dataset.decision).toBe('dont_apply');
    expect(card('Two').dataset.decision).toBe('');
  });

  it("applies a trusted tier's undecided cards in one save", async () => {
    await render();

    await click(button(container!, 'Apply every undecided card here'));

    expect(posts.map((p) => p.body)).toEqual([
      { runId: RUN, stage: 'states', pageRun: PAGE, cardIds: ['c4'], decision: 'apply', onlyUndecided: true },
    ]);
    expect(card('Five').dataset.decision).toBe('unsure');
  });

  it('saves a note on its own, keeping the decision', async () => {
    await render();

    await typeNote('Three', '  played in UT all fall ');

    expect(posts.map((p) => p.body)).toEqual([
      { runId: RUN, stage: 'states', pageRun: PAGE, cardIds: ['c3'], note: '  played in UT all fall ' },
    ]);
    expect(card('Three').querySelector('textarea')!.value).toBe('played in UT all fall');
    expect(card('Three').dataset.decision).toBe('dont_apply');
  });

  it('reloads the page when a save finds it built again', async () => {
    refusal = { status: 409, error: 'This page was built again since it loaded' };
    await render();

    await click(button(card('One'), 'Apply'));

    expect(gets).toBe(2);
    expect(container!.textContent).toContain(
      'Not saved: This page was built again since it loaded. The page has been reloaded.'
    );
  });

  it('locks every choice once the review is marked done', async () => {
    serve(
      review({
        ownerDoneAt: '2026-10-26T01:00:00+00:00',
        ownerDoneBy: 'deadline',
        ownerDoneLabel: 'Sun, Oct 25, 6:00 PM',
      })
    );
    await render();

    expect(container!.querySelector('[data-testid="cleanup-locked"]')!.textContent).toBe(
      'Marked done Sun, Oct 25, 6:00 PM at the deadline. Your choices are locked.'
    );
    expect([...card('One').querySelectorAll('button')].every((b) => b.disabled)).toBe(true);
    expect(button(container!, 'Mark review done')).toBeUndefined();
  });

  it.each([
    ['applying', 'This run is past review, so its choices are locked.'],
    ['proposing', 'This run is still proposing changes, so its review has not started.'],
  ])('locks every choice while the run is %s', async (status, says) => {
    serve(review({ status }));
    await render();

    expect(container!.querySelector('[data-testid="cleanup-locked"]')!.textContent).toBe(says);
    expect([...card('One').querySelectorAll('button')].every((b) => b.disabled)).toBe(true);
    expect(button(container!, 'Mark review done')).toBeUndefined();
  });

  it("shows a state card's evidence, and none on a card without it", async () => {
    const evidence = {
      opponents: { NV: 2, UT: 18 },
      opponents_total: 21,
      club: { CA: 14 },
      gotsport: 'UT',
      name: { state: null, how: 'none' },
    };
    serve(
      review({}, [
        makeCleanupCardRow({ card_id: 'c1', position: 1, card: { team: team('Utah side'), evidence } }),
        makeCleanupCardRow({ card_id: 'c2', position: 2, card: { team: team('Plain') } }),
      ])
    );
    await render();

    const lines = [...card('Utah side').querySelectorAll('[data-testid="cleanup-evidence"] li')].map(
      (li) => li.textContent
    );
    expect(lines).toEqual(['Opponents: UT 18 · NV 2 (of 21 teams played)', 'Club-mates: CA 14', 'GotSport says: UT']);
    expect(card('Plain').querySelector('[data-testid="cleanup-evidence"]')).toBeNull();
  });

  it('shows a pair with its kept team first, and the other first once the owner keeps it instead', async () => {
    serve(pairs());
    await render();
    const sides = () =>
      [...card(KEEP).querySelectorAll<HTMLElement>('[data-testid="cleanup-pair-side"]')].map((el) => [
        el.dataset.kept,
        el.textContent!.includes(KEEP) ? KEEP : MERGE,
      ]);
    expect(sides()).toEqual([
      ['true', KEEP],
      ['false', MERGE],
    ]);

    await click(button(card(KEEP), 'Keep the other one'));

    expect(posts).toEqual([
      { url: DECISIONS, body: { runId: RUN, stage: 'merges', pageRun: MERGES_PAGE, cardIds: ['p1'], swap: true } },
    ]);
    expect(sides()).toEqual([
      ['true', MERGE],
      ['false', KEEP],
    ]);
    expect(button(card(KEEP), 'Keep the other one').getAttribute('aria-pressed')).toBe('true');
  });

  it('shows a pair saved as swapped with the other team kept, and swaps it back', async () => {
    serve(pairs({ swap: true }));
    await render();
    const keptFirst = () =>
      card(KEEP).querySelector<HTMLElement>('[data-testid="cleanup-pair-side"]')!.textContent!.includes(KEEP)
        ? KEEP
        : MERGE;
    expect(keptFirst()).toBe(MERGE);
    expect(button(card(KEEP), 'Keep the other one').getAttribute('aria-pressed')).toBe('true');

    await click(button(card(KEEP), 'Keep the other one'));

    expect(posts.map((p) => p.body.swap)).toEqual([false]);
    expect(keptFirst()).toBe(KEEP);
  });

  it('shows a swap at once, before its save lands', async () => {
    serve(pairs());
    holding = true;
    await render();

    await click(button(card(KEEP), 'Keep the other one'));

    expect(button(card(KEEP), 'Keep the other one').getAttribute('aria-pressed')).toBe('true');
    await release();
  });

  it('saves a note typed on a pair card', async () => {
    serve(pairs());
    await render();

    await typeNote(KEEP, 'same coach, renamed for the fall');

    expect(posts.map((p) => p.body)).toEqual([
      { runId: RUN, stage: 'merges', pageRun: MERGES_PAGE, cardIds: ['p1'], note: 'same coach, renamed for the fall' },
    ]);
  });

  it("locks a pair's choices, swap included, once the review is marked done", async () => {
    serve(pairs({ run: { ownerDoneAt: '2026-10-26T01:00:00+00:00', ownerDoneBy: 'owner', ownerDoneLabel: 'x' } }));
    await render();

    expect([...card(KEEP).querySelectorAll('button')].every((b) => b.disabled)).toBe(true);
  });

  it("saves a pair's Merge them and Keep separate as the decisions the loop reads", async () => {
    serve(pairs());
    await render();

    await click(button(card(KEEP), 'Merge them'));
    await click(button(card(KEEP), 'Keep separate'));

    expect(posts.map((p) => p.body.decision)).toEqual(['apply', 'dont_apply']);
    expect(card(KEEP).dataset.decision).toBe('dont_apply');
  });

  it("counts a pair's decisions in the words its buttons use", async () => {
    serve(pairs());
    await render();

    expect(container!.querySelector('[data-testid="cleanup-tally"]')!.textContent).toBe(
      '0 merge0 keep separate0 unsure1 left'
    );
  });

  it("shows a pair's evidence", async () => {
    serve(pairs());
    await render();

    const lines = [...card(KEEP).querySelectorAll('[data-testid="cleanup-evidence"] li')].map((li) => li.textContent);
    expect(lines).toEqual([
      'Found as the same squad registered with two providers',
      'Shared opponents: 2 (SC del Sol 2013, Arizona Arsenal 2013)',
      'Opponent overlap: 25%',
    ]);
  });

  it('never offers to merge a whole group at once', async () => {
    serve(pairs({ card: { whole: true } }));
    await render();

    expect(button(container!, 'Apply every undecided card here')).toBeUndefined();
  });

  it('lists an automatic merge on one line, the team merged away first', async () => {
    serve(pairs());
    await render();

    expect(container!.querySelector('[data-testid="cleanup-auto"] li')!.textContent).toBe(
      `${MERGE} → kept as ${KEEP} (one row holds no games and its alias already points at the other)`
    );
  });

  it('lists an automatic merge the review turned round with the row it keeps last', async () => {
    const swapped = pairs();
    const [stage] = swapped.stages;
    stage.auto = stage.auto.map((row) => ({
      ...row,
      swap: true,
      card: { ...row.card, sure: 'reviewers cleared it: one squad registered twice' },
    })) as typeof stage.auto;
    serve(swapped);
    await render();

    expect(container!.querySelector('[data-testid="cleanup-auto"] li')!.textContent).toBe(
      `${KEEP} → kept as ${MERGE} (reviewers cleared it: one squad registered twice)`
    );
  });

  it('lists a pair the reviewers found to be two teams as kept separate', async () => {
    const separate = pairs();
    const [stage] = separate.stages;
    stage.auto = stage.auto.map((row) => ({
      ...row,
      card: { ...row.card, keep_separate: true, sure: 'reviewers found two teams: 2008 and 2009' },
    })) as typeof stage.auto;
    serve(separate);
    await render();

    expect(container!.querySelector('[data-testid="cleanup-auto"] li')!.textContent).toBe(
      `${MERGE} and ${KEEP} kept separate (reviewers found two teams: 2008 and 2009)`
    );
  });

  it('lists a club guess the reviewers turned down as kept, not changed', async () => {
    const kept = review();
    const [stage] = kept.stages;
    stage.auto = [
      makeCleanupCardRow({
        card_id: 'a1',
        lane: 'auto',
        decision: 'apply',
        card: {
          team: team('Concorde Fire 2013B'),
          change: { field: 'club_name', old: 'Concorde Fire', new: 'CF' },
          keep_as_is: true,
          sure: 'reviewers found the stored club right: CF is a squad label',
        },
      }),
    ];
    serve(kept);
    await render();

    expect(container!.querySelector('[data-testid="cleanup-auto"] li')!.textContent).toBe(
      'Concorde Fire 2013B: Club kept as Concorde Fire, not CF (reviewers found the stored club right: CF is a squad label)'
    );
  });

  it("asks for a lane's undo once confirmed, then shows it waiting and offers it no more", async () => {
    await render();
    const undo = container!.querySelector<HTMLElement>('[data-testid="cleanup-undo"]')!;

    await click(button(undo, 'Undo automatic changes'));
    await click(button(document.body, 'Undo'));

    expect(posts).toEqual([{ url: UNDO, body: { runId: RUN, stage: 'states', lane: 'auto' } }]);
    const shown = container!.querySelector<HTMLElement>('[data-testid="cleanup-undo"]')!;
    expect(shown.textContent).toContain(
      'Undoing automatic changes: asked Thu, Oct 22, 12:00 PM, waiting for the next hourly run.'
    );
    expect(button(shown, 'Undo automatic changes').disabled).toBe(true);
    expect(button(shown, 'Undo my changes').disabled).toBe(false);
  });

  it('asks for nothing when the undo is not confirmed', async () => {
    await render();

    await click(button(container!.querySelector('[data-testid="cleanup-undo"]')!, 'Undo my changes'));
    await click(button(document.body, 'Keep them'));

    expect(posts).toEqual([]);
  });

  it("offers the last finished run's undo for each stage it published, with no run open too", async () => {
    serve({
      ...review(),
      run: null,
      stages: [],
      previous: { runId: '2026-10-14-all', stages: ['clubs', 'states', 'ages'], undo: [] },
    });
    await render();

    const panel = container!.querySelector<HTMLElement>('[data-testid="cleanup-previous"]')!;
    const stages = panel.querySelectorAll<HTMLElement>('[data-testid="cleanup-previous-stage"]');
    expect(container!.textContent).toContain('No cleanup run is open right now.');
    expect([...stages].map((el) => el.textContent!.split('Undo')[0])).toEqual(['Club names', 'States', 'Age groups']);
    await click(button(stages[1], 'Undo my changes'));
    await click(button(document.body, 'Undo'));

    expect(posts).toEqual([{ url: UNDO, body: { runId: '2026-10-14-all', stage: 'states', lane: 'owner' } }]);
  });

  it('offers no undo once the run is past review', async () => {
    serve(review({ status: 'applying' }));
    await render();

    expect(container!.querySelector('[data-testid="cleanup-undo"]')).toBeNull();
  });

  it('offers no Done before any stage page is published', async () => {
    serve({ ...review(), stages: [] });
    await render();

    expect(container!.textContent).toContain('No review page is published for this run yet.');
    expect(button(container!, 'Mark review done')).toBeUndefined();
  });

  it('marks the review done once confirmed, and reloads it', async () => {
    await render();

    serve(
      review({ ownerDoneAt: '2026-10-22T01:00:00+00:00', ownerDoneBy: 'owner', ownerDoneLabel: 'Tue, Oct 21, 6:00 PM' })
    );
    await confirmDone();

    expect(posts).toEqual([{ url: DONE, body: { runId: RUN } }]);
    expect(container!.querySelector('[data-testid="cleanup-locked"]')).not.toBeNull();
  });

  it('waits for a save in flight, and leaves the review open when that save fails', async () => {
    holding = true;
    await render();

    await click(button(card('One'), 'Apply'));
    await confirmDone();
    expect(posts.map((p) => p.url)).toEqual([DECISIONS]);

    await release(500);

    expect(posts.map((p) => p.url)).toEqual([DECISIONS]);
    expect(container!.textContent).toContain('A choice did not save, so the review is not marked done.');
  });

  it('leaves the review open when a save fails while the confirmation is showing', async () => {
    holding = true;
    await render();

    await click(button(card('One'), 'Apply'));
    await click(button(container!, 'Mark review done'));
    await release(500);
    await click(button(document.body, 'Mark done'));

    expect(posts.map((p) => p.url)).toEqual([DECISIONS]);
    expect(container!.textContent).toContain('A choice did not save, so the review is not marked done.');
  });

  it('marks the review done after an earlier failed save was made again', async () => {
    refusal = { status: 500, error: 'Could not save the choice' };
    await render();
    await click(button(card('One'), 'Apply'));
    refusal = null;
    await click(button(card('One'), 'Apply'));

    await confirmDone();

    expect(posts.map((p) => p.url)).toEqual([DECISIONS, DECISIONS, DONE]);
  });

  it('waits for every part of a group save split across writes before marking done', async () => {
    const group = Array.from({ length: 101 }, (_, n) =>
      makeCleanupCardRow({
        card_id: `g${n}`,
        position: n + 1,
        card: { group: 'A', whole: true, alike: null, team: team(`Group ${n}`) },
      })
    );
    serve(review({}, group));
    holding = true;
    await render();

    await click(button(container!, 'Apply every undecided card here'));
    await confirmDone();
    await release();
    expect(posts.map((p) => p.url)).toEqual([DECISIONS, DECISIONS]);

    await release();

    expect(posts.map((p) => [p.url, (p.body.cardIds as string[] | undefined)?.length])).toEqual([
      [DECISIONS, 100],
      [DECISIONS, 1],
      [DONE, undefined],
    ]);
  });
});
