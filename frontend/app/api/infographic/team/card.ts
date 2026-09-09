import { formatGender, US_STATES } from '@/lib/constants';
import { teamDisplayName } from '@/lib/utils';
import { OSWALD_CHAR_RATIO } from '../_shared/layout';
import { formatRecord, formatScore } from '../_shared/theme';

// The name block's box on the card: the right column's content width, and the height it
// can take before it starts pushing the cohort chip and the stat rail off the canvas.
const NAME_WIDTH = 648;
const NAME_MAX_HEIGHT = 250;
const NAME_LINE_HEIGHT = 1.04;
const NAME_SIZES = [82, 72, 62, 54, 46, 40];

/**
 * The largest size at which a registered name still fits its box.
 *
 * Youth team names run long — "Columbia Youth Soccer Association - Columbia Youth Soccer
 * Association CYSA 2012 Stingers-Live Oak" is a real one — and at a fixed 82px that name
 * both clips on the right and shoves the stat rail off the bottom of the card.
 */
export function fitNameSize(name: string): number {
  const fits = NAME_SIZES.find((size) => {
    const charsPerLine = Math.max(1, Math.floor(NAME_WIDTH / (size * OSWALD_CHAR_RATIO)));
    const lines = Math.ceil(name.length / charsPerLine);
    return lines * size * NAME_LINE_HEIGHT <= NAME_MAX_HEIGHT;
  });
  return fits ?? NAME_SIZES[NAME_SIZES.length - 1];
}

export interface TeamCardRow {
  team_name: string;
  club_name: string | null;
  league: string | null;
  distinction: string | null;
  state_code: string | null;
  age_group: string | null;
  gender: string | null;
}

export interface TeamCardRanking {
  rank_in_cohort_final: number | null;
  power_score_final: number | null;
  total_wins: number | null;
  total_losses: number | null;
  total_draws: number | null;
}

export interface TeamCard {
  hero: string;
  heroLabel: string;
  displayName: string;
  nameSize: number;
  subtitle: string;
  cohort: string | null;
  record: string;
  nationalRank: string;
  powerScore: string;
  ranked: boolean;
}

function stateName(code: string | null): string | null {
  if (!code) return null;
  return US_STATES.find((s) => s.code === code.toLowerCase())?.name ?? code.toUpperCase();
}

function cohortLabel(ageGroup: string | null, gender: string | null): string | null {
  if (!ageGroup) return null;
  const side = gender ? formatGender(gender) : 'Unknown';
  if (side === 'Unknown') return ageGroup.toUpperCase();
  return `${ageGroup.toUpperCase()} ${side.toUpperCase()}`;
}

/**
 * The view model behind the team share card.
 *
 * The hero is the state rank, then the national rank, then the record. A parent shares this
 * into a team chat, and the state rank is both the number they quote and the one more teams
 * look good on; the record is the last resort so an unranked team still gets a real card.
 * Returning a card for every team is the point — a 404 here drops the link preview back to a
 * bare URL, which is the failure this route exists to fix.
 */
export function buildTeamCard(row: TeamCardRow, ranking: TeamCardRanking | null, stateRank: number | null): TeamCard {
  const state = stateName(row.state_code);
  const record = formatRecord(ranking?.total_wins ?? 0, ranking?.total_losses ?? 0, ranking?.total_draws ?? 0);
  const nationalRank = ranking?.rank_in_cohort_final ?? null;

  let hero: string;
  let heroLabel: string;
  if (stateRank != null && state) {
    hero = `#${stateRank}`;
    heroLabel = `IN ${state.toUpperCase()}`;
  } else if (nationalRank != null) {
    hero = `#${nationalRank}`;
    heroLabel = 'NATIONALLY';
  } else {
    hero = record;
    heroLabel = 'RECORD';
  }

  const displayName = teamDisplayName(row).toUpperCase();

  return {
    hero,
    heroLabel,
    displayName,
    nameSize: fitNameSize(displayName),
    subtitle: [row.club_name, state].filter(Boolean).join(' · '),
    cohort: cohortLabel(row.age_group, row.gender),
    record,
    nationalRank: nationalRank != null ? `#${nationalRank}` : '--',
    powerScore: formatScore(ranking?.power_score_final),
    ranked: stateRank != null || nationalRank != null,
  };
}
