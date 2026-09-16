import 'server-only';

import type { SupabaseClient } from '@supabase/supabase-js';
import { AppError } from './errors';
import {
  fetchPredictionGames,
  fetchPredictionTeam,
  resolvePredictionTeamIds,
  type PredictionTeam,
} from './matchPredictionService';
import { predictMatch, warmMatchPredictorCalibration, type MatchPrediction } from './matchPredictor';
import type { Game } from './types';

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

export interface SeedingPredictionResult {
  schema_version: 1;
  generated_at: string;
  ratings_as_of: string | null;
  cohorts: Record<
    string,
    {
      teams: Record<string, SeedingTeam>;
      unavailable: Record<string, string>;
      predictions: SeedingPairPrediction[];
    }
  >;
}

function includesTeam(game: Game, ids: Set<string>): boolean {
  return ids.has(game.home_team_master_id ?? '') || ids.has(game.away_team_master_id ?? '');
}

function predictionRow(
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

/** Read the exact Compare inputs once, then evaluate every pair without shadow writes. */
export async function buildSeedingPredictions(
  supabase: SupabaseClient,
  cohorts: SeedingCohorts
): Promise<SeedingPredictionResult> {
  await warmMatchPredictorCalibration();
  const resolvedByRequested = new Map<string, ResolvedTeam>();
  const teamByCanonical = new Map<string, PredictionTeam>();
  const unavailableByCanonical = new Map<string, string>();
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
          const team = await fetchPredictionTeam(supabase, teamId, { strict: true });
          if (team.rank_in_cohort_final == null) {
            unavailableByCanonical.set(teamId, 'Limited recent results. Use club input or recent scores.');
          } else {
            for (const value of Object.values(team)) {
              if (typeof value === 'number' && !Number.isFinite(value)) {
                throw new Error('Compare team input contains a non-finite value');
              }
            }
            teamByCanonical.set(teamId, team);
          }
        } catch (error) {
          if (error instanceof AppError && error.code === 'team_not_found') {
            unavailableByCanonical.set(teamId, 'Confirm the club, team name, and age group before seeding.');
          } else if (error instanceof AppError && error.code === 'prediction_unavailable') {
            unavailableByCanonical.set(teamId, 'Limited recent results. Use club input or recent scores.');
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
  const games = await fetchPredictionGames(supabase, allIds);
  const ratingDates = [...teamByCanonical.values()].map((team) => team.ratings_as_of);
  const result: SeedingPredictionResult = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    // A global newest timestamp would make older cohort ratings look fresh.
    ratings_as_of: ratingDates.length && ratingDates.every(Boolean) ? (ratingDates.sort()[0] ?? null) : null,
    cohorts: {},
  };

  for (const [cohortKey, entrants] of Object.entries(cohorts)) {
    const output: SeedingPredictionResult['cohorts'][string] = { teams: {}, unavailable: {}, predictions: [] };
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
        output.unavailable[entrantId] =
          'Two roster entries appear to be the same team. Confirm both team matches before seeding.';
        continue;
      }
      const team = teamByCanonical.get(resolved.canonicalTeamId);
      if (!team) {
        output.unavailable[entrantId] = unavailableByCanonical.get(resolved.canonicalTeamId)!;
        continue;
      }
      // Compare currently builds recent profiles from the canonical ID only.
      // Merged-ID history remains in the exact pair input, but must not inflate
      // our evidence count or make an old canonical profile look recently played.
      const ids = new Set([resolved.canonicalTeamId]);
      const teamGames = games.filter((game) => includesTeam(game, ids));
      if (!teamGames.length) {
        output.unavailable[entrantId] = 'Limited recent results. Use club input or recent scores.';
        continue;
      }
      output.teams[entrantId] = {
        ...team,
        latest_game_date: teamGames[0]?.game_date ?? null,
        prediction_game_count: teamGames.length,
      };
    }
    const available = entrantIds.filter((entrantId) => entrantId in output.teams);
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
        const prediction = predictMatch(output.teams[a], output.teams[b], pairGames);
        assertPrediction(prediction);
        output.predictions.push(predictionRow(a, b, prediction), predictionRow(b, a, prediction, true));
      }
    }
  }
  return result;
}
