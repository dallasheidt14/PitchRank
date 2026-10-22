import 'server-only';
import { createHash } from 'node:crypto';

import type { SupabaseClient } from '@supabase/supabase-js';
import { AppError } from './errors';
import {
  fetchPredictionEvidence,
  PredictionMetadataError,
  PredictionUnavailableError,
  fetchPredictionTeam,
  resolvePredictionTeamIds,
  type PredictionTeam,
} from './matchPredictionService';
import { predictMatch, warmMatchPredictorCalibration, type MatchPrediction } from './matchPredictor';
import type { Game } from './types';
import {
  buildNetworkEvidence as buildResultEvidence,
  predictNetworkResult as predictCohortResult,
  NETWORK_RESULT_MODEL as COHORT_RESULT_MODEL,
  withoutNetworkGame as withoutResultGame,
  resampleNetworkEvidence as resampleResultEvidence,
  type NetworkEvidence as ResultEvidence,
} from './networkResultModel';
export type SeedingModel = 'legacy' | 'cohort' | 'results';

// Explicit MatchBalance policy; Compare and published rankings keep their own windows.
export const MATCHBALANCE_HISTORY_START = '2026-08-01';

export type SeedingCohorts = Record<string, Record<string, string>>;
type ResolvedTeam = Awaited<ReturnType<typeof resolvePredictionTeamIds>>;
export type SeedingTeam = PredictionTeam & {
  latest_game_date: string | null;
  prediction_game_count: number;
};

export interface SeedingPairPrediction {
  entrant_a: string;
  entrant_b: string;
  predicted_winner: 'team_a' | 'team_b' | 'draw';
  win_probability_a: number;
  win_probability_b: number;
  draw_probability: number;
  expected_score: { teamA: number; teamB: number };
  expected_margin: number;
  expected_absolute_goal_difference: number;
  blowout_4plus_probability: number;
  confidence: 'high' | 'medium' | 'low';
  confidence_score: number | null;
}

export const SEEDING_UNAVAILABLE_CODES = [
  'team_not_found',
  'no_current_rating',
  'metadata_conflict',
  'duplicate_entry',
] as const;
export type SeedingUnavailableCode = (typeof SEEDING_UNAVAILABLE_CODES)[number];

interface Unavailable {
  code: SeedingUnavailableCode;
  reason: string;
  details?: { kind: string; team_age?: number; rating_ages?: number[] };
}

export interface SeedingPredictionResult {
  schema_version: 1;
  generated_at: string;
  ratings_as_of: string | null;
  input_digests: Record<string, string>;
  model: SeedingModel;
  evidence: Record<string, unknown>;
  cohorts: Record<
    string,
    {
      teams: Record<string, SeedingTeam>;
      unavailable: Record<string, string>;
      unavailable_codes: Record<string, SeedingUnavailableCode>;
      unavailable_details: Record<string, NonNullable<Unavailable['details']>>;
      predictions: SeedingPairPrediction[];
      sensitivity?: Array<{
        omitted_game_id: string;
        kind: 'game_removal' | 'cluster_resample';
        predictions: SeedingPairPrediction[];
      }>;
    }
  >;
}

function includesTeam(game: Game, ids: Set<string>): boolean {
  return ids.has(game.home_team_master_id ?? '') || ids.has(game.away_team_master_id ?? '');
}

export function predictionRow(
  entrantA: string,
  entrantB: string,
  prediction: MatchPrediction,
  reverse = false
): SeedingPairPrediction {
  const winner = prediction.predictedWinner;
  return {
    entrant_a: entrantA,
    entrant_b: entrantB,
    predicted_winner: reverse ? (winner === 'team_a' ? 'team_b' : winner === 'team_b' ? 'team_a' : 'draw') : winner,
    win_probability_a: reverse ? prediction.winProbabilityB : prediction.winProbabilityA,
    win_probability_b: reverse ? prediction.winProbabilityA : prediction.winProbabilityB,
    draw_probability: prediction.drawProbability ?? 0,
    expected_score: reverse
      ? { teamA: prediction.expectedScore.teamB, teamB: prediction.expectedScore.teamA }
      : prediction.expectedScore,
    expected_margin: reverse ? -prediction.expectedMargin : prediction.expectedMargin,
    expected_absolute_goal_difference: prediction.expectedAbsoluteGoalDifference!,
    blowout_4plus_probability: prediction.blowout4PlusProbability!,
    confidence: prediction.confidence,
    confidence_score: prediction.confidence_score ?? null,
  };
}

function assertPrediction(prediction: MatchPrediction): void {
  for (const value of [
    prediction.winProbabilityA,
    prediction.winProbabilityB,
    prediction.drawProbability,
    prediction.blowout4PlusProbability,
    prediction.confidence_score,
  ]) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
      throw new Error('Compare returned an invalid seeding probability');
    }
  }
  if (
    !Number.isFinite(prediction.expectedMargin) ||
    !Number.isFinite(prediction.expectedAbsoluteGoalDifference) ||
    prediction.expectedAbsoluteGoalDifference! < 0 ||
    Object.values(prediction.expectedScore).some((value) => !Number.isInteger(value) || value < 0) ||
    Math.abs(prediction.winProbabilityA + prediction.winProbabilityB + prediction.drawProbability! - 1) > 1e-6
  ) {
    throw new Error('Compare returned an invalid seeding margin or score');
  }
}

/** Freeze the selected model's inputs, then evaluate every pair without shadow writes. */
export async function buildSeedingPredictions(
  supabase: SupabaseClient,
  cohorts: SeedingCohorts,
  options: { model?: SeedingModel; asOf?: string } = {}
): Promise<SeedingPredictionResult> {
  const model = options.model ?? 'legacy';
  if (!['legacy', 'cohort', 'results'].includes(model)) throw new Error('Unknown seeding model');
  await warmMatchPredictorCalibration();
  const resolvedByRequested = new Map<string, ResolvedTeam>();
  const teamByCanonical = new Map<string, PredictionTeam>();
  const unavailableByCanonical = new Map<string, Unavailable>();
  const requestedIds = [...new Set(Object.values(cohorts).flatMap((entries) => Object.values(entries)))].sort();

  // Bounded concurrency: large tournament packs do not open hundreds of requests together.
  for (let start = 0; start < requestedIds.length; start += 8) {
    await Promise.all(
      requestedIds.slice(start, start + 8).map(async (teamId) => {
        resolvedByRequested.set(teamId, await resolvePredictionTeamIds(supabase, teamId));
      })
    );
  }
  const canonicalIds = [...new Set([...resolvedByRequested.values()].map((item) => item.canonicalTeamId))];
  for (let start = 0; start < canonicalIds.length; start += 8) {
    await Promise.all(
      canonicalIds.slice(start, start + 8).map(async (teamId) => {
        try {
          const team = await fetchPredictionTeam(supabase, teamId, { strict: true, allowEmptyHistory: true });
          for (const value of Object.values(team)) {
            if (typeof value === 'number' && !Number.isFinite(value)) {
              throw new Error('Compare team input contains a non-finite value');
            }
          }
          teamByCanonical.set(teamId, team);
        } catch (error) {
          if (error instanceof AppError && error.code === 'team_not_found') {
            unavailableByCanonical.set(teamId, {
              code: 'team_not_found',
              reason: 'Confirm the club, team name, and age group before seeding.',
            });
          } else if (error instanceof AppError && error.code === 'prediction_unavailable') {
            const detail = error instanceof PredictionUnavailableError ? error.details : undefined;
            const explanation =
              detail?.reason === 'inactive'
                ? 'PitchRank marks this team inactive. Confirm its recent results before placement.'
                : detail?.reason === 'no_ranked_results'
                  ? 'Rankings do not currently include usable game history for this team. Refresh results, then run rankings and rebuild.'
                  : 'No usable current PitchRank rating is available. Check its game history, then run rankings and rebuild.';
            unavailableByCanonical.set(teamId, {
              code: 'no_current_rating',
              reason: explanation,
              details: detail,
            });
          } else if (error instanceof AppError && error.code === 'prediction_metadata_conflict') {
            unavailableByCanonical.set(teamId, {
              code: 'metadata_conflict',
              reason: `${error.message} Then rebuild matchup tiers. Your team match is saved.`,
              details: error instanceof PredictionMetadataError ? error.details : { kind: 'data_review' },
            });
          } else {
            throw error;
          }
        }
      })
    );
  }

  const allIds = [...resolvedByRequested.values()]
    .filter((item) => teamByCanonical.has(item.canonicalTeamId))
    .flatMap((item) => item.allTeamIds);
  const evidence = await fetchPredictionEvidence(supabase, allIds, options.asOf, supabase, {
    windowStart: MATCHBALANCE_HISTORY_START,
  });
  const games = evidence.games;
  // Network priors compare against a zero-game neutral reference, so aggregate
  // records do not enter them. Keep their published inputs independent of which
  // other cohorts happen to be selected in the same build.
  const opponentTeams = new Map(teamByCanonical);
  // The legacy pair predictor also reads a team's aggregate record. Replace that
  // record from the same canonical, scored fixtures rather than leaking older
  // ranking-window results into the season-only game analysis. Rating strengths
  // (PowerScore, Glicko, offense/defense and SOS) remain published baseline inputs.
  for (const [id, team] of teamByCanonical) {
    let wins = 0,
      losses = 0,
      draws = 0;
    for (const game of games) {
      const home = game.home_team_master_id === id;
      if (!home && game.away_team_master_id !== id) continue;
      const margin = (game.home_score! - game.away_score!) * (home ? 1 : -1);
      if (margin > 0) wins++;
      else if (margin < 0) losses++;
      else draws++;
    }
    const played = wins + losses + draws;
    teamByCanonical.set(id, {
      ...team,
      wins,
      losses,
      draws,
      games_played: played,
      win_percentage: played ? ((wins + draws * 0.5) / played) * 100 : null,
    });
  }
  const unknownOpponents: Record<string, string> = {};
  if (model === 'results') {
    const opponents = [...new Set(games.flatMap((g) => [g.home_team_master_id, g.away_team_master_id]))]
      .filter((id): id is string => !!id && !opponentTeams.has(id))
      .sort();
    for (let start = 0; start < opponents.length; start += 8) {
      await Promise.all(
        opponents.slice(start, start + 8).map(async (id) => {
          try {
            opponentTeams.set(id, await fetchPredictionTeam(supabase, id, { strict: true, allowEmptyHistory: true }));
          } catch (error) {
            if (
              error instanceof AppError &&
              ['team_not_found', 'prediction_unavailable', 'prediction_metadata_conflict'].includes(error.code ?? '')
            ) {
              unknownOpponents[id] = error.code!;
            } else throw error;
          }
        })
      );
    }
  }
  const ratingDates = [...teamByCanonical.values()].map((team) => team.ratings_as_of);
  const result: SeedingPredictionResult = {
    schema_version: 1,
    model,
    evidence: {},
    generated_at: new Date().toISOString(),
    // A global newest timestamp would make older cohort ratings look fresh.
    ratings_as_of: ratingDates.length && ratingDates.every(Boolean) ? (ratingDates.sort()[0] ?? null) : null,
    input_digests: {},
    cohorts: {},
  };

  for (const [cohortKey, entrants] of Object.entries(cohorts)) {
    const output: SeedingPredictionResult['cohorts'][string] = {
      teams: {},
      unavailable: {},
      unavailable_codes: {},
      unavailable_details: {},
      predictions: [],
    };
    const markUnavailable = (entrantId: string, { code, reason, details }: Unavailable) => {
      output.unavailable[entrantId] = reason;
      output.unavailable_codes[entrantId] = code;
      output.unavailable_details[entrantId] = details ?? { kind: code };
    };
    result.cohorts[cohortKey] = output;
    const canonicalCounts = new Map<string, number>();
    for (const requested of Object.values(entrants)) {
      const canonical = resolvedByRequested.get(requested)!.canonicalTeamId;
      canonicalCounts.set(canonical, (canonicalCounts.get(canonical) ?? 0) + 1);
    }
    const entrantIds = Object.keys(entrants).sort((left, right) => left.localeCompare(right));
    for (const entrantId of entrantIds) {
      const resolved = resolvedByRequested.get(entrants[entrantId])!;
      if (canonicalCounts.get(resolved.canonicalTeamId)! > 1) {
        markUnavailable(entrantId, {
          code: 'duplicate_entry',
          reason: 'Two roster entries appear to be the same team. Confirm both team matches before seeding.',
        });
        continue;
      }
      if (evidence.excluded_team_ids.includes(resolved.canonicalTeamId)) {
        markUnavailable(entrantId, {
          code: 'metadata_conflict',
          reason: 'This canonical team is excluded from ranking evidence. Resolve its identity before seeding.',
          details: { kind: 'identity_review' },
        });
        continue;
      }
      if (evidence.review_team_ids.includes(resolved.canonicalTeamId)) {
        markUnavailable(entrantId, {
          code: 'metadata_conflict',
          reason: 'Possible duplicate game records need source review. The records remain in the saved evidence.',
          details: { kind: 'game_records_review' },
        });
        continue;
      }
      const team = teamByCanonical.get(resolved.canonicalTeamId);
      if (!team) {
        markUnavailable(entrantId, unavailableByCanonical.get(resolved.canonicalTeamId)!);
        continue;
      }
      // Canonicalized fixtures include merged history under this single ID.
      const ids = new Set([resolved.canonicalTeamId]);
      const teamGames = games.filter((game) => includesTeam(game, ids));
      output.teams[entrantId] = {
        ...team,
        latest_game_date: teamGames[0]?.game_date ?? null,
        prediction_game_count: teamGames.length,
      };
    }
    const available = entrantIds.filter((entrantId) => entrantId in output.teams);
    const cohortIds = new Set(Object.values(entrants).flatMap((id) => resolvedByRequested.get(id)!.allTeamIds));
    const cohortGames = games.filter((game) => includesTeam(game, cohortIds));
    const involved = new Set(cohortGames.flatMap((g) => [g.home_team_master_id, g.away_team_master_id]));
    const frozenTeams = Object.fromEntries(
      [...opponentTeams].filter(([id]) => involved.has(id) || canonicalCounts.has(id)).sort()
    );
    const resultEvidence =
      model === 'results'
        ? buildResultEvidence(frozenTeams, cohortGames, evidence.as_of, [...canonicalCounts.keys()])
        : {};
    for (const team of Object.values(output.teams)) {
      const profile = resultEvidence[team.team_id_master];
      if (profile) Object.assign(team, { result_evidence: profile });
    }
    const scopedOmissions = evidence.omitted.filter((item) => item.team_ids.some((id) => cohortIds.has(id)));
    const rawIds = new Set([
      ...cohortGames.flatMap((g) => [g.original_home_team_id, g.original_away_team_id]),
      ...scopedOmissions.flatMap((item) => [item.record.home_team_master_id, item.record.away_team_master_id]),
    ]);
    const snapshot = {
      schema_version: 1,
      as_of: evidence.as_of,
      window_start: evidence.window_start,
      model,
      model_parameters: model === 'results' ? COHORT_RESULT_MODEL : null,
      aliases: Object.fromEntries(
        Object.entries(evidence.aliases)
          .filter(([id, canonical]) => rawIds.has(id) || cohortIds.has(canonical))
          .sort()
      ),
      entrants: entrantIds.map((id) => [id, entrants[id], resolvedByRequested.get(entrants[id])]),
      teams: output.teams,
      opponents: model === 'results' ? frozenTeams : {},
      unknown_opponents: Object.fromEntries(
        Object.entries(unknownOpponents)
          .filter(([id]) => involved.has(id))
          .sort()
      ),
      unavailable: output.unavailable_codes,
      unavailable_details: output.unavailable_details,
      games: cohortGames,
      omitted: scopedOmissions,
    };
    result.evidence[cohortKey] = { canonical_json: stableJson(snapshot) };
    result.input_digests[cohortKey] = createHash('sha256').update(stableJson(snapshot)).digest('hex');
    for (let left = 0; left < available.length; left += 1) {
      for (let right = left + 1; right < available.length; right += 1) {
        const a = available[left];
        const b = available[right];
        const ids = new Set([
          ...resolvedByRequested.get(entrants[a])!.allTeamIds,
          ...resolvedByRequested.get(entrants[b])!.allTeamIds,
        ]);
        // Filtering preserves the same stable game order returned to Compare.
        const pairGames = games.filter((game) => includesTeam(game, ids));
        const prediction =
          model === 'results'
            ? predictCohortResult(output.teams[a], output.teams[b], resultEvidence)
            : predictMatch(output.teams[a], output.teams[b], pairGames);
        assertPrediction(prediction);
        output.predictions.push(predictionRow(a, b, prediction), predictionRow(b, a, prediction, true));
      }
    }
    if (model === 'results') {
      output.sensitivity = [];
      const gameIds = [
        ...new Set(
          available
            .map((id) => resultEvidence[output.teams[id].team_id_master]?.influentialGames[0]?.game_id)
            .filter((id): id is string => !!id)
        ),
      ].sort();
      const appendVariant = (gameId: string, kind: 'game_removal' | 'cluster_resample', variant: ResultEvidence) => {
        const predictions: SeedingPairPrediction[] = [];
        for (let left = 0; left < available.length; left++)
          for (let right = left + 1; right < available.length; right++) {
            const a = available[left],
              b = available[right];
            const ta = output.teams[a],
              tb = output.teams[b];
            if (
              variant[ta.team_id_master] === resultEvidence[ta.team_id_master] &&
              variant[tb.team_id_master] === resultEvidence[tb.team_id_master]
            )
              continue;
            const prediction = predictCohortResult(ta, tb, variant);
            assertPrediction(prediction);
            predictions.push(predictionRow(a, b, prediction), predictionRow(b, a, prediction, true));
          }
        if (predictions.length) output.sensitivity!.push({ omitted_game_id: gameId, kind, predictions });
      };
      for (const gameId of gameIds) {
        appendVariant(gameId, 'game_removal', withoutResultGame(resultEvidence, gameId));
      }
      if (gameIds.length && available.length > 1) {
        for (let sample = 0; sample < COHORT_RESULT_MODEL.clusterSamples; sample++) {
          appendVariant(`cluster-${sample}`, 'cluster_resample', resampleResultEvidence(resultEvidence, sample));
        }
      }
    }
  }
  return result;
}

/** Canonical serialization prevents object insertion order from masquerading as new evidence. */
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(stableJson).join(',') + ']';
  if (value !== null && typeof value === 'object')
    return (
      '{' +
      Object.entries(value)
        .filter(([, item]) => item !== undefined)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, item]) => JSON.stringify(key) + ':' + stableJson(item))
        .join(',') +
      '}'
    );
  return JSON.stringify(value) ?? 'null';
}
