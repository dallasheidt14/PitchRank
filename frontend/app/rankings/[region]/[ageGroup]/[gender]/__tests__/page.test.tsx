import { describe, expect, it, vi } from 'vitest';
import { notFound, permanentRedirect } from 'next/navigation';
import type { ReactElement } from 'react';

const { mockGetRankings } = vi.hoisted(() => ({ mockGetRankings: vi.fn() }));

vi.mock('next/navigation', () => ({
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
  permanentRedirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT ${url}`);
  }),
}));
vi.mock('@/lib/api', () => ({
  api: {
    getRankings: mockGetRankings,
    getActiveRankingsCount: vi.fn().mockResolvedValue(2),
  },
}));
vi.mock('@/lib/cohort-seo', () => ({
  computeCohortModules: () => ({ stub: true }),
  getRelatedGuide: () => ({ slug: 'arizona-guide', title: 'Arizona Guide' }),
}));
vi.mock('@/components/RankingsPageContent', () => ({ RankingsPageContent: () => null }));
vi.mock('@/components/CohortSEOContent', () => ({ CohortSEOContent: () => null, CohortFAQ: () => null }));

import RankingsPage from '../page';
import { RankingsPageContent } from '@/components/RankingsPageContent';
import { CohortSEOContent, CohortFAQ } from '@/components/CohortSEOContent';
import { flatten } from '@/test/flatten';

// A state board's rows arrive in PowerScore order with unranked teams mixed in. Published ranks can skip a
// number (a team excluded after ranking), so position in the list is not the rank.
const STATE_BOARD = [
  { team_id_master: 't1', team_name: 'Alpha', power_score_final: 0.6, rank_in_state_final: 1 },
  { team_id_master: 't2', team_name: 'Unranked United', power_score_final: 0.55, rank_in_state_final: null },
  { team_id_master: 't3', team_name: 'Charlie', power_score_final: 0.52, rank_in_state_final: 4 },
  { team_id_master: 't4', team_name: 'Bravo', power_score_final: 0.5, rank_in_state_final: 2 },
  // A placeholder name is shown as its club, as the table shows it.
  {
    team_id_master: 't5',
    team_name: 'unknown_4482913',
    club_name: 'Aardvark SC',
    power_score_final: 0.45,
    rank_in_state_final: 5,
  },
];

// The national function returns no state rank at all.
const NATIONAL_BOARD = [
  { team_id_master: 'n1', team_name: 'Delta', power_score_final: 0.7, rank_in_cohort_final: 3 },
  { team_id_master: 'n2', team_name: 'Echo', power_score_final: 0.8, rank_in_cohort_final: 1 },
  { team_id_master: 'n3', team_name: 'Unranked Rovers', power_score_final: 0.75, rank_in_cohort_final: null },
];

async function renderBoard(region: string, rows: unknown[]) {
  mockGetRankings.mockResolvedValue(rows);
  return flatten(await RankingsPage({ params: Promise.resolve({ region, ageGroup: 'u13', gender: 'male' }) }));
}

function topList(tree: ReactElement[]): string[] {
  return tree
    .filter((el) => el.type === 'li')
    .map((el) => [(el.props as { children: unknown }).children].flat().slice(0, 3).join(''));
}

describe('RankingsPage layout', () => {
  it('puts the table straight after the intro, then At a Glance, the guide and the FAQ, in that order', async () => {
    const tree = await renderBoard('az', STATE_BOARD);
    const at = (match: (el: ReactElement) => boolean) => tree.findIndex(match);

    const order = [
      at((el) => el.type === 'h1'),
      at((el) => (el.props as { className?: string }).className === 'sr-only'),
      at((el) => el.type === RankingsPageContent),
      at((el) => el.type === CohortSEOContent),
      at((el) => el.type === 'a' && (el.props as { href?: string }).href === '/blog/arizona-guide'),
      at((el) => el.type === CohortFAQ),
    ];
    expect(order.every((index) => index >= 0)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(tree.some((el) => /\border-/.test((el.props as { className?: string }).className ?? ''))).toBe(false);
  });

  it('lists only ranked teams in the hidden top list, in order of their published state rank', async () => {
    expect(topList(await renderBoard('az', STATE_BOARD))).toEqual([
      '1. Alpha',
      '2. Bravo',
      '4. Charlie',
      '5. Aardvark SC',
    ]);
  });

  it('numbers a national board by national rank', async () => {
    expect(topList(await renderBoard('national', NATIONAL_BOARD))).toEqual(['1. Echo', '3. Delta']);
  });

  // The visible <Breadcrumbs /> emits the BreadcrumbList; a second one from the page would duplicate it.
  it('emits only its own RankingTable data, no BreadcrumbList', async () => {
    const tree = await renderBoard('az', STATE_BOARD);
    // Structured data is a literal script or the output of a *Schema component, which flatten does not call.
    const ldTypes = tree
      .flatMap((el) =>
        typeof el.type === 'function' && el.type.name.endsWith('Schema')
          ? flatten((el.type as (props: unknown) => unknown)(el.props))
          : [el]
      )
      .filter((el) => el.type === 'script')
      .map(
        (el) =>
          JSON.parse((el.props as { dangerouslySetInnerHTML: { __html: string } }).dangerouslySetInnerHTML.__html)[
            '@type'
          ]
      );

    expect(ldTypes).toEqual(['RankingTable']);
  });
});

describe('RankingsPage URL validation', () => {
  const render = (region: string, ageGroup: string, gender: string) =>
    RankingsPage({ params: Promise.resolve({ region, ageGroup, gender }) });

  it.each([
    ['xx', 'u13', 'male'],
    ['az', 'u13', 'boys'],
    ['az', 'u9', 'male'],
    ['az', 'u18', 'female'],
  ])('returns not found for /rankings/%s/%s/%s', async (region, ageGroup, gender) => {
    mockGetRankings.mockResolvedValue(STATE_BOARD);
    await expect(render(region, ageGroup, gender)).rejects.toThrow('NEXT_NOT_FOUND');
    expect(notFound).toHaveBeenCalled();
  });

  it('sends an upper-case URL to the lower-case board', async () => {
    mockGetRankings.mockResolvedValue(STATE_BOARD);
    await expect(render('AZ', 'U13', 'Male')).rejects.toThrow('NEXT_REDIRECT /rankings/az/u13/male');
    expect(permanentRedirect).toHaveBeenCalledWith('/rankings/az/u13/male');
  });

  it('renders every board the sitemap lists', async () => {
    mockGetRankings.mockResolvedValue(STATE_BOARD);
    await expect(render('national', 'u19', 'female')).resolves.toBeDefined();
    await expect(render('wy', 'u10', 'male')).resolves.toBeDefined();
  });
});

describe('RankingsPage failed fetch', () => {
  it('throws after the build so a failed refresh keeps the last good page', async () => {
    mockGetRankings.mockRejectedValue(new Error('statement timeout'));
    await expect(
      RankingsPage({ params: Promise.resolve({ region: 'national', ageGroup: 'u13', gender: 'male' }) })
    ).rejects.toThrow('statement timeout');
  });

  it('still renders an empty board during the build, which has no earlier page to keep', async () => {
    vi.stubEnv('NEXT_PHASE', 'phase-production-build');
    mockGetRankings.mockRejectedValue(new Error('statement timeout'));
    await expect(
      RankingsPage({ params: Promise.resolve({ region: 'national', ageGroup: 'u13', gender: 'male' }) })
    ).resolves.toBeDefined();
    vi.unstubAllEnvs();
  });
});
