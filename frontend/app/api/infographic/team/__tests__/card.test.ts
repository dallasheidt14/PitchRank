import { describe, expect, it } from 'vitest';
import {
  buildTeamCard,
  fitNameSize,
  tallyRecord,
  type TeamCardRanking,
  type TeamCardRow,
  type TeamGame,
} from '../card';

const TEAM = 'aaaaaaaa-0000-4000-8000-000000000001';
const MERGED = 'aaaaaaaa-0000-4000-8000-000000000002';
const OTHER = 'bbbbbbbb-0000-4000-8000-000000000009';

// One game per outcome, and each outcome from a different side of the fixture, so inverting
// the home/away branch cannot leave the tally unchanged.
const GAMES: TeamGame[] = [
  { home_team_master_id: TEAM, home_score: 3, away_score: 1 },
  { home_team_master_id: OTHER, home_score: 0, away_score: 2 },
  { home_team_master_id: TEAM, home_score: 1, away_score: 2 },
  { home_team_master_id: OTHER, home_score: 1, away_score: 1 },
];

// A real registered name, and the one that clipped on the right and pushed the stat rail
// off the bottom of the card before the name was sized to fit.
const LONG_NAME = 'COLUMBIA YOUTH SOCCER ASSOCIATION - COLUMBIA YOUTH SOCCER ASSOCIATION CYSA 2012 STINGERS-LIVE OAK';

function makeRow(overrides: Partial<TeamCardRow> = {}): TeamCardRow {
  return {
    team_name: 'RSL Arizona North 13B Elite',
    club_name: 'RSL Arizona North',
    league: null,
    distinction: null,
    state_code: 'AZ',
    age_group: 'u13',
    gender: 'Male',
    ...overrides,
  };
}

function makeRanking(overrides: Partial<TeamCardRanking> = {}): TeamCardRanking {
  return {
    rank_in_cohort_final: 87,
    power_score_final: 0.8241,
    total_wins: 14,
    total_losses: 2,
    total_draws: 1,
    ...overrides,
  };
}

describe('buildTeamCard', () => {
  it('leads with the state rank, named in full', () => {
    const card = buildTeamCard(makeRow(), makeRanking(), 4);

    expect(card.hero).toBe('#4');
    expect(card.heroLabel).toBe('IN ARIZONA');
    expect(card.ranked).toBe(true);
  });

  it('demotes the national rank and PowerScore to the stat rail', () => {
    const card = buildTeamCard(makeRow(), makeRanking(), 4);

    expect(card.record).toBe('14-2-1');
    expect(card.nationalRank).toBe('#87');
    expect(card.powerScore).toBe('82.41');
  });

  // The hero's first branch is `stateRank != null && state`. A fixture missing both
  // conjuncts would still pass with either half of the condition deleted, so each of
  // the next two violates exactly one.
  it('falls back to the national rank when there is no state rank', () => {
    const card = buildTeamCard(makeRow(), makeRanking(), null);

    expect(card.hero).toBe('#87');
    expect(card.heroLabel).toBe('NATIONALLY');
    expect(card.ranked).toBe(true);
  });

  it('falls back to the national rank when the team has a state rank but no state on file', () => {
    const card = buildTeamCard(makeRow({ state_code: null }), makeRanking(), 4);

    expect(card.hero).toBe('#87');
    expect(card.heroLabel).toBe('NATIONALLY');
  });

  it('falls back to the record so an unranked team still gets a card', () => {
    const card = buildTeamCard(makeRow(), makeRanking({ rank_in_cohort_final: null }), null);

    expect(card.hero).toBe('14-2-1');
    expect(card.heroLabel).toBe('RECORD');
    expect(card.nationalRank).toBe('--');
    expect(card.ranked).toBe(false);
  });

  it('shows the real record for a team the ranking pipeline has no row for', () => {
    const card = buildTeamCard(makeRow(), tallyRecord(GAMES, [TEAM]), null);

    expect(card.hero).toBe('2-1-1');
    expect(card.heroLabel).toBe('RECORD');
    expect(card.powerScore).toBe('--');
    expect(card.ranked).toBe(false);
  });

  it('shows the registered name rather than one composed from the club', () => {
    const card = buildTeamCard(
      makeRow({ team_name: '2014 Elite', club_name: 'Phoenix United Futbol Club', distinction: 'elite' }),
      makeRanking(),
      1
    );

    expect(card.displayName).toBe('2014 ELITE');
    expect(card.subtitle).toBe('Phoenix United Futbol Club · Arizona');
  });

  it('composes from the club when the registered name is an unresolved placeholder', () => {
    const card = buildTeamCard(
      makeRow({ team_name: 'unknown_884213', club_name: 'CCV Stars', league: 'GA', distinction: null }),
      makeRanking(),
      12
    );

    expect(card.displayName).toBe('CCV STARS GA');
  });

  it('drops the state from the subtitle when the team has none', () => {
    const card = buildTeamCard(makeRow({ state_code: null }), makeRanking(), null);

    expect(card.subtitle).toBe('RSL Arizona North');
  });

  it.each([
    ['Male', 'U13 BOYS'],
    ['Female', 'U13 GIRLS'],
    ['M', 'U13 BOYS'],
    ['F', 'U13 GIRLS'],
  ])('renders the cohort chip for gender %s', (gender, expected) => {
    expect(buildTeamCard(makeRow({ gender }), makeRanking(), 4).cohort).toBe(expected);
  });

  it('keeps the age group when the gender is unrecognised', () => {
    expect(buildTeamCard(makeRow({ gender: 'Coed' }), makeRanking(), 4).cohort).toBe('U13');
  });

  it('omits the cohort chip when the team has no age group', () => {
    expect(buildTeamCard(makeRow({ age_group: null }), makeRanking(), 4).cohort).toBeNull();
  });

  it('sizes the name to fit, and carries the size on the card', () => {
    expect(buildTeamCard(makeRow({ team_name: '2014 Elite' }), makeRanking(), 1).nameSize).toBe(82);
    expect(buildTeamCard(makeRow({ team_name: LONG_NAME }), makeRanking(), 248).nameSize).toBe(46);
  });

  it('spells out a state whose code US_STATES does not carry', () => {
    const card = buildTeamCard(makeRow({ state_code: 'ZZ' }), makeRanking(), 3);

    expect(card.heroLabel).toBe('IN ZZ');
  });
});

describe('tallyRecord', () => {
  it('counts wins, losses and draws from both sides of the fixture', () => {
    expect(tallyRecord(GAMES, [TEAM])).toMatchObject({ total_wins: 2, total_losses: 1, total_draws: 1 });
  });

  it('counts a win the team took at home', () => {
    const games = [{ home_team_master_id: TEAM, home_score: 3, away_score: 1 }];

    expect(tallyRecord(games, [TEAM])).toMatchObject({ total_wins: 1, total_losses: 0, total_draws: 0 });
  });

  it('counts a win the team took away, reading the away score', () => {
    const games = [{ home_team_master_id: OTHER, home_score: 1, away_score: 3 }];

    expect(tallyRecord(games, [TEAM])).toMatchObject({ total_wins: 1, total_losses: 0, total_draws: 0 });
  });

  it('counts a loss the team took away', () => {
    const games = [{ home_team_master_id: OTHER, home_score: 3, away_score: 1 }];

    expect(tallyRecord(games, [TEAM])).toMatchObject({ total_wins: 0, total_losses: 1, total_draws: 0 });
  });

  it('counts games the team played under an id a merge retired', () => {
    const games = [{ home_team_master_id: MERGED, home_score: 4, away_score: 0 }];

    expect(tallyRecord(games, [TEAM, MERGED])).toMatchObject({ total_wins: 1, total_losses: 0 });
    expect(tallyRecord(games, [TEAM])).toMatchObject({ total_wins: 0, total_losses: 1 });
  });

  it('leaves rank and PowerScore empty, since the pipeline produced neither', () => {
    const record = tallyRecord(GAMES, [TEAM]);

    expect(record.rank_in_cohort_final).toBeNull();
    expect(record.power_score_final).toBeNull();
  });

  it('returns a goalless record for a team with no completed games', () => {
    expect(tallyRecord([], [TEAM])).toMatchObject({ total_wins: 0, total_losses: 0, total_draws: 0 });
  });
});

describe('fitNameSize', () => {
  it.each([
    [10, 82],
    [27, 82],
    [46, 72],
    [60, 62],
    [97, 46],
    [200, 40],
  ])('sizes a %i-character name at %ipx', (length, expected) => {
    expect(fitNameSize('X'.repeat(length))).toBe(expected);
  });

  it('never grows the type as the name gets longer', () => {
    const sizes = Array.from({ length: 120 }, (_, i) => fitNameSize('X'.repeat(i + 1)));

    expect(sizes).toEqual([...sizes].sort((a, b) => b - a));
  });

  it('bottoms out rather than returning undefined for an absurd name', () => {
    expect(fitNameSize('X'.repeat(5000))).toBe(40);
  });
});
