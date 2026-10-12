import { describe, it, expect } from 'vitest';
import { parseTeamSearchQuery } from './teamSearchQuery';

const SEASON = 2026;
const parse = (q: string) => parseTeamSearchQuery(q, SEASON);

describe('parseTeamSearchQuery', () => {
  it('reads every U-form spelling as that age group', () => {
    const expected = parse('u13');
    expect(expected).toEqual({
      terms: [],
      fuzzyTerms: [],
      ageGroups: ['u13'],
      ageSpellings: ['u13', 'bu13', 'gu13', '13u'],
      gender: null,
    });
    for (const q of ['U13', 'U-13', 'u 13', 'under 13', '13u', 'U 13']) {
      expect(parse(q)).toEqual(expected);
    }
  });

  it('reads a gendered U-form as age plus gender', () => {
    expect(parse('BU13')).toMatchObject({ ageGroups: ['u13'], gender: 'Male' });
    expect(parse('GU13')).toMatchObject({ ageGroups: ['u13'], gender: 'Female' });
    expect(parse('u13g')).toMatchObject({ ageGroups: ['u13'], gender: 'Female' });
    expect(parse('bu 14')).toMatchObject({ ageGroups: ['u14'], gender: 'Male', terms: [] });
  });

  it('reads a birth year as both cohorts it can mean this season', () => {
    const parsed = parse('2014');
    expect(parsed.ageGroups).toEqual(['u12', 'u13']);
    expect(parsed.ageSpellings).toEqual(['2014', 'b2014', 'g2014', '2014b', '2014g', 'b14', 'g14', '14b', '14g']);
    expect(parsed.ageSpellings).not.toContain('14');
    expect(parsed.terms).toEqual([]);
  });

  it('reads every gendered birth-year spelling', () => {
    for (const q of ['B2014', '2014B', 'b14', '14B']) {
      expect(parse(q)).toMatchObject({ ageGroups: ['u12', 'u13'], gender: 'Male', terms: [] });
    }
    for (const q of ['G2014', '2014g', 'g14', '14G']) {
      expect(parse(q)).toMatchObject({ ageGroups: ['u12', 'u13'], gender: 'Female', terms: [] });
    }
  });

  it('names a band by its younger year (CLAUDE.md label key)', () => {
    for (const q of ['2013/2014', '2013/14', '13/14', '14/13', '2013-2014', 'B13/14']) {
      expect(parse(q).ageGroups).toEqual(['u13']);
    }
    for (const q of ['2014/2015', '2014/15', '14/15']) {
      expect(parse(q).ageGroups).toEqual(['u12']);
    }
    expect(parse('B13/14').gender).toBe('Male');
    expect(parse('13/14').ageSpellings).toEqual(
      expect.arrayContaining(['2013 2014', '2013 14', '13 2014', '13 14', '14 13', '2014 2013'])
    );
  });

  it('reads a bare two-digit number as either an age or a birth year', () => {
    const parsed = parse('14');
    expect(parsed.ageGroups).toEqual(['u12', 'u13', 'u14']);
    expect(parsed.ageSpellings).toEqual(expect.arrayContaining(['u14', '2014', '14b']));
    expect(parsed.ageSpellings).not.toContain('14');
  });

  it('folds U18 into U19', () => {
    expect(parse('u18').ageGroups).toEqual(['u19']);
    expect(parse('u18').ageSpellings).toEqual(expect.arrayContaining(['u18', 'u19']));
  });

  it('reads gender words', () => {
    for (const q of ['boys', 'boy', 'b', 'male', 'm']) expect(parse(q).gender).toBe('Male');
    for (const q of ['girls', 'girl', 'g', 'female', 'f']) expect(parse(q).gender).toBe('Female');
    expect(parse('boys girls').gender).toBeNull();
  });

  it('keeps the remaining words as text terms', () => {
    expect(parse('rebels 2014 girls')).toEqual({
      terms: ['rebels'],
      fuzzyTerms: ['rebels'],
      ageGroups: ['u12', 'u13'],
      ageSpellings: ['2014', 'b2014', 'g2014', '2014b', '2014g', 'b14', 'g14', '14b', '14g'],
      gender: 'Female',
    });
    expect(parse("o'brien fc").terms).toEqual(["o'brien", 'fc']);
  });

  it('splits text on the separators the stored text normalises', () => {
    expect(parse('ecnl-rl').terms).toEqual(['ecnl', 'rl']);
    expect(parse('ecnl_rl').terms).toEqual(['ecnl', 'rl']);
    expect(parse('ecnl rl').terms).toEqual(['ecnl', 'rl']);
  });

  it('caps terms at six and drops single letters', () => {
    expect(parse('a bb cc dd ee ff gg hh').terms).toEqual(['bb', 'cc', 'dd', 'ee', 'ff', 'gg']);
  });

  it('never reads an age or gender from a word with non-ASCII characters, but still searches it', () => {
    for (const q of ['２０１４', '𝟚𝟘𝟙𝟜', '²⁰¹⁴', 'u1²3', '20１14', 'GİRLS']) {
      const parsed = parse(q);
      expect(parsed.ageGroups).toEqual([]);
      expect(parsed.ageSpellings).toEqual([]);
      expect(parsed.gender).toBeNull();
    }
    expect(parse('Atlético 2014').terms).toEqual(['atlético']);
    expect(parse('FC México').terms).toEqual(['fc', 'méxico']);
  });

  it('composes a pasted accent written as a separate mark, as stored team names are', () => {
    const decomposed = `Me${String.fromCharCode(0x301)}xico`;
    expect(parse(decomposed).terms).toEqual([`m${String.fromCharCode(0xe9)}xico`]);
  });

  it('reads a lone letter split off by punctuation as an initial, not a gender', () => {
    expect(parse('Trident F.C.')).toEqual({
      terms: ['trident'],
      fuzzyTerms: ['trident'],
      ageGroups: [],
      ageSpellings: [],
      gender: null,
    });
    expect(parse('Texas A&M').gender).toBeNull();
    expect(parse('rebels (girls)').gender).toBe('Female');
    expect(parse('rebels u13,girls')).toMatchObject({ terms: ['rebels'], ageGroups: ['u13'], gender: 'Female' });
  });

  it('still reads a lone gender letter that punctuation only surrounds', () => {
    expect(parse('Rebels 2014 (G)').gender).toBe('Female');
    expect(parse('u13 g.').gender).toBe('Female');
    expect(parse('Rebels 2014 B,').gender).toBe('Male');
    expect(parse('Surf 2014 B').gender).toBe('Male');
  });

  it('reads typographic apostrophes and dashes as their ASCII forms', () => {
    expect(parse('O’Fallon').terms).toEqual(["o'fallon"]);
    expect(parse('Rebels 2013–2014').ageGroups).toEqual(['u13']);
    expect(parse('Rebels 2013—2014').ageGroups).toEqual(['u13']);
    expect(parse('“U13” girls')).toMatchObject({ terms: [], ageGroups: ['u13'], gender: 'Female' });
  });

  it('spells a band with the gender letter team names attach to it', () => {
    const spellings = parse('2014/15 girls').ageSpellings;
    for (const s of ['2014 15', '2014 15g', 'g2014 15', '14 15b', 'b2015 14']) expect(spellings).toContain(s);
    expect(parse('2014/15G')).toMatchObject({ ageGroups: ['u12'], gender: 'Female' });
  });

  it('drops a term longer than any team word, or with no letter or digit', () => {
    expect(parse(`${'x'.repeat(41)} rebels`).terms).toEqual(['rebels']);
    expect(parse(`${'x'.repeat(40)} rebels`).terms).toEqual(['x'.repeat(40), 'rebels']);
    expect(parse('★★ rebels').terms).toEqual(['rebels']);
    expect(parse('1904').terms).toEqual(['1904']);
  });

  it('counts a term by its letters and digits, the only characters the index sees', () => {
    expect(parse("s' 's s'' rebels").terms).toEqual(['rebels']);
    expect(parse("o'fallon ofallon").terms).toEqual(["o'fallon"]);
    const parsed = parse("fc rebels 20' ab'c");
    expect(parsed.terms).toEqual(['fc', 'rebels', "20'", "ab'c"]);
    expect(parsed.fuzzyTerms).toEqual(['rebels', "ab'c"]);
  });

  it('returns nothing for empty input', () => {
    const empty = { terms: [], fuzzyTerms: [], ageGroups: [], ageSpellings: [], gender: null };
    expect(parse('')).toEqual(empty);
    expect(parse('   ')).toEqual(empty);
  });
});
