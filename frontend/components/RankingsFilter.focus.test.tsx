// A filter change loads another board and remounts the filter card. Radix Select can't be driven in happy-dom,
// so this file swaps in a plain double whose items call the same onValueChange a real pick would.
import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockPathname, mockReplace } = vi.hoisted(() => ({
  mockPathname: { current: '/rankings/az/u12/male' },
  mockReplace: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
  usePathname: () => mockPathname.current,
}));
vi.mock('@/lib/events', () => ({ trackFilterApplied: vi.fn() }));
vi.mock('@/components/ui/select', async () => {
  const { createContext, createElement, useContext } = await import('react');
  const Pick = createContext<(value: string) => void>(() => {});
  type Props = { children?: React.ReactNode; id?: string; value?: string; onValueChange?: (value: string) => void };
  return {
    Select: ({ onValueChange, children }: Props) => createElement(Pick.Provider, { value: onValueChange! }, children),
    SelectTrigger: ({ id, children }: Props) =>
      createElement('button', { type: 'button', role: 'combobox', id }, children),
    SelectValue: () => null,
    SelectContent: ({ children }: Props) => createElement('div', null, children),
    SelectItem: function SelectItem({ value, children }: Props) {
      const pick = useContext(Pick);
      return createElement('button', { type: 'button', 'data-value': value, onClick: () => pick(value!) }, children);
    },
  };
});

import { RankingsFilter } from './RankingsFilter';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function mountAt(pathname: string) {
  mockPathname.current = pathname;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(RankingsFilter)));
}

async function unmount() {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
}

/** Next writes the new board's URL before the old card unmounts; this stands in for that commit. */
async function arriveAt(pathname: string) {
  window.history.replaceState(null, '', pathname);
  await unmount();
  await mountAt(pathname);
}

async function pick(value: string) {
  await act(async () => (container!.querySelector(`[data-value="${value}"]`) as HTMLButtonElement).click());
}

const startUrl = window.location.href;

afterEach(async () => {
  await unmount();
  mockReplace.mockReset();
  window.history.replaceState(null, '', startUrl);
});

describe('RankingsFilter focus after a filter change', () => {
  it('puts focus back on the dropdown that changed once the new board mounts', async () => {
    await mountAt('/rankings/az/u12/male');
    await pick('u13');
    expect(mockReplace).toHaveBeenCalledWith('/rankings/az/u13/male', { scroll: false });

    await arriveAt('/rankings/az/u13/male');

    expect(document.activeElement?.id).toBe('rankings-filter-age');
  });

  it('puts focus back on the gender dropdown after a gender change', async () => {
    await mountAt('/rankings/az/u12/male');
    await pick('female');

    await arriveAt('/rankings/az/u12/female');

    expect(document.activeElement?.id).toBe('rankings-filter-gender');
  });

  it('leaves focus alone when the next board to mount is a different one', async () => {
    await mountAt('/rankings/az/u12/male');
    await pick('female');

    await arriveAt('/rankings/ca/u12/male');

    expect(document.activeElement).toBe(document.body);
  });

  it('takes focus once, not again when the visitor comes back to that board later', async () => {
    await mountAt('/rankings/az/u12/male');
    await pick('u13');
    await arriveAt('/rankings/az/u13/male');
    expect(document.activeElement?.id).toBe('rankings-filter-age');
    (document.activeElement as HTMLElement).blur();

    await unmount();
    await mountAt('/rankings/az/u13/male');

    expect(document.activeElement).toBe(document.body);
  });

  it('drops the note when the visitor goes elsewhere before the new board arrives', async () => {
    await mountAt('/rankings/az/u12/male');
    await pick('u13');

    // Another page (the blog, say) opens before the board loads; the board is visited later by a link.
    window.history.pushState(null, '', '/blog');
    await unmount();
    window.history.pushState(null, '', '/rankings/az/u13/male');
    await mountAt('/rankings/az/u13/male');

    expect(document.activeElement).toBe(document.body);
  });

  it('drops the note when the visitor goes Back before the new board arrives, then follows a link to it', async () => {
    window.history.pushState(null, '', '/');
    window.history.pushState(null, '', '/rankings/az/u12/male');
    await mountAt('/rankings/az/u12/male');
    await pick('u13');

    // Back to the home page before the board loads; a link there then opens that board.
    window.history.back();
    await vi.waitFor(() => expect(window.location.pathname).toBe('/'));
    await unmount();
    window.history.pushState(null, '', '/rankings/az/u13/male');
    await mountAt('/rankings/az/u13/male');

    expect(document.activeElement).toBe(document.body);
  });
});
