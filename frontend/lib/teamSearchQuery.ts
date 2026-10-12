import { soccerSeasonYear } from './teamAge';
import { normalizeAgeGroup } from './utils';

export type TeamSearchMatch = 'exact' | 'similar' | 'relaxed';

/** One row of the `/api/teams/search` response. */
export interface TeamSearchResult {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  age_group: string;
  gender: string;
  state_code: string | null;
  /** Same value as `state_code`, for consumers of the route that read `state`. */
  state: string | null;
  league: string | null;
  distinction: string | null;
  is_ranked: boolean;
}

export interface ParsedTeamSearch {
  terms: string[];
  /** The terms with three or more letters or digits, the fewest a trigram index can narrow on. */
  fuzzyTerms: string[];
  ageGroups: string[];
  ageSpellings: string[];
  gender: 'Male' | 'Female' | null;
}

const MAX_TERMS = 6;
// Longer than any word in live team text; each extra character is another trigram to read.
const MAX_TERM_LENGTH = 40;
const NOT_LETTER_OR_DIGIT = /[^\p{L}\p{N}]/gu;
const MIN_AGE = 6;
const MAX_AGE = 19;

const MALE_WORDS = new Set(['boys', 'boy', 'b', 'male', 'm']);
const FEMALE_WORDS = new Set(['girls', 'girl', 'g', 'female', 'f']);
const U_PREFIXES = new Set(['u', 'bu', 'gu', 'under']);

const U_FORM = /^([bg])?u-?([0-9]{1,2})([bg])?$/;
const U_SUFFIX_FORM = /^([0-9]{1,2})u([bg])?$/;
const BIRTH_YEAR = /^([bg])?(20[0-9]{2})([bg])?$/;
const SHORT_BIRTH_YEAR = /^(?:([bg])([0-9]{2})|([0-9]{2})([bg]))$/;
const BAND = /^([bg])?((?:20)?[0-9]{2})[-/]((?:20)?[0-9]{2})([bg])?$/;
const BARE_TWO_DIGIT = /^[0-9]{2}$/;
const ONE_OR_TWO_DIGITS = /^[0-9]{1,2}$/;

type Gender = 'Male' | 'Female';

function genderLetter(letter: string | undefined): Gender | null {
  if (letter === 'b') return 'Male';
  if (letter === 'g') return 'Female';
  return null;
}

/** Fold U18 into U19 (PitchRank runs no u18 board) and keep ages 6–19. */
function boardAge(age: number): number | null {
  const folded = normalizeAgeGroup(age);
  return folded !== null && folded >= MIN_AGE && folded <= MAX_AGE ? folded : null;
}

function uFormSpellings(age: number): string[] {
  return [`u${age}`, `bu${age}`, `gu${age}`, `${age}u`];
}

function birthYearSpellings(year: number): string[] {
  const yy = String(year).slice(2);
  return [`${year}`, `b${year}`, `g${year}`, `${year}b`, `${year}g`, `b${yy}`, `g${yy}`, `${yy}b`, `${yy}g`];
}

/**
 * A band as team_search_text holds it, separators already spaces, gender letter included
 * (`2013 14`, `b13 14`, `2014 15g`).
 */
function bandSpellings(first: number, second: number): string[] {
  const forms = (year: number) => [String(year), String(year).slice(2)];
  const spellings: string[] = [];
  for (const [a, b] of [
    [first, second],
    [second, first],
  ]) {
    for (const x of forms(a)) {
      for (const y of forms(b)) {
        spellings.push(`${x} ${y}`, `b${x} ${y}`, `g${x} ${y}`, `${x} ${y}b`, `${x} ${y}g`);
      }
    }
  }
  return spellings;
}

interface Token {
  text: string;
  /** A lone letter punctuation split off a longer word, as `f` and `c` from `F.C.`. */
  initial: boolean;
}

/**
 * Split on whitespace, lowercase, and turn ASCII punctuation other than - / _ | ' into
 * spaces. Typographic quotes and dashes become their ASCII forms first; any other
 * non-ASCII character stays inside its word.
 */
function tokenize(raw: string): Token[] {
  const tokens: Token[] = [];
  const folded = raw
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2013\u2014]/g, '-');
  for (const word of folded.split(/\s+/)) {
    const cleaned = word.replace(/[^A-Za-z0-9'\-/_|]/g, (c) => (c < '\x80' ? ' ' : c)).toLowerCase();
    const parts = cleaned.split(' ').filter(Boolean);
    for (const text of parts) tokens.push({ text, initial: parts.length > 1 && text.length === 1 });
  }
  return tokens;
}

/**
 * Parse a typed team search into TEXT terms, an age-group set, the age spellings a team
 * name may carry, and a gender. A token that names an age or a gender in any common
 * form (u13, U-13, under 13, 2014, 14B, G2014, 13/14, boys, g) becomes a constraint
 * rather than a word the team text must contain.
 *
 * A word containing a non-ASCII character is searched as text but never read as an age or
 * a gender, because it stays whole and every age and gender pattern is ASCII-only:
 * deleting the character would join `u1²3` into `u13`, splitting on it turns `20１14` into
 * two valid ages, and NFKC turns full-width digits into ASCII ones. ASCII punctuation
 * becomes a space, and a single letter it splits off a longer word (the `f` of `F.C.`) is an
 * initial, not a gender.
 *
 * A term counts by its letters and digits, because the trigram index ignores the rest: `s'`,
 * `'s` and `s''` are all the one letter `s`. A term with fewer than two (no trigram to narrow
 * on), one longer than MAX_TERM_LENGTH, a repeat of an earlier term's letters and digits, or
 * one past MAX_TERMS is dropped. Only terms with three or more reach the typo-tolerant passes,
 * where a shorter one would recheck most teams.
 */
export function parseTeamSearchQuery(raw: string, seasonYear: number = soccerSeasonYear()): ParsedTeamSearch {
  const rawTokens = tokenize(raw);
  const tokens: Token[] = [];
  for (let i = 0; i < rawTokens.length; i++) {
    const token = rawTokens[i];
    const next = rawTokens[i + 1];
    if (U_PREFIXES.has(token.text) && next !== undefined && ONE_OR_TWO_DIGITS.test(next.text)) {
      tokens.push({ text: token.text === 'under' ? `u${next.text}` : `${token.text}${next.text}`, initial: false });
      i++;
    } else {
      tokens.push(token);
    }
  }

  const ages = new Set<number>();
  const spellings = new Set<string>();
  const genders = new Set<Gender>();
  const textTokens: string[] = [];

  const addBirthYear = (year: number) => {
    let matched = false;
    for (const age of [seasonYear - year, seasonYear - year + 1]) {
      const board = boardAge(age);
      if (board !== null) {
        ages.add(board);
        matched = true;
      }
    }
    if (matched) birthYearSpellings(year).forEach((s) => spellings.add(s));
    return matched;
  };

  const addUForm = (age: number) => {
    const board = boardAge(age);
    if (board === null) return false;
    ages.add(board);
    uFormSpellings(age).forEach((s) => spellings.add(s));
    if (board !== age) uFormSpellings(board).forEach((s) => spellings.add(s));
    return true;
  };

  const addGender = (letter: string | undefined) => {
    const gender = genderLetter(letter);
    if (gender) genders.add(gender);
  };

  for (const { text: token, initial } of tokens) {
    if (!initial && MALE_WORDS.has(token)) {
      genders.add('Male');
      continue;
    }
    if (!initial && FEMALE_WORDS.has(token)) {
      genders.add('Female');
      continue;
    }

    let match = token.match(U_FORM);
    if (match && addUForm(parseInt(match[2], 10))) {
      addGender(match[1]);
      addGender(match[3]);
      continue;
    }

    match = token.match(U_SUFFIX_FORM);
    if (match && addUForm(parseInt(match[1], 10))) {
      addGender(match[2]);
      continue;
    }

    match = token.match(BIRTH_YEAR);
    if (match && addBirthYear(parseInt(match[2], 10))) {
      addGender(match[1]);
      addGender(match[3]);
      continue;
    }

    match = token.match(SHORT_BIRTH_YEAR);
    if (match) {
      const digits = match[2] ?? match[3];
      if (addBirthYear(2000 + parseInt(digits, 10))) {
        addGender(match[1] ?? match[4]);
        continue;
      }
    }

    match = token.match(BAND);
    if (match) {
      const first = 2000 + (parseInt(match[2], 10) % 100);
      const second = 2000 + (parseInt(match[3], 10) % 100);
      const board = Math.abs(first - second) === 1 ? boardAge(seasonYear - Math.max(first, second) + 1) : null;
      if (board !== null) {
        ages.add(board);
        bandSpellings(first, second).forEach((s) => spellings.add(s));
        addGender(match[1]);
        addGender(match[4]);
        continue;
      }
    }

    if (BARE_TWO_DIGIT.test(token)) {
      const asUForm = addUForm(parseInt(token, 10));
      const asBirthYear = addBirthYear(2000 + parseInt(token, 10));
      if (asUForm || asBirthYear) continue;
    }

    textTokens.push(token);
  }

  const terms: string[] = [];
  const fuzzyTerms: string[] = [];
  const cores = new Set<string>();
  for (const token of textTokens) {
    for (const part of token.split(/[-_/|]+/)) {
      const core = part.replace(NOT_LETTER_OR_DIGIT, '');
      if (core.length < 2 || part.length > MAX_TERM_LENGTH || cores.has(core) || terms.length >= MAX_TERMS) continue;
      cores.add(core);
      terms.push(part);
      if (core.length >= 3) fuzzyTerms.push(part);
    }
  }

  return {
    terms,
    fuzzyTerms,
    ageGroups: [...ages].sort((a, b) => a - b).map((age) => `u${age}`),
    ageSpellings: [...spellings],
    gender: genders.size === 1 ? [...genders][0] : null,
  };
}
