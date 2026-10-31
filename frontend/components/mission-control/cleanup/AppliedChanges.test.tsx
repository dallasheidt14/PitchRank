import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { AppliedRun } from '@/lib/mission-control/cleanup';
import { AppliedChanges } from './AppliedChanges';

const RUN = '2026-10-28-all';

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let served: { runs: AppliedRun[] };
const posts: Array<Record<string, unknown>> = [];

beforeEach(() => {
  served = {
    runs: [
      {
        runId: RUN,
        open: false,
        changes: [
          { cardId: 'c1', stage: 'states', lane: 'auto', text: 'Phoenix One: State UT → AZ', undo: null },
          { cardId: 'c2', stage: 'merges', lane: 'auto', text: 'Storm B13 merged into Storm 2013 Boys', undo: null },
          {
            cardId: 'c3',
            stage: 'clubs',
            lane: 'owner',
            text: 'Storm Girls: Club X → Y',
            undo: { status: 'pending', requestedLabel: 'Sun, Nov 1, 9:00 AM', handledLabel: null, result: null },
          },
        ],
      },
    ],
  };
  posts.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (!init || init.method !== 'POST') return Response.json(served);
      posts.push(JSON.parse(String(init.body)));
      return Response.json({ requested: true });
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
  await act(async () => root!.render(<AppliedChanges />));
  await settle();
}

async function search(text: string) {
  const input = container!.querySelector<HTMLInputElement>('input[type="search"]')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setter.call(input, text);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function matches() {
  return [...container!.querySelectorAll<HTMLElement>('[data-testid="applied-change"]')];
}

function button(scope: ParentNode, label: string) {
  return [...scope.querySelectorAll('button')].find((b) => b.textContent === label)!;
}

describe('AppliedChanges', () => {
  it('lists nothing until a team is searched for, then the changes naming it', async () => {
    await render();

    expect(container!.querySelector('h3')!.textContent).toBe(`Last run (${RUN}): 3 changes applied`);
    expect(matches()).toHaveLength(0);

    await search('storm');

    expect(matches().map((li) => li.textContent)).toEqual([
      expect.stringContaining('Storm B13 merged into Storm 2013 Boys'),
      expect.stringContaining('Storm Girls: Club X → Y'),
    ]);
    expect(button(matches()[1], 'Undo').disabled).toBe(true);
    expect(matches()[1].textContent).toContain('Undo asked Sun, Nov 1, 9:00 AM');
  });

  it('asks to undo a merge and keep the two separate, unless told otherwise', async () => {
    await render();
    await search('storm b13');

    await act(async () => button(matches()[0], 'Undo').click());
    expect(document.body.textContent).toContain('Keep these two teams separate from now on');
    await act(async () => button(document.querySelector('[role="dialog"]')!, 'Undo').click());
    await settle();

    expect(posts).toEqual([{ runId: RUN, cardId: 'c2', decline: true }]);

    await search('phoenix');
    await act(async () => button(matches()[0], 'Undo').click());
    const box = document.body.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    expect(box.parentElement!.textContent).toContain("Don't propose this change again");
    await act(async () => box.click());
    await act(async () => button(document.querySelector('[role="dialog"]')!, 'Undo').click());
    await settle();

    expect(posts[1]).toEqual({ runId: RUN, cardId: 'c1', decline: false });
  });
});
