import type { Game, TeamWithRanking } from './types';
import type { MatchPredictionShadowContext } from './matchPredictionService';

export const SYNTHETIC_CLOCK = '2026-11-13T22:38:46.070Z';
export const SENSITIVITY_STEPS = {
  glicko_rating: 5,
  power_score_final: 0.005,
  sos_norm: 0.005,
  offense_norm: 0.005,
  defense_norm: 0.005,
} as const;
const clamp = (n: number) => Math.max(0, Math.min(1, n));

/** Same seed, order, and arithmetic as the original 1,500-case v8 diagnostic. */
export function formulaSyntheticCases(calibration: MatchPredictionShadowContext['calibration']) {
  let seed = 1449;
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  function sample(id: string, n: number, age: number) {
    const power = 0.1 + random() * (age === 10 ? 0.45 : 0.65);
    const team = {
      team_id_master: id,
      team_name: `Synthetic ${id}`,
      age,
      gender: 'M',
      power_score_final: power,
      sos_norm: random(),
      offense_norm: clamp(0.2 + power * 0.65 + (random() - 0.5) * 0.25),
      defense_norm: clamp(0.2 + power * 0.65 + (random() - 0.5) * 0.25),
      glicko_rating: 1150 + power * 850 + (random() - 0.5) * 80,
      glicko_rd: n < 4 ? 230 : 100,
      games_played: n,
      wins: 0,
      losses: 0,
      draws: 0,
      status: n < 10 ? 'Not Enough Ranked Games' : 'Active',
      ratings_as_of: SYNTHETIC_CLOCK,
    } as unknown as TeamWithRanking;
    const games: Game[] = [];
    for (let j = 0; j < n; j++) {
      const gf = Math.floor(random() * 5),
        ga = Math.floor(random() * 5);
      team[gf > ga ? 'wins' : gf < ga ? 'losses' : 'draws']++;
      games.push({
        id: `${id}-${j}`,
        game_date: new Date(Date.parse(SYNTHETIC_CLOCK.slice(0, 10)) - (j + 1) * 86400000).toISOString().slice(0, 10),
        home_team_master_id: id,
        away_team_master_id: `opponent-${id}-${j}`,
        home_score: gf,
        away_score: ga,
        ml_overperformance: (random() - 0.5) * 2,
      } as Game);
    }
    return { team, games };
  }
  return Array.from({ length: 1500 }, (_, i) => {
    const age = [10, 12, 15, 19][i % 4],
      n = i % 3 === 0 ? 3 : 20;
    const a = sample('a', n, age),
      b = sample('b', n, age);
    return {
      predictorVersion: 'heuristic_v8_continuous_transitions_v1',
      teamAInput: a.team,
      teamBInput: b.team,
      frozenEvidence: { games: [...a.games, ...b.games] },
      calibration,
    } as MatchPredictionShadowContext;
  });
}

export function improvedFormulaContext(context: MatchPredictionShadowContext, field: keyof typeof SENSITIVITY_STEPS) {
  const original = context.teamAInput[field];
  if (typeof original !== 'number' || !Number.isFinite(original)) return null;
  const value =
    field === 'glicko_rating' ? original + SENSITIVITY_STEPS[field] : clamp(original + SENSITIVITY_STEPS[field]);
  if (value === original) return null;
  return { ...context, teamAInput: { ...context.teamAInput, [field]: value } };
}

/** Sweep both sides of the adaptive transition endpoints, with aligned and conflicting SOS. */
export function formulaBoundaryCases(context: MatchPredictionShadowContext) {
  return [0.05, 0.08].flatMap((boundary) =>
    [-1, 1].flatMap((sign) =>
      [-1, 1].flatMap((sos) =>
        [-0.000001, 0, 0.000001].map((epsilon) => ({
          ...context,
          teamAInput: {
            ...context.teamAInput,
            power_score_final: 0.5 + sign * (boundary + epsilon),
            offense_norm: 0.5,
            defense_norm: 0.5,
            sos_norm: 0.5 + sos * 0.3,
            games_played: 20,
            glicko_rd: 80,
          },
          teamBInput: {
            ...context.teamBInput,
            power_score_final: 0.5,
            offense_norm: 0.5,
            defense_norm: 0.5,
            sos_norm: 0.5 - sos * 0.3,
            games_played: 20,
            glicko_rd: 80,
          },
        }))
      )
    )
  );
}
