/** Seeding-only joint fit of observed results. Parameters require independent validation. */
import { predictMatch } from './matchPredictor';
import { withScoreDistribution } from './cohortResultModel';
import type { Game, TeamWithRanking } from './types';

export const NETWORK_RESULT_MODEL = {
  version: 'joint_game_evidence_v1',
  status: 'preview_unvalidated',
  halfLifeDays: 90,
  marginCap: 4,
  priorWeight: 0.5,
  previousSeasonWeight: 0.5,
  clusterSamples: 12,
  clusterSeed: 20261018,
  maximumIterations: 1000,
  convergenceTolerance: 1e-9,
} as const;
const clip = (x: number, cap: number) => Math.max(-cap, Math.min(cap, x));
type Prior = { strength: number; name: string; club: string; entrant: boolean; unknown: number };
type Fixture = {
  id: string;
  home: string;
  away: string;
  date: string;
  margin: number;
  goals: number;
  rawWeight: number;
  event: string;
  source: string | null;
};
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
  opponent_club: string;
  event: string;
  source_url: string | null;
  fixture: Fixture;
};
export type NetworkProfile = {
  modelVersion: string;
  strength: number;
  priorStrength: number;
  prior: Prior;
  correction: number;
  effectiveOpponentWeight: number;
  games: number;
  unknownOpponentGames: number;
  limited: boolean;
  influentialGames: Observation[];
  distinctOpponents: number;
  latestGameDate: string | null;
  componentEntrants: number;
  totalGoals: number;
  converged: boolean;
};
export type NetworkEvidence = Record<string, NetworkProfile>;

/** Each physical game supplies one edge, not a pair of independent team observations. */
function fit(priors: Record<string, Prior>, fixtures: Fixture[]): NetworkEvidence {
  const ids = Object.keys(priors).sort(),
    index = new Map(ids.map((id, i) => [id, i]));
  const pairWeights = new Map<string, number>();
  const pairKey = (g: Fixture) => JSON.stringify([g.home, g.away].sort());
  for (const g of fixtures) pairWeights.set(pairKey(g), (pairWeights.get(pairKey(g)) ?? 0) + g.rawWeight);
  const edges = fixtures.map((g) => ({
    g,
    a: index.get(g.home)!,
    b: index.get(g.away)!,
    w: g.rawWeight / Math.max(1, pairWeights.get(pairKey(g))!),
  }));
  const priorWeight = NETWORK_RESULT_MODEL.priorWeight;
  const rhs = ids.map((id) => priorWeight * priors[id].strength);
  const multiply = (v: number[]) => {
    const result = v.map((x) => priorWeight * x);
    for (const { a, b, w } of edges) {
      const d = w * (v[a] - v[b]);
      result[a] += d;
      result[b] -= d;
    }
    return result;
  };
  for (const { g, a, b, w } of edges) {
    const m = w * clip(g.margin, NETWORK_RESULT_MODEL.marginCap);
    rhs[a] += m;
    rhs[b] -= m;
  }
  // Conjugate gradients solve the sparse positive-definite graph system exactly
  // to a checked tolerance; no result is presented after non-convergence.
  const x = ids.map((id) => priors[id].strength),
    ax = multiply(x);
  let residual = rhs.map((v, i) => v - ax[i]),
    direction = [...residual];
  const dot = (a: number[], b: number[]) => a.reduce((s, v, i) => s + v * b[i], 0);
  let squared = dot(residual, residual);
  for (
    let iteration = 0;
    squared > NETWORK_RESULT_MODEL.convergenceTolerance ** 2 && iteration < NETWORK_RESULT_MODEL.maximumIterations;
    iteration++
  ) {
    const product = multiply(direction),
      alpha = squared / dot(direction, product);
    for (let i = 0; i < x.length; i++) x[i] += alpha * direction[i];
    residual = residual.map((v, i) => v - alpha * product[i]);
    const next = dot(residual, residual),
      beta = next / squared;
    direction = residual.map((v, i) => v + beta * direction[i]);
    squared = next;
  }
  if (!Number.isFinite(squared) || squared > NETWORK_RESULT_MODEL.convergenceTolerance ** 2)
    throw new Error('Game-evidence strength fit did not converge; rebuild or review the evidence.');
  const neighbours = ids.map(() => new Set<number>());
  const incident: (typeof edges)[] = ids.map(() => []);
  for (const edge of edges) {
    const { a, b } = edge;
    neighbours[a].add(b);
    neighbours[b].add(a);
    incident[a].push(edge);
    incident[b].push(edge);
  }
  const components = new Map<number, { entrants: number; totalGoals: number }>();
  for (let start = 0; start < ids.length; start++)
    if (!components.has(start)) {
      const members = new Set([start]),
        queue = [start];
      for (let k = 0; k < queue.length; k++)
        for (const next of neighbours[queue[k]])
          if (!members.has(next)) {
            members.add(next);
            queue.push(next);
          }
      const entrants = [...members].filter((i) => priors[ids[i]].entrant).length;
      let totalWeight = 0,
        weightedGoals = 0;
      for (const member of members)
        for (const edge of incident[member])
          if (edge.a === member) {
            // Count a physical fixture once, using only this component's evidence.
            totalWeight += edge.w;
            weightedGoals += edge.w * Math.min(edge.g.goals, 10);
          }
      const totalGoals = Math.max(1.4, Math.min(8.8, totalWeight ? weightedGoals / totalWeight : 3));
      for (const member of members) components.set(member, { entrants, totalGoals });
    }
  return Object.fromEntries(
    ids.map((id, i) => {
      const observations: Observation[] = incident[i]
        .map(({ g, a, b, w }) => {
          const home = a === i,
            opponent = ids[home ? b : a],
            margin = (home ? 1 : -1) * g.margin;
          const expected = priors[id].strength - priors[opponent].strength;
          return {
            game_id: g.id,
            opponent_id: opponent,
            date: g.date,
            margin,
            expected_margin: expected,
            residual: clip(margin, NETWORK_RESULT_MODEL.marginCap) - clip(expected, NETWORK_RESULT_MODEL.marginCap),
            weight: w,
            raw_weight: g.rawWeight,
            opponent_name: priors[opponent].name,
            opponent_club: priors[opponent].club,
            event: g.event,
            source_url: g.source,
            fixture: g,
          };
        })
        .sort(
          (a, b) =>
            Math.abs(b.weight * b.residual) - Math.abs(a.weight * a.residual) || a.game_id.localeCompare(b.game_id)
        );
      const support = observations.reduce((s, g) => s + g.weight, 0);
      return [
        id,
        {
          modelVersion: NETWORK_RESULT_MODEL.version,
          strength: x[i],
          priorStrength: priors[id].strength,
          prior: priors[id],
          correction: x[i] - priors[id].strength,
          effectiveOpponentWeight: support,
          games: observations.length,
          unknownOpponentGames: priors[id].unknown,
          limited: support < 3,
          influentialGames: observations,
          distinctOpponents: neighbours[i].size,
          latestGameDate:
            observations
              .map((g) => g.date)
              .sort()
              .at(-1) ?? null,
          componentEntrants: components.get(i)!.entrants,
          totalGoals: components.get(i)!.totalGoals,
          converged: true,
        },
      ];
    })
  );
}

export function buildNetworkEvidence(
  teams: Record<string, TeamWithRanking>,
  games: Game[],
  asOf: string,
  entrantIds: string[] = Object.keys(teams)
): NetworkEvidence {
  const end = Date.parse(asOf + 'T00:00:00Z');
  if (!Number.isFinite(end)) throw new Error('Invalid game-evidence cutoff');
  const date = new Date(end),
    season = Date.UTC(date.getUTCFullYear() - (date.getUTCMonth() < 7 ? 1 : 0), 7, 1);
  const entrants = new Set(entrantIds),
    priors: Record<string, Prior> = {};
  for (const [id, t] of Object.entries(teams).sort()) {
    // A fixed neutral opponent places all priors on the existing goal scale.
    // This is supporting, correlated rating evidence, never an extra game.
    const neutral: TeamWithRanking = {
      club_name: null,
      league: null,
      distinction: null,
      state: null,
      gender: t.gender,
      rank_in_cohort_final: null,
      last_scraped_at: null,
      win_percentage: 0,
      team_id_master: '__neutral__',
      team_name: 'Reference',
      age: null,
      power_score_final: 0.5,
      glicko_rating: 1500,
      glicko_rd: 350,
      games_played: 0,
      wins: 0,
      losses: 0,
      draws: 0,
      offense_norm: 0.5,
      defense_norm: 0.5,
      sos_norm: 0.5,
      exp_margin: null,
      exp_goals_for: null,
      exp_goals_against: null,
      exp_win_rate: null,
      same_age_games: undefined,
      same_age_game_share: undefined,
      same_age_unique_opponents: undefined,
      same_age_top100_opp_count: undefined,
      same_age_top500_opp_count: undefined,
      same_age_avg_opp_power_adj: undefined,
      repeat_opponent_share: undefined,
      positive_ml_evidence_scale: undefined,
      publication_cap_rank: undefined,
      publication_cap_score: undefined,
    };
    priors[id] = {
      strength: predictMatch(t, neutral, []).expectedMargin,
      name: t.team_name,
      club: t.club_name ?? '',
      entrant: entrants.has(id),
      unknown: 0,
    };
  }
  const fixtures: Fixture[] = [],
    seen = new Map<string, string>();
  for (const g of [...games].sort((a, b) => a.id.localeCompare(b.id))) {
    const played = Date.parse(g.game_date.slice(0, 10) + 'T00:00:00Z');
    if (
      !Number.isFinite(played) ||
      played > end ||
      end - played > 365 * 86400000 ||
      g.is_excluded ||
      g.home_score == null ||
      g.away_score == null
    )
      continue;
    if (!Number.isInteger(g.home_score) || !Number.isInteger(g.away_score) || g.home_score < 0 || g.away_score < 0)
      throw new Error('Invalid scored game');
    const home = g.home_team_master_id ?? '',
      away = g.away_team_master_id ?? '';
    const signature = JSON.stringify([home, away, g.game_date, g.home_score, g.away_score]);
    if (seen.has(g.id)) {
      if (seen.get(g.id) !== signature) throw new Error('Conflicting duplicate game');
      continue;
    }
    seen.set(g.id, signature);
    if (!priors[home] || !priors[away]) {
      if (priors[home]) priors[home].unknown++;
      if (priors[away]) priors[away].unknown++;
      continue;
    }
    if (home === away) throw new Error('A team cannot play itself');
    fixtures.push({
      id: g.id,
      home,
      away,
      date: g.game_date.slice(0, 10),
      margin: g.home_score - g.away_score,
      goals: g.home_score + g.away_score,
      rawWeight:
        Math.pow(0.5, (end - played) / 86400000 / NETWORK_RESULT_MODEL.halfLifeDays) *
        (played < season ? NETWORK_RESULT_MODEL.previousSeasonWeight : 1),
      event: g.event_name ?? g.competition ?? g.id,
      source: g.source_url ?? null,
    });
  }
  return fit(priors, fixtures);
}
function refit(evidence: NetworkEvidence, transform: (g: Fixture) => Fixture | null): NetworkEvidence {
  const fixtures = new Map<string, Fixture>();
  for (const p of Object.values(evidence)) for (const row of p.influentialGames) fixtures.set(row.game_id, row.fixture);
  return fit(
    Object.fromEntries(Object.entries(evidence).map(([id, p]) => [id, p.prior])),
    [...fixtures.values()]
      .sort((a, b) => a.id.localeCompare(b.id))
      .map(transform)
      .filter((g): g is Fixture => g !== null)
  );
}
export function withoutNetworkGame(evidence: NetworkEvidence, id: string) {
  return refit(evidence, (g) => (g.id === id ? null : g));
}
export function resampleNetworkEvidence(evidence: NetworkEvidence, sample: number) {
  let state = (NETWORK_RESULT_MODEL.clusterSeed + sample) >>> 0;
  const counts = (values: string[]) => {
    const ids = [...new Set(values)].sort(),
      counts = new Map(ids.map((id) => [id, 0]));
    for (let i = 0; i < ids.length; i++) {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      const id = ids[Math.floor((state / 4294967296) * ids.length)];
      counts.set(id, counts.get(id)! + 1);
    }
    return counts;
  };
  const teams = counts(Object.keys(evidence)),
    events = counts(Object.values(evidence).flatMap((p) => p.influentialGames.map((g) => g.event)));
  return refit(evidence, (g) => {
    const w = teams.get(g.home)! * teams.get(g.away)! * events.get(g.event)!;
    return w ? { ...g, rawWeight: g.rawWeight * w } : null;
  });
}
export function predictNetworkResult(a: TeamWithRanking, b: TeamWithRanking, evidence: NetworkEvidence) {
  const ea = evidence[a.team_id_master],
    eb = evidence[b.team_id_master];
  if (!ea || !eb) throw new Error('Missing game-evidence strength');
  const margin = clip(ea.strength - eb.strength, 8),
    // Across disconnected components, combine both rates symmetrically.
    total = Math.max((ea.totalGoals + eb.totalGoals) / 2, Math.abs(margin) + 0.3);
  return withScoreDistribution(predictMatch(a, b, []), margin, total);
}
