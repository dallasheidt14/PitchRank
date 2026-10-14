import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/rankings/az/u12/male',
}));
vi.mock('@/lib/events', () => ({ trackFilterApplied: vi.fn() }));
vi.mock('@/components/RankingsTable', () => ({ RankingsTable: () => null }));
vi.mock('@/components/RelatedRankings', () => ({ RelatedRankings: () => null }));
vi.mock('@/components/Breadcrumbs', () => ({ Breadcrumbs: () => null }));

import { RankingsPageContent } from '@/components/RankingsPageContent';

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let headerSearch: HTMLInputElement | null = null;
const scrollIntoView = vi.fn();

beforeEach(() => {
  scrollIntoView.mockReset();
  // Stands in for GlobalSearch, which sits earlier in the document and is also a combobox.
  headerSearch = document.createElement('input');
  headerSearch.setAttribute('role', 'combobox');
  document.body.appendChild(headerSearch);
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      disconnect() {}
    }
  );
  Object.defineProperty(Element.prototype, 'scrollIntoView', { value: scrollIntoView, configurable: true });
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  headerSearch?.remove();
  root = null;
  container = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function renderAndTapChange() {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () =>
    root!.render(React.createElement(RankingsPageContent, { region: 'az', ageGroup: 'u12', gender: 'male' }))
  );
  const change = container.querySelector('[aria-label="Change rankings filter"]') as HTMLButtonElement;
  await act(async () => change.click());
}

describe('RankingsPageContent Change bar', () => {
  it('brings the filter card back and hands focus to its Region dropdown, not the header search', async () => {
    await renderAndTapChange();

    const filterCard = container!.querySelector('[data-testid="rankings-filter"]')!;
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(filterCard.parentElement);

    const focused = document.activeElement as HTMLElement;
    expect(focused).not.toBe(headerSearch);
    expect(focused.getAttribute('role')).toBe('combobox');
    expect(filterCard.contains(focused)).toBe(true);
    expect(focused.textContent).toBe('Arizona');
  });

  it('leaves the scroll speed to the page so reduced motion is honoured', async () => {
    await renderAndTapChange();

    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start' });
  });

  it('stops the scroll below the sticky site header', async () => {
    await renderAndTapChange();

    const wrapper = container!.querySelector('[data-testid="rankings-filter"]')!.parentElement!;
    expect(wrapper.className.split(/\s+/)).toContain('scroll-mt-[calc(var(--site-header-height)+0.5rem)]');
  });
});
