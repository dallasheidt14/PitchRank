import { describe, expect, it } from 'vitest';
import { composeTeamDisplay, formatDistinction, formatLeague } from './utils';

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
