// happy-dom applies no stylesheet, so this reads which copy of Upcoming Games each breakpoint shows from
// the Tailwind classes on its ancestors. Whether the layout looks right is a live check, not this.
import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('@/lib/hooks', () => ({ useTeam: () => ({ data: { state: 'AZ', age: 13, gender: 'F' } }) }));
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock('next/dynamic', () => ({ default: () => () => null }));
vi.mock('@/components/TeamHeader', () => ({ TeamHeader: () => null }));
vi.mock('@/components/GameHistoryTable', () => ({
  GameHistoryTable: () => React.createElement('div', { 'data-testid': 'history' }),
}));
vi.mock('@/components/UpcomingGamesTable', () => ({
  UpcomingGamesTable: () => React.createElement('div', { 'data-testid': 'upcoming' }),
}));
vi.mock('@/components/Breadcrumbs', () => ({ Breadcrumbs: () => null }));

import { TeamPageShell } from '@/components/TeamPageShell';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

/** Whether every ancestor's classes leave `el` displayed below md (`phone`) or at md and up (`md`). */
function shownAt(el: Element, width: 'phone' | 'md'): boolean {
  for (let node: Element | null = el; node && node !== container; node = node.parentElement) {
    const names = (node.getAttribute('class') ?? '').split(/\s+/);
    if (width === 'phone' && names.includes('hidden')) return false;
    if (width === 'md' && names.includes('md:hidden')) return false;
    if (width === 'md' && names.includes('hidden') && !names.some((n) => /^md:(block|flex|grid)$/.test(n))) {
      return false;
    }
  }
  return true;
}

describe('TeamPageShell upcoming games placement', () => {
  it('shows one copy per width: above the game history on phones, after it in the right column from md up', async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root!.render(React.createElement(TeamPageShell, { id: 'team-1' })));

    const history = container.querySelector('[data-testid="history"]')!;
    const copies = Array.from(container.querySelectorAll('[data-testid="upcoming"]'));
    const before = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

    const onPhone = copies.filter((c) => shownAt(c, 'phone'));
    expect(onPhone).toHaveLength(1);
    expect(before(onPhone[0], history)).toBe(true);

    const onMd = copies.filter((c) => shownAt(c, 'md'));
    expect(onMd).toHaveLength(1);
    expect(before(history, onMd[0])).toBe(true);
  });
});
