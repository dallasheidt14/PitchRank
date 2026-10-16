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

type HeroButton = ReactElement<{
  'data-testid'?: string;
  variant?: string;
  className?: string;
  children?: ReactElement<{ href: string }>;
}>;

describe('Home hero', () => {
  it('leads with rankings in yellow, then "Find your team" in mint, then the report card in outline', async () => {
    const tree = flatten(await Home());
    const row = tree.find((el) => (el.props as { className?: string }).className === 'flex flex-wrap gap-3')!;
    const [rankings, findTeam, reportCard] = [(row.props as { children: unknown }).children].flat() as HeroButton[];
    const findTeamButton = FindYourTeamButton() as HeroButton;

    expect([rankings.props['data-testid'], rankings.props.children!.props.href]).toEqual(['cta-rankings', '/rankings']);
    expect(rankings.props.className!.split(/\s+/)).toEqual(expect.arrayContaining(['bg-accent', 'text-primary']));
    expect(findTeam.type).toBe(FindYourTeamButton);
    expect(findTeamButton.props.variant).toBe('secondary');
    expect(findTeamButton.props.className).not.toContain('bg-accent');
    expect([reportCard.props['data-testid'], reportCard.props.variant, reportCard.props.children!.props.href]).toEqual([
      'cta-report-card',
      'outline',
      '/report-card',
    ]);
  });
});
