import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { FindYourTeamButton } from './FindYourTeamButton';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.restoreAllMocks();
});

/** Both header searches are always in the page; CSS shows one per width. */
async function clickAtWidth(desktop: boolean) {
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) => ({ matches: desktop && query === '(min-width: 64rem)' }) as MediaQueryList
  );
  container = document.createElement('div');
  container.innerHTML = '<input id="global-search-mobile" /><input id="global-search-desktop" />';
  document.body.appendChild(container);
  const host = document.createElement('div');
  container.appendChild(host);
  root = createRoot(host);
  await act(async () => root!.render(React.createElement(FindYourTeamButton)));
  await act(async () => (container!.querySelector('[data-testid="cta-find-team"]') as HTMLButtonElement).click());
}

describe('FindYourTeamButton', () => {
  it('puts the cursor in the phone header search below lg', async () => {
    await clickAtWidth(false);

    expect(document.activeElement?.id).toBe('global-search-mobile');
  });

  it('puts the cursor in the desktop header search from lg up', async () => {
    await clickAtWidth(true);

    expect(document.activeElement?.id).toBe('global-search-desktop');
  });
});
