import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { makePairCard, makePairSide } from '@/test/fixtures';
import type { SpotCheckReview as Review, SpotVerdict } from '@/lib/mission-control/cleanup';
import { SpotCheckReview } from './SpotCheckReview';

const RUN = '2026-11-04-all';

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let served: Review;
let refusal: number | null;
const posts: Array<Record<string, unknown>> = [];

function check(n: number, verdict: SpotVerdict | null = null, swap = false) {
  return {
    cardId: `c${n}`,
    position: n,
    card: makePairCard({
      id: `c${n}`,
      why: `Reviewers cleared it: reason ${n}`,
      keep: makePairSide({ team_id: `k${n}`, name: `Kept ${n}` }),
      merge: makePairSide({ team_id: `m${n}`, name: `Merged ${n}` }),
    }),
    swap,
    verdict,
    note: null,
  };
}

beforeEach(() => {
  served = { runs: [{ runId: RUN, checks: [check(1, 'right'), check(2, null, true)] }], cleanWeeks: 3 };
  refusal = null;
  posts.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (!init || init.method !== 'POST') return Response.json(served);
      const body = JSON.parse(String(init.body));
      posts.push(body);
      if (refusal) return Response.json({ error: 'Could not record the verdict' }, { status: refusal });
      const found = served.runs[0].checks.find((c) => c.cardId === body.cardId)!;
      found.verdict = body.verdict;
      found.note = body.note || null;
      return Response.json({ verdict: body.verdict, note: found.note });
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
  await act(async () => root!.render(<SpotCheckReview />));
  await settle();
}

function cards() {
  return [...container!.querySelectorAll<HTMLElement>('[data-testid="spot-check"]')];
}

function button(card: HTMLElement, label: string) {
  return [...card.querySelectorAll('button')].find((b) => b.textContent === label)!;
}

describe('SpotCheckReview', () => {
  it('shows each sampled merge kept team first, as it applied, with the reviewers reason and the clean weeks', async () => {
    await render();

    const [first, second] = cards();
    expect(first.querySelector('a')!.textContent).toBe('Kept 1');
    expect(second.querySelector('a')!.getAttribute('href')).toBe('/teams/m2');
    expect(second.textContent).toContain('Reviewers cleared it: reason 2');
    expect(button(first, 'Right').getAttribute('aria-pressed')).toBe('true');
    expect(container!.querySelector('[data-testid="spot-check-weeks"]')!.textContent).toContain(
      'Clean weeks in a row: 3 of 4'
    );
    expect(container!.querySelector('h3')!.textContent).toBe(`Run ${RUN}: 1 of 2 marked`);
  });

  it('records a verdict, and pressing it again takes it back', async () => {
    await render();

    await act(async () => button(cards()[1], 'Wrong').click());
    await settle();

    expect(posts).toEqual([{ runId: RUN, cardId: 'c2', verdict: 'wrong', note: '' }]);
    expect(cards()[1].dataset.verdict).toBe('wrong');

    await act(async () => button(cards()[1], 'Wrong').click());
    await settle();

    expect(posts[1]).toEqual({ runId: RUN, cardId: 'c2', verdict: null, note: '' });
    expect(cards()[1].dataset.verdict).toBe('');
  });

  it('says when a verdict did not save and shows what the database holds', async () => {
    refusal = 500;
    await render();

    await act(async () => button(cards()[1], 'Right').click());
    await settle();

    expect(container!.querySelector('[role="status"]')!.textContent).toBe('Not saved: Could not record the verdict.');
    expect(cards()[1].dataset.verdict).toBe('');
  });
});
