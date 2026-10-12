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
});
