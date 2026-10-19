import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { makeCleanupCardRow } from '@/test/fixtures';
import type { CardRow, Choice, CleanupReview as Review } from '@/lib/mission-control/cleanup';
import { CleanupReview } from './CleanupReview';

const RUN = '2026-10-21-all';
const PAGE = '20261021T180000Z-a1b2c3';
const DECISIONS = '/api/mission-control/cleanup/decisions';
const DONE = '/api/mission-control/cleanup/done';

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
    stored[row.card_id] = { decision: row.decision, note: row.note ?? '' };
  }
}

/** The decisions route as the table answers it: a note trimmed, and only the cards it changed come back. */
function answer({ url, body }: Post): Response {
  if (url === DONE) return Response.json({ ownerDoneAt: '2026-10-22T01:00:00+00:00', ownerDoneBy: 'owner' });
  const updated = (body.cardIds as string[])
    .filter((id) => !(body.onlyUndecided && stored[id].decision))
    .map((id) => {
      stored[id] = {
        decision: 'decision' in body ? (body.decision as Choice['decision']) : stored[id].decision,
        note: 'note' in body ? ((body.note as string | null) ?? '').trim() : stored[id].note,
      };
      return { card_id: id, decision: stored[id].decision, note: stored[id].note || null };
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
    stored.c2 = { decision: 'apply', note: '' };

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
