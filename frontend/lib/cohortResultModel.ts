/** Experimental tournament model. Constants are versioned hypotheses, not fitted claims.
 * Published ratings are immutable priors; scored games supply shrunk corrections.
 */
import { predictMatch, type MatchPrediction } from './matchPredictor';
import type { Game, TeamWithRanking } from './types';

export const COHORT_RESULT_MODEL = {
  version: 'opponent_adjusted_results_v1',
  halfLifeDays: 90,
  marginCap: 4,
  priorWeight: 5,
  previousSeasonWeight: 0.5,
  clusterSamples: 12,
  clusterSeed: 20261016,
  status: 'preview_unvalidated',
} as const;

const clip = (value: number, bound: number) => Math.max(-bound, Math.min(bound, value));
export type ResultEvidence = ReturnType<typeof buildResultEvidence>;

type Observation = {
  game_id: string;
  opponent_id: string;
  date: string;
  margin: number;
  expected_margin: number;
  residual: number;
  weight: number;
  raw_weight: number;
  opponent_name: string;
  event: string | null;
};

function resultProfile(observations: Observation[], unknownOpponentGames: number) {
  const rows = observations.map((row) => ({ ...row }));
  const weights = new Map<string, number>();
  rows.forEach((row) => weights.set(row.opponent_id, (weights.get(row.opponent_id) ?? 0) + row.raw_weight));
  rows.forEach((row) => {
    row.weight = row.raw_weight / Math.max(1, weights.get(row.opponent_id)!);
  });
  const support = rows.reduce((sum, row) => sum + row.weight, 0);
  return {
    correction:
      rows.reduce((sum, row) => sum + row.weight * row.residual, 0) / (support + COHORT_RESULT_MODEL.priorWeight),
    effectiveOpponentWeight: support,
    games: rows.length,
    unknownOpponentGames,
    limited: support < 3,
    influentialGames: rows.sort(
      (a, b) => Math.abs(b.weight * b.residual) - Math.abs(a.weight * a.residual) || a.game_id.localeCompare(b.game_id)
    ),
  };
}

export function buildResultEvidence(teams: Record<string, TeamWithRanking>, games: Game[], asOf: string) {
  const end = Date.parse(asOf + 'T00:00:00Z');
  const date = new Date(end);
  const seasonStart = Date.UTC(date.getUTCFullYear() - (date.getUTCMonth() < 7 ? 1 : 0), 7, 1);
  const profiles: Record<string, ReturnType<typeof resultProfile>> = {};
  for (const [id, team] of Object.entries(teams)) {
    const rows = games.filter((g) => g.home_team_master_id === id || g.away_team_master_id === id);
    const evidence = [];
    let unknown = 0;
    for (const game of rows) {
      const home = game.home_team_master_id === id;
      const opponentId = (home ? game.away_team_master_id : game.home_team_master_id) ?? '';
      const opponent = teams[opponentId];
      if (!opponent) {
        unknown++;
        continue;
      }
      const played = Date.parse(game.game_date.slice(0, 10) + 'T00:00:00Z');
      if (!Number.isFinite(played) || played > end || end - played > 365 * 86400000) continue;
      if (game.home_score == null || game.away_score == null || game.is_excluded) continue;
      const margin = (home ? 1 : -1) * (game.home_score - game.away_score);
      // The existing prior supplies its age-aware matchup scale. A younger team is
      // never demoted simply for playing up, and league names confer no bonus.
      const expected = predictMatch(team, opponent, []).expectedMargin;
      const residual = clip(margin, COHORT_RESULT_MODEL.marginCap) - clip(expected, COHORT_RESULT_MODEL.marginCap);
      const weight =
        Math.pow(0.5, (end - played) / 86400000 / COHORT_RESULT_MODEL.halfLifeDays) *
        (played < seasonStart ? COHORT_RESULT_MODEL.previousSeasonWeight : 1);
      evidence.push({
        game_id: game.id,
        opponent_id: opponentId,
        date: game.game_date,
        margin,
        expected_margin: expected,
        residual,
        weight,
        raw_weight: weight,
        opponent_name: opponent.team_name,
        event: game.event_name ?? game.competition ?? null,
      });
    }
    // Repeat meetings contribute performance evidence but at most one unit of
    // opponent support. They cannot manufacture confidence by repetition.
    profiles[id] = resultProfile(evidence, unknown);
  }
  return profiles;
}

function poisson(lambda: number): number[] {
  const probabilities = [Math.exp(-lambda)];
  for (let score = 1; score <= 40; score++) probabilities.push((probabilities[score - 1] * lambda) / score);
  const total = probabilities.reduce((a, b) => a + b, 0);
  return probabilities.map((value) => value / total);
}

/** One coherent score distribution supplies order probabilities and tier risks. */
export function predictCohortResult(a: TeamWithRanking, b: TeamWithRanking, evidence: ResultEvidence): MatchPrediction {
  const base = predictMatch(a, b, []);
  const ea = evidence[a.team_id_master];
  const eb = evidence[b.team_id_master];
  const margin = clip(base.expectedMargin + (ea?.correction ?? 0) - (eb?.correction ?? 0), 8);
  const total = Math.max(3, base.expectedScore.teamA + base.expectedScore.teamB, Math.abs(margin) + 0.4);
  const lambdaA = (total + margin) / 2;
  const lambdaB = (total - margin) / 2;
  const massA = poisson(lambdaA),
    massB = poisson(lambdaB);
  let winA = 0,
    winB = 0,
    draw = 0,
    abs = 0,
    blowout = 0;
  for (let x = 0; x < massA.length; x++)
    for (let y = 0; y < massB.length; y++) {
      const p = massA[x] * massB[y];
      if (x > y) winA += p;
      else if (x < y) winB += p;
      else draw += p;
      abs += p * Math.abs(x - y);
      if (Math.abs(x - y) >= 4) blowout += p;
    }
  return {
    ...base,
    predictedWinner: Math.abs(winA - winB) < 1e-12 ? 'draw' : winA > winB ? 'team_a' : 'team_b',
    winProbabilityA: winA,
    winProbabilityB: winB,
    drawProbability: draw,
    expectedScore: { teamA: Math.round(lambdaA), teamB: Math.round(lambdaB) },
    expectedMargin: margin,
    expectedAbsoluteGoalDifference: abs,
    blowout4PlusProbability: blowout,
    // No calibrated outcome-confidence claim for this experimental model.
    // Evidence support is reported separately in each frozen result profile.
    confidence: 'low',
    confidence_score: 0,
  };
}

/** Recompute support after removing an actual observed game from both teams. */
export function withoutResultGame(evidence: ResultEvidence, gameId: string): ResultEvidence {
  return Object.fromEntries(
    Object.entries(evidence).map(([id, profile]) => {
      if (!profile.influentialGames.some((row) => row.game_id === gameId)) return [id, profile];
      return [
        id,
        resultProfile(
          profile.influentialGames.filter((row) => row.game_id !== gameId),
          profile.unknownOpponentGames
        ),
      ];
    })
  );
}

/** Shared team/event weights perturb real observations, never synthetic outcomes. */
export function resampleResultEvidence(evidence: ResultEvidence, sample: number): ResultEvidence {
  let state = (COHORT_RESULT_MODEL.clusterSeed + sample) >>> 0;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  const counts = (ids: string[]) => {
    const unique = [...new Set(ids)].sort();
    const weights = new Map(unique.map((id) => [id, 0]));
    for (let i = 0; i < unique.length; i++) {
      const id = unique[Math.floor(random() * unique.length)];
      weights.set(id, weights.get(id)! + 1);
    }
    return weights;
  };
  const observations = Object.values(evidence).flatMap((profile) => profile.influentialGames);
  const teams = counts([...Object.keys(evidence), ...observations.map((row) => row.opponent_id)]);
  const events = counts(observations.map((row) => row.event ?? row.game_id));
  return Object.fromEntries(
    Object.entries(evidence).map(([id, profile]) => [
      id,
      resultProfile(
        profile.influentialGames
          .map((row) => ({
            ...row,
            raw_weight:
              row.raw_weight * teams.get(id)! * teams.get(row.opponent_id)! * events.get(row.event ?? row.game_id)!,
          }))
          .filter((row) => row.raw_weight > 0),
        profile.unknownOpponentGames
      ),
    ])
  );
}
