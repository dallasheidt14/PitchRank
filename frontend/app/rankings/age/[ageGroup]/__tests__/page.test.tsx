import { describe, expect, it, vi } from 'vitest';
import { permanentRedirect } from 'next/navigation';

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
    getRankings: vi.fn().mockResolvedValue([]),
    getRankingsCount: vi.fn().mockResolvedValue(0),
  },
}));
vi.mock('@/components/Breadcrumbs', () => ({ Breadcrumbs: () => null }));

import AgeGroupPage from '../page';
import { api } from '@/lib/api';
import { flatten } from '@/test/flatten';

const render = (ageGroup: string) => AgeGroupPage({ params: Promise.resolve({ ageGroup }) });

function ageLinks(tree: ReturnType<typeof flatten>): string[] {
  return tree
    .map((el) => (el.props as { href?: unknown }).href)
    .filter((href): href is string => typeof href === 'string' && href.startsWith('/rankings/age/'));
}

describe('AgeGroupPage', () => {
  it.each(['u18', 'U18'])('sends /rankings/age/%s to the U19 page', async (ageGroup) => {
    await expect(render(ageGroup)).rejects.toThrow('NEXT_REDIRECT /rankings/age/u19');
    expect(permanentRedirect).toHaveBeenCalledWith('/rankings/age/u19');
  });

  it("shows top teams' PowerScores on the boards' 0-100 scale, boys and girls", async () => {
    const topTeam = [
      {
        team_id_master: 'team-1',
        team_name: 'Futboltech U12 Liverpool',
        club_name: 'Futboltech',
        state: 'NJ',
        power_score_final: 0.4892,
        rank_in_cohort_final: 1,
      },
    ] as Awaited<ReturnType<typeof api.getRankings>>;
    vi.mocked(api.getRankings).mockResolvedValueOnce(topTeam).mockResolvedValueOnce(topTeam);

    const cells = flatten(await render('u12'))
      .filter((el) => el.type === 'td')
      .map((el) => (el.props as { children?: unknown }).children);

    expect(cells.filter((cell) => cell === '48.92')).toHaveLength(2);
  });

  it('links U17 straight on to U19 and never to the U18 page', async () => {
    const links = ageLinks(flatten(await render('u17')));

    expect(links).toContain('/rankings/age/u19');
    expect(links).not.toContain('/rankings/age/u18');
  });
});
