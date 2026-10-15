import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';

vi.mock('@/lib/api', () => ({
  api: {
    getDbStats: vi.fn().mockResolvedValue({ totalGames: 1, totalTeams: 1 }),
    getRankings: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('@/components/HowWeRank', () => ({ HowWeRank: () => null }));
vi.mock('@/components/FeatureShowcase', () => ({ FeatureShowcase: () => null }));
vi.mock('@/components/RecentMovers', () => ({ RecentMovers: () => null }));
vi.mock('@/components/SeasonRolloverNotice', () => ({ SeasonRolloverNotice: () => null }));

import Home from '../page';
import { FindYourTeamButton } from '@/components/FindYourTeamButton';
import { flatten } from '@/test/flatten';

type HeroButton = ReactElement<{ 'data-testid'?: string; variant?: string; children?: ReactElement<{ href: string }> }>;

describe('Home hero', () => {
  it('leads with "Find your team", then rankings, then the report card in outline', async () => {
    const tree = flatten(await Home());
    const row = tree.find((el) => (el.props as { className?: string }).className === 'flex flex-wrap gap-3')!;
    const [first, ...rest] = [(row.props as { children: unknown }).children].flat() as HeroButton[];

    expect(first.type).toBe(FindYourTeamButton);
    expect(
      rest.map((button) => [button.props['data-testid'], button.props.variant, button.props.children!.props.href])
    ).toEqual([
      ['cta-rankings', 'secondary', '/rankings'],
      ['cta-report-card', 'outline', '/report-card'],
    ]);
  });
});
