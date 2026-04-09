import 'server-only';

import type { SupabaseClient } from '@supabase/supabase-js';
import { AppError } from './errors';
import { explainMatch, type MatchExplanation } from './matchExplainer';
import { predictMatch, type MatchPrediction, warmMatchPredictorCalibration } from './matchPredictor';
import type { Game, TeamWithRanking } from './types';
import { normalizeAgeGroup } from './utils';

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

export interface MatchPredictionBuildResult {
  response: MatchPredictionResponse;
  shadowContext: MatchPredictionShadowContext;
}

export const MATCH_PREDICTION_VERSION = 'heuristic_v3_shadow_ready';

type TeamRow = {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
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

type MergeRow = {
  deprecated_team_id: string;
};

const BASE_RANKINGS_FULL_FIELDS =
  'age_group, gender, rank_in_cohort_final, power_score_final, glicko_rating, glicko_rd, glicko_volatility, sos_norm, off_norm, def_norm, wins, losses, draws, games_played';
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

function normalizeGenderCode(rawGender: string | null | undefined): 'M' | 'F' | 'B' | 'G' {
  if (rawGender === 'Male' || rawGender === 'M' || rawGender === 'B' || rawGender === 'Boys') return 'M';
  if (rawGender === 'Female' || rawGender === 'F' || rawGender === 'G' || rawGender === 'Girls') return 'F';
  return 'M';
}

async function resolveCanonicalTeamId(supabase: SupabaseClient, teamId: string): Promise<string> {
  const { data, error } = await supabase
    .from('team_merge_map')
    .select('canonical_team_id')
    .eq('deprecated_team_id', teamId)
    .maybeSingle();

  if (error) {
    throw error;
  }

  return data?.canonical_team_id ?? teamId;
}

async function resolvePredictionTeamIds(
  supabase: SupabaseClient,
  teamId: string
): Promise<{ canonicalTeamId: string; allTeamIds: string[] }> {
  const canonicalTeamId = await resolveCanonicalTeamId(supabase, teamId);
  const { data, error } = await supabase
    .from('team_merge_map')
    .select('deprecated_team_id')
    .eq('canonical_team_id', canonicalTeamId);

  if (error) {
    throw error;
  }

  const allTeamIds = [canonicalTeamId];
  (data as MergeRow[] | null)?.forEach((row) => {
    if (row.deprecated_team_id) {
      allTeamIds.push(row.deprecated_team_id);
    }
  });

  return {
    canonicalTeamId,
    allTeamIds: [...new Set(allTeamIds)],
  };
}

async function fetchPredictionTeam(supabase: SupabaseClient, teamId: string): Promise<TeamWithRanking> {
  const [teamResult, rankingResult, stateRankingResult, rankingsFullData, predictiveResult] = await Promise.all([
    supabase
      .from('teams')
      .select('team_id_master, team_name, club_name, state, state_code, age_group, gender, last_scraped_at')
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

  const teamData = teamResult.data as TeamRow | null;
  const rankingData = rankingResult.data as RankingRow | null;
  const stateRankingData = stateRankingResult.data as RankingRow | null;
  const predictiveData = predictiveResult.data as PredictiveRow | null;

  if (!teamData) {
    throw new AppError('Team not found', 'team_not_found', 404);
  }

  const age =
    normalizeAgeGroup(rankingData?.age) ??
    normalizeAgeGroup(stateRankingData?.age) ??
    normalizeAgeGroup(rankingsFullData?.age_group) ??
    normalizeAgeGroup(teamData.age_group);

  const wins = rankingData?.wins ?? stateRankingData?.wins ?? rankingsFullData?.wins ?? 0;
  const losses = rankingData?.losses ?? stateRankingData?.losses ?? rankingsFullData?.losses ?? 0;
  const draws = rankingData?.draws ?? stateRankingData?.draws ?? rankingsFullData?.draws ?? 0;
  const gamesPlayed =
    rankingData?.games_played ?? stateRankingData?.games_played ?? rankingsFullData?.games_played ?? 0;
  const computedWinPercentage = gamesPlayed > 0 ? ((wins + draws * 0.5) / gamesPlayed) * 100 : null;

  const team: TeamWithRanking = {
    team_id_master: teamData.team_id_master,
    team_name: teamData.team_name,
    club_name: teamData.club_name,
    state: teamData.state ?? teamData.state_code,
    age,
    gender: normalizeGenderCode(
      rankingData?.gender ?? stateRankingData?.gender ?? rankingsFullData?.gender ?? teamData.gender
    ),
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

  if (team.power_score_final == null || team.games_played <= 0) {
    throw new AppError(
      'Prediction unavailable. Match predictions rely on current ranking data for both teams.',
      'prediction_unavailable',
      422
    );
  }

  return team;
}

async function fetchPredictionGames(supabase: SupabaseClient, teamIds: string[]): Promise<Game[]> {
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - 365);

  const { data, error } = await supabase
    .from('games')
    .select(
      'id, game_date, home_team_master_id, away_team_master_id, home_score, away_score, competition, division_name, event_name, ml_overperformance'
    )
    .gte('game_date', cutoffDate.toISOString().split('T')[0])
    .not('home_score', 'is', null)
    .not('away_score', 'is', null)
    .or(`home_team_master_id.in.(${teamIds.join(',')}),away_team_master_id.in.(${teamIds.join(',')})`)
    .eq('is_excluded', false)
    .order('game_date', { ascending: false });

  if (error) {
    throw error;
  }

  return ((data ?? []) as Game[]).map((game) => ({
    ...game,
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
    is_excluded: game.is_excluded ?? false,
    home_provider_id: game.home_provider_id ?? '',
    away_provider_id: game.away_provider_id ?? '',
  }));
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
  teamBId: string
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

  const games = await fetchPredictionGames(supabase, [
    ...new Set([...resolvedTeamA.allTeamIds, ...resolvedTeamB.allTeamIds]),
  ]);

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
