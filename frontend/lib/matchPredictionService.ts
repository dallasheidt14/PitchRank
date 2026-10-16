import 'server-only';

import type { SupabaseClient } from '@supabase/supabase-js';
import { AppError } from './errors';
import { explainMatch, type MatchExplanation } from './matchExplainer';
import { predictMatch, type MatchPrediction, warmMatchPredictorCalibration } from './matchPredictor';
import type { Game, TeamWithRanking } from './types';
import { MLS_NEXT_PROVIDER_CODES, normalizeAgeGroup } from './utils';
import { formatGender } from '@/lib/constants';
import { canonicalPredictionIds, predictionIdentityClosure } from './predictionIdentity';

export interface MatchPredictionResponse {
  teamA: {
    team_id_master: string;
    team_name: string;
    club_name: string | null;
  };
  teamB: {
    team_id_master: string;
    team_name: string;
    club_name: string | null;
  };
  prediction: MatchPrediction;
  explanation: MatchExplanation;
}

export interface MatchPredictionShadowContext {
  predictorVersion: string;
  resolvedTeamAIds: string[];
  resolvedTeamBIds: string[];
  relevantGameIds: string[];
  relevantGameCount: number;
  teamAInput: TeamWithRanking;
  teamBInput: TeamWithRanking;
}

interface MatchPredictionBuildResult {
  response: MatchPredictionResponse;
  shadowContext: MatchPredictionShadowContext;
}

export const MATCH_PREDICTION_VERSION = 'heuristic_v6_canonical_evidence_v1';

type TeamRow = {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  league: string | null;
  distinction: string | null;
  state: string | null;
  state_code: string | null;
  age_group: string | null;
  gender: string | null;
  last_scraped_at: string | null;
};

type RankingRow = {
  age?: number | string | null;
  gender?: string | null;
  rank_in_cohort_final?: number | null;
  rank_in_state_final?: number | null;
  power_score_final?: number | null;
  glicko_rating?: number | null;
  glicko_rd?: number | null;
  glicko_volatility?: number | null;
  sos_norm?: number | null;
  sos_norm_state?: number | null;
  offense_norm?: number | null;
  defense_norm?: number | null;
  wins?: number | null;
  losses?: number | null;
  draws?: number | null;
  games_played?: number | null;
};

type RankingsFullRow = {
  last_calculated?: string | null;
  status?: string | null;
  age_group?: string | number | null;
  gender?: string | null;
  rank_in_cohort_final?: number | null;
  power_score_final?: number | null;
  glicko_rating?: number | null;
  glicko_rd?: number | null;
  glicko_volatility?: number | null;
  sos_norm?: number | null;
  off_norm?: number | null;
  def_norm?: number | null;
  wins?: number | null;
  losses?: number | null;
  draws?: number | null;
  games_played?: number | null;
  same_age_games?: number | null;
  same_age_game_share?: number | null;
  same_age_unique_opponents?: number | null;
  same_age_top100_opp_count?: number | null;
  same_age_top500_opp_count?: number | null;
  same_age_avg_opp_power_adj?: number | null;
  repeat_opponent_share?: number | null;
  positive_ml_evidence_scale?: number | null;
  publication_cap_rank?: number | null;
  publication_cap_score?: number | null;
};

type PredictiveRow = {
  exp_margin?: number | null;
  exp_win_rate?: number | null;
  exp_goals_for?: number | null;
  exp_goals_against?: number | null;
};

const BASE_RANKINGS_FULL_FIELDS =
  'age_group, gender, rank_in_cohort_final, power_score_final, glicko_rating, glicko_rd, glicko_volatility, sos_norm, off_norm, def_norm, wins, losses, draws, games_played, last_calculated, status';
const OPTIONAL_RANKINGS_FULL_PREDICTION_FIELDS =
  'same_age_games, same_age_game_share, same_age_unique_opponents, same_age_top100_opp_count, same_age_top500_opp_count, same_age_avg_opp_power_adj, repeat_opponent_share, positive_ml_evidence_scale, publication_cap_rank, publication_cap_score';

function isMissingOptionalPredictionColumn(error: unknown): boolean {
  const message = String((error as { message?: string } | null)?.message ?? error ?? '').toLowerCase();
  return (
    (message.includes('column') || message.includes('schema cache') || message.includes('could not find')) &&
    (message.includes('same_age_') ||
      message.includes('positive_ml_evidence_scale') ||
      message.includes('publication_cap_'))
  );
}

function isMissingOptionalGlickoViewColumn(error: unknown, view: string): boolean {
  const detail = error as { code?: string; message?: string } | null;
  return (
    detail?.code === '42703' &&
    new RegExp(`^column ${view}\\.glicko_(rating|rd|volatility) does not exist$`).test(detail.message ?? '')
  );
}

async function fetchRankingsFullRow(supabase: SupabaseClient, teamId: string): Promise<RankingsFullRow | null> {
  const fullSelector = `${BASE_RANKINGS_FULL_FIELDS}, ${OPTIONAL_RANKINGS_FULL_PREDICTION_FIELDS}`;

  const attempt = async (selector: string) =>
    supabase.from('rankings_full').select(selector).eq('team_id', teamId).maybeSingle();

  let result = await attempt(fullSelector);
  if (result.error && isMissingOptionalPredictionColumn(result.error)) {
    result = await attempt(BASE_RANKINGS_FULL_FIELDS);
  }

  if (result.error) {
    throw result.error;
  }

  return result.data as RankingsFullRow | null;
}

function normalizeGenderCode(rawGender: string | null | undefined): 'M' | 'F' | null {
  const value = rawGender?.trim().toLowerCase();
  if (['male', 'm', 'b', 'boy', 'boys'].includes(value ?? '')) return 'M';
  if (['female', 'f', 'g', 'girl', 'girls'].includes(value ?? '')) return 'F';
  return null;
}

export const resolvePredictionTeamIds = predictionIdentityClosure;

export type PredictionTeam = TeamWithRanking & {
  ratings_as_of: string | null;
  status: string | null;
  ratings_age: number | null;
  ratings_gender: 'M' | 'F' | null;
};

export async function fetchPredictionTeam(
  supabase: SupabaseClient,
  teamId: string,
  options: { strict?: boolean; allowEmptyHistory?: boolean } = {}
): Promise<PredictionTeam> {
  const [teamResult, rankingResult, stateRankingResult, rankingsFullData, predictiveResult] = await Promise.all([
    supabase
      .from('teams')
      .select(
        'team_id_master, team_name, club_name, league, distinction, state, state_code, age_group, gender, last_scraped_at'
      )
      .eq('team_id_master', teamId)
      .maybeSingle(),
    supabase
      .from('rankings_view')
      .select(
        'age, gender, rank_in_cohort_final, power_score_final, glicko_rating, glicko_rd, glicko_volatility, sos_norm, offense_norm, defense_norm, wins, losses, draws, games_played'
      )
      .eq('team_id_master', teamId)
      .maybeSingle(),
    supabase
      .from('state_rankings_view')
      .select(
        'age, gender, rank_in_cohort_final, rank_in_state_final, power_score_final, glicko_rating, glicko_rd, glicko_volatility, sos_norm, sos_norm_state, offense_norm, defense_norm, wins, losses, draws, games_played'
      )
      .eq('team_id_master', teamId)
      .maybeSingle(),
    fetchRankingsFullRow(supabase, teamId),
    supabase
      .from('team_predictive_view')
      .select('exp_margin, exp_win_rate, exp_goals_for, exp_goals_against')
      .eq('team_id_master', teamId)
      .maybeSingle(),
  ]);

  if (teamResult.error) {
    throw teamResult.error;
  }
  if (options.strict) {
    // Legacy ranking views omit Glicko columns. In that schema Compare uses
    // rankings_full below; preserve that exact path while surfacing read failures.
    for (const [view, result] of [
      ['rankings_view', rankingResult],
      ['state_rankings_view', stateRankingResult],
    ] as const) {
      if (result.error && !isMissingOptionalGlickoViewColumn(result.error, view)) throw result.error;
    }
    // This supplemental view is absent in the live schema. Compare already
    // supplies null exp_* inputs there; distinguish that known optional absence
    // from an actual failed read (auth, network, timeout, or a broken query).
    if (predictiveResult.error && predictiveResult.error.code !== 'PGRST205') throw predictiveResult.error;
  }

  const teamData = teamResult.data as TeamRow | null;
  const rankingData = rankingResult.data as RankingRow | null;
  const stateRankingData = stateRankingResult.data as RankingRow | null;
  const predictiveData = predictiveResult.data as PredictiveRow | null;

  if (!teamData) {
    throw new AppError('Team not found', 'team_not_found', 404);
  }

  const ratingsAge =
    normalizeAgeGroup(rankingData?.age) ??
    normalizeAgeGroup(stateRankingData?.age) ??
    normalizeAgeGroup(rankingsFullData?.age_group);
  const age = normalizeAgeGroup(teamData.age_group);
  const gender = normalizeGenderCode(teamData.gender);
  const ratingsGender =
    normalizeGenderCode(rankingData?.gender) ??
    normalizeGenderCode(stateRankingData?.gender) ??
    normalizeGenderCode(rankingsFullData?.gender);
  if (age == null || gender == null) {
    throw new AppError(
      'The PitchRank team record is missing a valid age or gender. Correct the team record before predicting.',
      'prediction_metadata_conflict',
      422
    );
  }
  // Ratings may predate a profile correction. Do not mix cohorts in one prediction.
  const conflicts: string[] = [];
  for (const [recordedAge, recordedGender] of [
    [normalizeAgeGroup(rankingData?.age), normalizeGenderCode(rankingData?.gender)],
    [normalizeAgeGroup(stateRankingData?.age), normalizeGenderCode(stateRankingData?.gender)],
    [normalizeAgeGroup(rankingsFullData?.age_group), normalizeGenderCode(rankingsFullData?.gender)],
  ] as const) {
    if (recordedAge != null && recordedAge !== age) {
      conflicts.push(`team record U${age}, calculated ratings U${recordedAge}`);
    }
    if (recordedGender != null && recordedGender !== gender) {
      conflicts.push(`team record ${formatGender(gender ?? '')}, calculated ratings ${formatGender(recordedGender)}`);
    }
  }
  if (conflicts.length) {
    throw new AppError(
      `PitchRank data needs updating: ${[...new Set(conflicts)].join('; ')}. Recalculate rankings before predicting.`,
      'prediction_metadata_conflict',
      422
    );
  }

  const wins = rankingData?.wins ?? stateRankingData?.wins ?? rankingsFullData?.wins ?? 0;
  const losses = rankingData?.losses ?? stateRankingData?.losses ?? rankingsFullData?.losses ?? 0;
  const draws = rankingData?.draws ?? stateRankingData?.draws ?? rankingsFullData?.draws ?? 0;
  const gamesPlayed =
    rankingData?.games_played ?? stateRankingData?.games_played ?? rankingsFullData?.games_played ?? 0;
  const computedWinPercentage = gamesPlayed > 0 ? ((wins + draws * 0.5) / gamesPlayed) * 100 : null;

  const mlsNextAliasResult = await supabase
    .from('team_alias_map')
    .select('id, providers!inner(code)')
    .eq('team_id_master', teamData.team_id_master)
    .in('providers.code', MLS_NEXT_PROVIDER_CODES)
    .limit(1);
  if (options.strict && mlsNextAliasResult.error) throw mlsNextAliasResult.error;

  const team: PredictionTeam = {
    ratings_as_of: rankingsFullData?.last_calculated ?? null,
    ratings_age: ratingsAge,
    ratings_gender: ratingsGender,
    status: rankingsFullData?.status ?? null,
    team_id_master: teamData.team_id_master,
    team_name: teamData.team_name,
    club_name: teamData.club_name,
    league: teamData.league ?? null,
    distinction: teamData.distinction ?? null,
    has_modular11_alias: (mlsNextAliasResult.data?.length ?? 0) > 0,
    state: teamData.state ?? teamData.state_code,
    age,
    gender,
    rank_in_cohort_final:
      rankingData?.rank_in_cohort_final ??
      stateRankingData?.rank_in_cohort_final ??
      rankingsFullData?.rank_in_cohort_final ??
      null,
    rank_in_state_final: stateRankingData?.rank_in_state_final ?? null,
    power_score_final:
      rankingData?.power_score_final ??
      stateRankingData?.power_score_final ??
      rankingsFullData?.power_score_final ??
      null,
    glicko_rating:
      rankingData?.glicko_rating ?? stateRankingData?.glicko_rating ?? rankingsFullData?.glicko_rating ?? null,
    glicko_rd: rankingData?.glicko_rd ?? stateRankingData?.glicko_rd ?? rankingsFullData?.glicko_rd ?? null,
    glicko_volatility:
      rankingData?.glicko_volatility ??
      stateRankingData?.glicko_volatility ??
      rankingsFullData?.glicko_volatility ??
      null,
    sos_norm: rankingData?.sos_norm ?? stateRankingData?.sos_norm ?? rankingsFullData?.sos_norm ?? null,
    sos_norm_state: stateRankingData?.sos_norm_state ?? rankingsFullData?.sos_norm ?? null,
    offense_norm: rankingData?.offense_norm ?? stateRankingData?.offense_norm ?? rankingsFullData?.off_norm ?? null,
    defense_norm: rankingData?.defense_norm ?? stateRankingData?.defense_norm ?? rankingsFullData?.def_norm ?? null,
    same_age_games: rankingsFullData?.same_age_games ?? null,
    same_age_game_share: rankingsFullData?.same_age_game_share ?? null,
    same_age_unique_opponents: rankingsFullData?.same_age_unique_opponents ?? null,
    same_age_top100_opp_count: rankingsFullData?.same_age_top100_opp_count ?? null,
    same_age_top500_opp_count: rankingsFullData?.same_age_top500_opp_count ?? null,
    same_age_avg_opp_power_adj: rankingsFullData?.same_age_avg_opp_power_adj ?? null,
    repeat_opponent_share: rankingsFullData?.repeat_opponent_share ?? null,
    positive_ml_evidence_scale: rankingsFullData?.positive_ml_evidence_scale ?? null,
    publication_cap_rank: rankingsFullData?.publication_cap_rank ?? null,
    publication_cap_score: rankingsFullData?.publication_cap_score ?? null,
    wins,
    losses,
    draws,
    games_played: gamesPlayed,
    last_scraped_at: teamData.last_scraped_at,
    win_percentage: computedWinPercentage,
    exp_margin: predictiveData?.exp_margin ?? null,
    exp_win_rate: predictiveData?.exp_win_rate ?? null,
    exp_goals_for: predictiveData?.exp_goals_for ?? null,
    exp_goals_against: predictiveData?.exp_goals_against ?? null,
  };

  if (team.power_score_final == null || (!options.allowEmptyHistory && team.games_played <= 0)) {
    throw new AppError(
      'Prediction unavailable. Match predictions rely on current ranking data for both teams.',
      'prediction_unavailable',
      422
    );
  }

  return team;
}

export async function fetchPredictionEvidence(
  supabase: SupabaseClient,
  teamIds: string[],
  asOf = new Date().toISOString().slice(0, 10),
  exclusionsClient: SupabaseClient = supabase
) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf) || !Number.isFinite(Date.parse(asOf)))
    throw new Error('Invalid prediction date');
  const cutoffDate = new Date(asOf + 'T00:00:00Z');
  cutoffDate.setUTCDate(cutoffDate.getUTCDate() - 365);

  // Both Compare and Seeding use this stable order, including same-day games.
  // Page below the local PostgREST cap and keep the complete filter below its
  // 100-ID URI safeguard. Each team ID appears once per home/away clause.
  const wanted = [...new Set(teamIds)].sort();
  const games = new Map<string, Game>();
  const pageSize = 1000;
  const gameIdBatchSize = 50;
  for (let start = 0; start < wanted.length; start += gameIdBatchSize) {
    const batch = wanted.slice(start, start + gameIdBatchSize);
    for (let offset = 0; ; offset += pageSize) {
      const { data, error } = await supabase
        .from('games')
        .select(
          'id, game_date, home_team_master_id, away_team_master_id, home_score, away_score, competition, division_name, event_name, ml_overperformance, provider_id, source_url, scraped_at'
        )
        .gte('game_date', cutoffDate.toISOString().split('T')[0])
        .lte('game_date', asOf)
        .not('home_score', 'is', null)
        .not('away_score', 'is', null)
        .or(`home_team_master_id.in.(${batch.join(',')}),away_team_master_id.in.(${batch.join(',')})`)
        .eq('is_excluded', false)
        .order('game_date', { ascending: false })
        .order('id', { ascending: true })
        .range(offset, offset + pageSize - 1);
      if (error) throw error;
      const rows = (data ?? []) as Game[];
      for (const game of rows) games.set(game.id, game);
      if (rows.length < pageSize) break;
    }
  }

  const excludedIds: string[] = [];
  for (let offset = 0; ; offset += 1000) {
    const { data, error } = await exclusionsClient
      .from('team_ranking_exclusions')
      .select('team_id_master')
      .order('team_id_master', { ascending: true })
      .range(offset, offset + 999);
    if (error) throw error;
    excludedIds.push(...(data ?? []).map((row) => row.team_id_master));
    if ((data?.length ?? 0) < 1000) break;
  }
  const identities = await canonicalPredictionIds(supabase, [
    ...teamIds,
    ...excludedIds,
    ...[...games.values()]
      .flatMap((game) => [game.home_team_master_id, game.away_team_master_id])
      .filter((id): id is string => !!id),
  ]);
  const excluded = new Set(excludedIds.map((id) => identities.get(id) ?? id));
  const omitted: Array<{ game_id: string; reason: string; team_ids: string[]; record: Game }> = [];
  const evidence: Array<Game & { original_home_team_id: string | null; original_away_team_id: string | null }> = [];
  const seen = new Map<string, Game[]>();
  const ambiguous = new Set<string>();
  for (const game of [...games.values()].sort(comparePredictionGames)) {
    const home = identities.get(game.home_team_master_id ?? '') ?? game.home_team_master_id;
    const away = identities.get(game.away_team_master_id ?? '') ?? game.away_team_master_id;
    let reason = '';
    if (game.is_excluded || excluded.has(home ?? '') || excluded.has(away ?? '')) reason = 'excluded';
    else if (!home || !away || home === away) reason = 'unresolved_or_self_match';
    else if (game.game_date > asOf || game.game_date < cutoffDate.toISOString().slice(0, 10)) reason = 'outside_window';
    else if (
      ![game.home_score, game.away_score].every(
        (value) => typeof value === 'number' && Number.isInteger(value) && value >= 0
      )
    )
      reason = 'invalid_score';
    // Date, score and event cannot prove that two provider records are one match.
    // Quarantine ambiguous copies for source review; keep ordinary repeat games.
    const sides = [
      [home, game.home_score],
      [away, game.away_score],
    ].sort((a, b) => String(a[0]).localeCompare(String(b[0])));
    const signature = JSON.stringify([game.game_date, sides, game.event_name ?? game.competition ?? null]);
    const priorGames = seen.get(signature) ?? [];
    const conflicts = priorGames.filter((prior) => {
      const first = sourceFixtureIdentity(prior),
        second = sourceFixtureIdentity(game);
      if (first && second && first.namespace === second.namespace && first.id !== second.id) return false;
      return (
        ambiguous.has(prior.id) ||
        [prior.home_team_master_id, prior.away_team_master_id].sort().join('|') !==
          [game.home_team_master_id, game.away_team_master_id].sort().join('|') ||
        (prior.provider_id && game.provider_id && prior.provider_id !== game.provider_id)
      );
    });
    if (!reason && conflicts.length) {
      reason = 'ambiguous_duplicate_fixture';
      ambiguous.add(game.id);
      for (const prior of conflicts) {
        ambiguous.add(prior.id);
        const index = evidence.findIndex((row) => row.id === prior.id);
        if (index >= 0) {
          evidence.splice(index, 1);
          omitted.push({ game_id: prior.id, reason, team_ids: [home!, away!], record: prior });
        }
      }
    }
    if (reason) {
      if (reason === 'ambiguous_duplicate_fixture') seen.set(signature, [...priorGames, game]);
      omitted.push({
        game_id: game.id,
        reason,
        team_ids: [home, away].filter((id): id is string => !!id),
        record: game,
      });
      continue;
    }
    seen.set(signature, [...priorGames, game]);
    evidence.push({
      ...game,
      home_team_master_id: home,
      away_team_master_id: away,
      original_home_team_id: game.home_team_master_id,
      original_away_team_id: game.away_team_master_id,
      result: game.result ?? null,
      competition: game.competition ?? null,
      division_name: game.division_name ?? null,
      event_name: game.event_name ?? null,
      venue: game.venue ?? null,
      provider_id: game.provider_id ?? null,
      source_url: game.source_url ?? null,
      scraped_at: game.scraped_at ?? null,
      created_at: game.created_at ?? '',
      ml_overperformance: game.ml_overperformance ?? null,
      is_excluded: false,
      home_provider_id: game.home_provider_id ?? '',
      away_provider_id: game.away_provider_id ?? '',
    });
  }
  const involved = new Set([
    ...teamIds,
    ...[...games.values()]
      .flatMap((g) => [g.home_team_master_id, g.away_team_master_id])
      .filter((id): id is string => !!id),
  ]);
  return {
    schema_version: 1,
    as_of: asOf,
    window_start: cutoffDate.toISOString().slice(0, 10),
    games: evidence,
    aliases: Object.fromEntries([...identities].filter(([id]) => involved.has(id)).sort()),
    omitted,
    review_team_ids: [
      ...new Set(omitted.filter((row) => row.reason === 'ambiguous_duplicate_fixture').flatMap((row) => row.team_ids)),
    ].sort(),
    excluded_team_ids: [...excluded].filter((id) => [...involved].some((raw) => identities.get(raw) === id)).sort(),
  };
}

function sourceFixtureIdentity(game: Game): { namespace: string; id: string } | null {
  if (!game.provider_id || !game.source_url) return null;
  try {
    const url = new URL(game.source_url);
    const fixtureId = /^(?:\d+|[a-f0-9]{8}-[a-f0-9-]{27})$/i;
    for (const [key, value] of url.searchParams) {
      if (/^(?:game|match|fixture)_?id$/i.test(key) && fixtureId.test(value)) {
        return {
          namespace: `${game.provider_id}|${url.origin}${url.pathname}|${key.toLowerCase()}`,
          id: value.toLowerCase(),
        };
      }
    }
    const match = url.pathname.match(/^(.*\/(?:games?|match(?:es)?|fixtures?))\/([^/]+)\/?$/i);
    return match && fixtureId.test(match[2])
      ? { namespace: `${game.provider_id}|${url.origin}${match[1]}`, id: match[2].toLowerCase() }
      : null;
  } catch {
    return null;
  }
}

export async function fetchPredictionGames(
  supabase: SupabaseClient,
  teamIds: string[],
  asOf?: string
): Promise<Game[]> {
  return (await fetchPredictionEvidence(supabase, teamIds, asOf)).games;
}

export function comparePredictionGames(left: Game, right: Game): number {
  if (left.game_date !== right.game_date) return left.game_date > right.game_date ? -1 : 1;
  return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
}

export async function buildMatchPrediction(
  supabase: SupabaseClient,
  teamAId: string,
  teamBId: string
): Promise<MatchPredictionResponse> {
  const result = await buildMatchPredictionWithShadowContext(supabase, teamAId, teamBId);
  return result.response;
}

export async function buildMatchPredictionWithShadowContext(
  supabase: SupabaseClient,
  teamAId: string,
  teamBId: string,
  exclusionsClient: SupabaseClient = supabase
): Promise<MatchPredictionBuildResult> {
  await warmMatchPredictorCalibration();

  const [resolvedTeamA, resolvedTeamB] = await Promise.all([
    resolvePredictionTeamIds(supabase, teamAId),
    resolvePredictionTeamIds(supabase, teamBId),
  ]);

  if (resolvedTeamA.canonicalTeamId === resolvedTeamB.canonicalTeamId) {
    throw new AppError('Please choose two different teams.', 'same_team', 400);
  }

  const [teamA, teamB] = await Promise.all([
    fetchPredictionTeam(supabase, resolvedTeamA.canonicalTeamId),
    fetchPredictionTeam(supabase, resolvedTeamB.canonicalTeamId),
  ]);

  const evidence = await fetchPredictionEvidence(
    supabase,
    [...new Set([...resolvedTeamA.allTeamIds, ...resolvedTeamB.allTeamIds])],
    undefined,
    exclusionsClient
  );

  if (
    [teamAId, teamBId, resolvedTeamA.canonicalTeamId, resolvedTeamB.canonicalTeamId].some((id) =>
      evidence.excluded_team_ids.includes(id)
    )
  ) {
    throw new AppError('A selected team is excluded from ranking evidence.', 'prediction_unavailable', 422);
  }
  const games = evidence.games;
  if (
    [resolvedTeamA.canonicalTeamId, resolvedTeamB.canonicalTeamId].some((id) => evidence.review_team_ids.includes(id))
  ) {
    throw new AppError(
      'Possible duplicate game records need source review before predicting.',
      'prediction_unavailable',
      422
    );
  }
  const prediction = predictMatch(teamA, teamB, games);
  const explanation = explainMatch(teamA, teamB, prediction);

  return {
    response: {
      teamA: {
        team_id_master: teamA.team_id_master,
        team_name: teamA.team_name,
        club_name: teamA.club_name,
      },
      teamB: {
        team_id_master: teamB.team_id_master,
        team_name: teamB.team_name,
        club_name: teamB.club_name,
      },
      prediction,
      explanation,
    },
    shadowContext: {
      predictorVersion: MATCH_PREDICTION_VERSION,
      resolvedTeamAIds: resolvedTeamA.allTeamIds,
      resolvedTeamBIds: resolvedTeamB.allTeamIds,
      relevantGameIds: games.map((game) => game.id),
      relevantGameCount: games.length,
      teamAInput: teamA,
      teamBInput: teamB,
    },
  };
}
