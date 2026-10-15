import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => '/rankings/az/u12/male',
}));
vi.mock('@/lib/events', () => ({ trackFilterApplied: vi.fn() }));

import { RankingsFilter } from './RankingsFilter';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe('RankingsFilter labels', () => {
  it('names each dropdown with its visible label', async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root!.render(React.createElement(RankingsFilter)));

    const named = Array.from(container.querySelectorAll('label')).map((label) => {
      const control = document.getElementById(label.htmlFor);
      return [label.textContent!.trim(), control?.getAttribute('role'), control?.textContent];
    });
    expect(named).toEqual([
      ['Region', 'combobox', 'Arizona'],
      ['Age Group', 'combobox', 'U12'],
      ['Gender', 'combobox', 'Boys'],
    ]);
  });
});
