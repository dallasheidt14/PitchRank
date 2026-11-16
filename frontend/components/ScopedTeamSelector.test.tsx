import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ScopedTeamSelector } from './ScopedTeamSelector';

const REBELS = {
  team_id_master: 'team-rebels',
  team_name: 'Rebels SC 2014',
  club_name: 'Rebels SC',
  age_group: 'u13',
  gender: 'Female',
  state_code: 'AZ',
  state: 'AZ',
};
const REBELS_BLUE = { ...REBELS, team_id_master: 'team-rebels-blue', team_name: 'Rebels SC 2014 Blue' };

const mockFetch = vi.fn();

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function respondWith(match: string) {
  mockFetch.mockResolvedValue({ ok: true, json: async () => ({ teams: [REBELS, REBELS_BLUE], match }) });
}

async function renderAndType(query: string) {
  await act(async () => {
    root!.render(
      React.createElement(ScopedTeamSelector, {
        ageGroup: 'u13',
        gender: 'Female',
        stateCode: 'az',
        value: null,
        onChange: vi.fn(),
      })
    );
  });
  const input = container!.querySelector('input') as HTMLInputElement;
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setValue.call(input, query);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return input;
}

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('ScopedTeamSelector search', () => {
  it.each([
    ['exact', false],
    ['similar', true],
    ['relaxed', true],
  ])('labels %s results as close matches: %s', async (match, labelled) => {
    respondWith(match);

    await renderAndType('rebles');

    expect(container!.textContent).toContain('Rebels SC 2014');
    expect(container!.textContent?.includes('Showing close matches')).toBe(labelled);
  });

  it('scrolls the row the arrow keys highlight into view', async () => {
    const scrolled: Element[] = [];
    const original = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = function (this: HTMLElement) {
      scrolled.push(this);
    };
    try {
      respondWith('similar');
      const input = await renderAndType('rebles');

      await act(async () => {
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
      });

      expect(scrolled.at(-1)?.tagName).toBe('BUTTON');
      expect(scrolled.at(-1)?.textContent).toContain('Rebels SC 2014 Blue');
    } finally {
      HTMLElement.prototype.scrollIntoView = original;
    }
  });

  // Focus stays in the box while the arrows move, so a screen reader learns the highlighted team
  // only through aria-activedescendant naming that option.
  it('points the search box at the listbox and at the option the arrow keys highlight', async () => {
    respondWith('exact');
    const input = await renderAndType('rebels');

    await act(async () => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    });

    const options = Array.from(container!.querySelectorAll('[role="option"]'));
    expect(options.map((option) => option.getAttribute('aria-selected'))).toEqual(['false', 'true']);
    expect(input.getAttribute('aria-expanded')).toBe('true');
    expect(input.getAttribute('aria-controls')).toBe(container!.querySelector('[role="listbox"]')!.id);
    expect(input.getAttribute('aria-activedescendant')).toBe(options[1].id);
  });

  // Each keystroke's search cancels the one before; fetch rejects a cancelled request with AbortError.
  it('keeps showing the loading message while a newer search runs after an older one is cancelled', async () => {
    mockFetch.mockImplementation(
      (_url: string, init: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        })
    );
    const input = await renderAndType('rebels');
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
    await act(async () => {
      setValue.call(input, 'rebels sc');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(container!.textContent).toContain('Searching your group...');
    expect(container!.textContent).not.toContain('No teams matching');
  });

  // The previous search's rows are still held while the next one loads, but the listbox is not drawn.
  it('reports the list closed while the next search loads, so the box never points at a missing list', async () => {
    respondWith('exact');
    const input = await renderAndType('rebels');
    expect(input.getAttribute('aria-expanded')).toBe('true');

    mockFetch.mockReturnValue(new Promise(() => {}));
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
    await act(async () => {
      setValue.call(input, 'rebels sc');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    expect(container!.textContent).toContain('Searching your group...');
    expect(container!.querySelector('[role="listbox"]')).toBeNull();
    expect(input.getAttribute('aria-expanded')).toBe('false');
    expect(input.hasAttribute('aria-activedescendant')).toBe(false);
  });
});
