import { describe, expect, it } from 'vitest';
import { composeTeamDisplay, composeTeamMeta, formatDistinction, formatLeague, teamDisplayName } from './utils';

describe('composeTeamDisplay', () => {
  it('composes club + league + distinction for clean data', () => {
    expect(
      composeTeamDisplay({
        team_name: 'VDA ECNL 2012',
        club_name: 'Virginia Development Academy',
        league: 'ECNL',
        distinction: null,
      })
    ).toBe('Virginia Development Academy ECNL');
  });

  it('composes a clean color/squad distinction', () => {
    expect(
      composeTeamDisplay({
        team_name: 'OK Energy FC 2014 Black',
        club_name: 'Oklahoma Energy FC',
        league: null,
        distinction: 'black',
      })
    ).toBe('Oklahoma Energy FC Black');
  });

  it('falls back to verbatim team_name for MLS NEXT (has_modular11_alias)', () => {
    expect(
      composeTeamDisplay({
        team_name: 'Cedar Stars Academy Bergen U14 HD',
        club_name: 'Cedar Stars Academy - Bergen',
        league: 'MLS_NEXT_HD',
        distinction: 'hd',
        has_modular11_alias: true,
      })
    ).toBe('Cedar Stars Academy Bergen U14 HD');
  });

  it('falls back to team_name when club_name is missing', () => {
    expect(composeTeamDisplay({ team_name: 'Some Raw Name', club_name: null, league: null, distinction: 'red' })).toBe(
      'Some Raw Name'
    );
  });

  // Safety net: when the distinction still carries league/tier leakage the
  // resolver did not strip (e.g. "Pre-ECNL" leaves an orphaned "pre"), the
  // composed name reads badly, so fall back to the raw team_name.
  describe('league/tier leakage safety net', () => {
    it('falls back for an orphaned "pre" prefix (Pre-ECNL)', () => {
      expect(
        composeTeamDisplay({
          team_name: 'Dallas Texans PRE ECNL 2014 Salazar',
          club_name: 'Dallas Texans',
          league: null,
          distinction: 'salazar|pre',
        })
      ).toBe('Dallas Texans PRE ECNL 2014 Salazar');
    });

    it('falls back for "i|pre" (numbered Pre-ECNL squad)', () => {
      expect(
        composeTeamDisplay({
          team_name: 'OK Energy FC PRE-ECNL 2014 I',
          club_name: 'Oklahoma Energy FC',
          league: null,
          distinction: 'i|pre',
        })
      ).toBe('OK Energy FC PRE-ECNL 2014 I');
    });

    it('falls back for "bv|pre|mls" (Pre-MLS-Next with club + league leakage)', () => {
      expect(
        composeTeamDisplay({
          team_name: 'SPORTING BV Pre-MLS Next 2014',
          club_name: 'Sporting Blue Valley',
          league: null,
          distinction: 'bv|pre|mls',
        })
      ).toBe('SPORTING BV Pre-MLS Next 2014');
    });

    it('falls back when a league token (ecnl) leaks into distinction', () => {
      expect(
        composeTeamDisplay({
          team_name: 'Raw Team ECNL Name',
          club_name: 'Some Club',
          league: null,
          distinction: 'ecnl',
        })
      ).toBe('Raw Team ECNL Name');
    });

    it.each(['preecnl', 'premls', 'ecnlrl', 'mls2', 'g08dpl', 'edpl', 'npl2'])(
      'falls back for smushed/affixed league token "%s"',
      (distinction) => {
        expect(composeTeamDisplay({ team_name: 'RAW NAME', club_name: 'Some Club', league: null, distinction })).toBe(
          'RAW NAME'
        );
      }
    );

    it.each(['white', 'premier', 'development', 'select', 'elite', 'smith'])(
      'does NOT fall back for legitimate squad distinction "%s"',
      (distinction) => {
        const out = composeTeamDisplay({
          team_name: 'RAW NAME',
          club_name: 'Phoenix Rising',
          league: null,
          distinction,
        });
        expect(out).not.toBe('RAW NAME');
        expect(out).toContain('Phoenix Rising');
      }
    );
  });
});

describe('teamDisplayName', () => {
  it('tells apart squads that compose to the same club label', () => {
    const squads = [
      { team_name: '2014/15G Copper', club_name: 'Colorado United', league: null, distinction: null },
      { team_name: 'Colorado United - Dash', club_name: 'Colorado United', league: null, distinction: null },
      { team_name: 'Aspire 13/14', club_name: 'Colorado United', league: null, distinction: null },
    ];
    expect(squads.map((t) => composeTeamDisplay(t))).toEqual(['Colorado United', 'Colorado United', 'Colorado United']);
    expect(squads.map((t) => teamDisplayName(t))).toEqual([
      '2014/15G Copper',
      'Colorado United - Dash',
      'Aspire 13/14',
    ]);
  });

  it('composes instead when the name is still an unresolved placeholder', () => {
    expect(
      teamDisplayName({
        team_name: 'unknown_4482913',
        club_name: 'Oklahoma Energy FC',
        league: null,
        distinction: 'black',
      })
    ).toBe('Oklahoma Energy FC Black');
  });

  // Most placeholder-named teams have no club on file, so the fallback usually cannot improve
  // on the placeholder.
  it('leaves an unresolved placeholder alone when no club is on file', () => {
    expect(teamDisplayName({ team_name: 'unknown_4482913', club_name: null })).toBe('unknown_4482913');
  });

  // Only `unknown_<numeric provider id>` is a placeholder; the backend's
  // _is_placeholder_unknown_team draws the same line. Treating any `unknown_` prefix as one
  // would swap a real name for its club label, which is the collapse teamDisplayName prevents.
  it('keeps a registered name that merely starts with unknown_', () => {
    expect(teamDisplayName({ team_name: 'unknown_elite', club_name: 'Oklahoma Energy FC' })).toBe('unknown_elite');
    expect(teamDisplayName({ team_name: 'unknown_Playoffs AWinner', club_name: 'Some Club' })).toBe(
      'unknown_Playoffs AWinner'
    );
  });

  // composeTeamDisplay returns the raw name for these two, which for a placeholder is the one
  // string the fallback exists to avoid — so teamDisplayName must not route through its guards.
  it('composes a placeholder even when the raw-name guards would fire', () => {
    expect(
      teamDisplayName({
        team_name: 'unknown_4482913',
        club_name: 'Cedar Stars Academy',
        league: 'MLS_NEXT_HD',
        has_modular11_alias: true,
      })
    ).toBe('Cedar Stars Academy MLS Next');
    expect(
      teamDisplayName({ team_name: 'unknown_4482913', club_name: 'Dallas Texans', distinction: 'salazar|pre' })
    ).toBe('Dallas Texans Pre Salazar');
  });

  it('composes instead when the name is blank', () => {
    expect(teamDisplayName({ team_name: '   ', club_name: 'Dynamos SC', league: null, distinction: null })).toBe(
      'Dynamos SC'
    );
  });

  // A registered label freezes while the cohort rolls every Aug 1, so a name's own U-token
  // usually contradicts its stored age.
  it('never appends the cohort age to the registered name', () => {
    expect(
      teamDisplayName({ team_name: 'RU ORANGE U10B ELITE 1', club_name: 'Richmond United', league: null, age: 11 })
    ).toBe('RU ORANGE U10B ELITE 1');
    expect(teamDisplayName({ team_name: 'BUCKS BYRNES U15', club_name: 'Bucks Soccer Club', age: 19 })).toBe(
      'BUCKS BYRNES U15'
    );
  });
});

describe('composeTeamMeta', () => {
  it('joins state, age group, and gender with bullets', () => {
    expect(composeTeamMeta({ state: 'az', age: 14, gender: 'M' })).toBe('AZ • U14 Boys');
  });

  it('omits the age fragment when age is unresolved', () => {
    expect(composeTeamMeta({ state: 'AZ', age: 0, gender: 'M' })).toBe('AZ');
  });

  it('omits the leading bullet when state is missing', () => {
    expect(composeTeamMeta({ state: null, age: 14, gender: 'M' })).toBe('U14 Boys');
  });

  it('returns an empty string when nothing is known', () => {
    expect(composeTeamMeta({ state: null, age: null, gender: null })).toBe('');
  });
});

describe('formatLeague', () => {
  it('maps known league codes', () => {
    expect(formatLeague('ECNL_RL')).toBe('ECNL RL');
    expect(formatLeague('MLS_NEXT')).toBe('MLS Next');
  });
  it('returns null for empty input', () => {
    expect(formatLeague(null)).toBeNull();
  });
});

describe('formatDistinction', () => {
  it('reverses words to reading order and converts roman to arabic', () => {
    expect(formatDistinction('i|elite|pre')).toBe('Pre Elite 1');
  });
  it('keeps numerals last for a color + number distinction', () => {
    expect(formatDistinction('white|2')).toBe('White 2');
  });
  it('returns null for empty input', () => {
    expect(formatDistinction(null)).toBeNull();
  });
});
