import { describe, expect, it } from 'vitest';
import { computeCohortModules } from './cohort-seo';
import { makeRankingRow as makeTeam } from '@/test/fixtures';

describe('computeCohortModules', () => {
  it('uses activeCount for totalTeams, not the capped teams-array length', () => {
    // The page only fetches the top 2,000; here a single team stands in for that
    // truncated slice while the true cohort has 6,170 Active teams.
    const result = computeCohortModules([makeTeam()], 6170, 'National', 'U12', 'Boys', true, 'national', 'male');

    expect(result.totalTeams).toBe(6170);
    expect(result.positioningHook).toBe('one of the deepest groups in the country');
  });

  it('falls back to teams.length when the active count lookup failed (null)', () => {
    const teams = [makeTeam({ team_id_master: 'a' }), makeTeam({ team_id_master: 'b' })];

    const result = computeCohortModules(teams, null, 'Arizona', 'U12', 'Boys', false, 'az', 'male');

    expect(result.totalTeams).toBe(2);
  });

  it('preserves a genuine zero active count instead of falling back', () => {
    // A cohort with only not-yet-ranked teams: the fetch returns rows but the
    // Active count is a real 0, which must not be replaced by teams.length.
    const teams = [makeTeam({ status: 'Not Enough Ranked Games' })];

    const result = computeCohortModules(teams, 0, 'Arizona', 'U12', 'Boys', false, 'az', 'male');

    expect(result.totalTeams).toBe(0);
  });
});
