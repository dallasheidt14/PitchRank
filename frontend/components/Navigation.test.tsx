import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => '/',
}));
vi.mock('next/image', () => ({ default: () => null }));
vi.mock('@/hooks/useUser', () => ({ useUser: () => ({ user: null, isLoading: false, signOut: vi.fn() }) }));
vi.mock('./GlobalSearch', () => ({
  GLOBAL_SEARCH_INPUT_IDS: { mobile: 'global-search-mobile', desktop: 'global-search-desktop' },
  GlobalSearch: ({ inputId }: { inputId?: string }) => React.createElement('input', { id: inputId }),
}));
vi.mock('./FeedbackModal', () => ({
  FeedbackModal: ({ open }: { open: boolean }) =>
    open ? React.createElement('div', { 'data-testid': 'feedback-dialog' }) : null,
}));

import { Navigation } from './Navigation';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

async function renderNavigation() {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(Navigation)));
}

describe('Navigation on phones', () => {
  it('gives the header row to the search, and the feedback form a row in the menu that keeps it open', async () => {
    await renderNavigation();

    const phoneRow = container!.querySelector('[data-testid="mobile-menu-toggle"]')!.parentElement!;
    expect(phoneRow.querySelector('#global-search-mobile')).not.toBeNull();
    expect(phoneRow.querySelector('[data-testid^="feedback-trigger"]')).toBeNull();

    await act(async () =>
      (container!.querySelector('[data-testid="mobile-menu-toggle"]') as HTMLButtonElement).click()
    );
    const menuRow = container!.querySelector('[data-testid="feedback-trigger-menu"]') as HTMLButtonElement;
    expect(menuRow.textContent).toBe('Feedback or questions');

    await act(async () => menuRow.click());
    expect(container!.querySelector('[data-testid="feedback-dialog"]')).not.toBeNull();
    expect(container!.querySelector('[data-testid="mobile-menu"]')).not.toBeNull();
  });

  it('keeps the "?" button in the desktop header', async () => {
    await renderNavigation();

    const desktopNav = container!.querySelector('[data-testid="desktop-nav"]')!;
    expect(desktopNav.querySelector('[data-testid="feedback-trigger"]')).not.toBeNull();
    expect(container!.querySelector('#global-search-desktop')).not.toBeNull();
  });

  // FindYourTeamButton picks between these two searches with min-width 64rem, Tailwind's lg.
  it('switches from the phone search to the desktop search at lg', async () => {
    await renderNavigation();

    const classes = (el: Element) => el.className.split(/\s+/);
    expect(classes(document.getElementById('global-search-desktop')!.parentElement!)).toEqual(
      expect.arrayContaining(['hidden', 'lg:flex'])
    );
    expect(classes(container!.querySelector('[data-testid="mobile-menu-toggle"]')!.parentElement!)).toEqual(
      expect.arrayContaining(['flex', 'lg:hidden'])
    );
  });
});
