import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('@/hooks/useUser', () => ({ useUser: () => ({ user: { email: 'admin@example.com' } }) }));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import { MergeTeamsDialog } from './MergeTeamsDialog';

const REBELS = {
  team_id_master: 'team-rebels',
  team_name: 'Rebels SC 2014',
  club_name: 'Rebels SC',
  age_group: 'u13',
  gender: 'Female',
  state_code: 'AZ',
  state: 'AZ',
};

const mockFetch = vi.fn();

let root: Root | null = null;
let container: HTMLDivElement | null = null;

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

describe('MergeTeamsDialog search', () => {
  // A merge combines every game of both teams, so a typo-tolerant candidate must not look
  // like an exact one.
  it.each([
    ['exact', false],
    ['similar', true],
    ['relaxed', true],
  ])('labels %s results as close matches: %s', async (match, labelled) => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ teams: [REBELS], match }) });
    await act(async () => {
      root!.render(
        React.createElement(MergeTeamsDialog, {
          currentTeamId: 'team-current',
          currentTeamName: 'Rebels 2014',
          currentTeamAgeGroup: 'u13',
          currentTeamGender: 'Female',
          currentTeamStateCode: 'AZ',
        })
      );
    });
    await act(async () => {
      [...container!.querySelectorAll('button')].find((b) => b.textContent?.includes('Merge Dupe Teams'))!.click();
    });
    const input = document.body.querySelector('#team-search') as HTMLInputElement;
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
    await act(async () => {
      setValue.call(input, 'rebles');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    // The dialog debounces its search by 300 ms.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 350));
    });

    expect(document.body.textContent).toContain('Rebels SC 2014');
    expect(document.body.textContent?.includes('Showing close matches')).toBe(labelled);
  });
});
