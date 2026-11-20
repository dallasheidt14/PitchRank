// @vitest-environment node
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { expect, it, vi } from 'vitest';
import { predictionRuntime } from './predictionRuntime';
import { WEIGHT_NAMES } from './winnerResearch';
import { formulaSyntheticCases, SYNTHETIC_CLOCK } from './compareFormulaCases';
import { createFormulaRuntime } from './compareFormulaResearch';
import type { MatchPredictionShadowContext } from './matchPredictionService';
type FrozenGame = NonNullable<MatchPredictionShadowContext['frozenEvidence']>['games'][number];
vi.mock('./calibrationLoader.ts', () => ({ loadCalibrationJson: async () => null }));

it('replays effective defaults, preserves A/A, and freezes deterministic weighted outputs', async () => {
  const p = await predictionRuntime();
  const cases = p.probes.map((probe) => ({
    context: {
      teamAInput: probe.teamA,
      teamBInput: probe.teamB,
      frozenEvidence: { games: [] },
      calibration: p.calibration,
    },
    prediction: probe.prediction,
    reference_time: p.observed_at,
  }));
  const run = (weights: Record<string, number>, rows = cases) =>
    JSON.parse(
      execFileSync(process.execPath, ['--import', 'tsx', path.join(process.cwd(), 'scripts/run-winner-study.ts')], {
        input: JSON.stringify({ weights, cases: rows }),
        encoding: 'utf8',
        windowsHide: true,
        timeout: 30000,
        env: { ...process.env, NODE_OPTIONS: '--conditions=react-server' },
        stdio: ['pipe', 'pipe', 'pipe'],
      })
    );
  const ones = Object.fromEntries(WEIGHT_NAMES.map((key) => [key, 1]));
  const baseline = run(ones);
  for (const [i, result] of baseline.entries()) {
    expect(result.prediction).toEqual(cases[i].prediction);
    expect(result.receipt.aa_parity).toBe(true);
    expect(result.receipt.baseline_replay).toBe(true);
  }
  const weights = { ...ones, schedule: 2.2, strength: 0.2, offense_defense: 4.2, record: 3.4 };
  expect(run(weights)).toEqual(run(weights));
  expect(
    run(weights).some(
      (r: { prediction: unknown }, i: number) => JSON.stringify(r.prediction) !== JSON.stringify(baseline[i].prediction)
    )
  ).toBe(true);
  expect(() => run({ ...weights, schedule: -1 })).toThrow();
  const changed = structuredClone(cases);
  changed[0].prediction.winProbabilityA += 0.01;
  expect(() => run(weights, changed)).toThrow();
  const noClock = structuredClone(cases);
  noClock[0].reference_time = '2026-11-20T01:00:00';
  expect(() => run(weights, noClock)).toThrow();
}, 60000);

it('applies every registered multiplier to its own contribution and reverses teams consistently', async () => {
  const p = await predictionRuntime();
  const context = formulaSyntheticCases(p.calibration)[1];
  context.teamAInput = { ...context.teamAInput, games_played: 20, wins: 12, draws: 2, glicko_rd: 80 };
  context.teamBInput = {
    ...context.teamBInput,
    games_played: 9,
    wins: 2,
    draws: 1,
    glicko_rd: 230,
    same_age_games: 2,
    same_age_game_share: 0.3,
    same_age_unique_opponents: 1,
    repeat_opponent_share: 0.8,
    positive_ml_evidence_scale: 0.3,
  };
  context.frozenEvidence!.games = context.frozenEvidence!.games.filter(
    (game) => game.home_team_master_id === 'a' || ['b-0', 'b-1'].includes(game.id)
  );
  context.frozenEvidence!.games.push(
    {
      id: 'h2h',
      game_date: '2026-11-12',
      home_team_master_id: 'a',
      away_team_master_id: 'b',
      home_score: 3,
      away_score: 1,
      ml_overperformance: 1,
    } as FrozenGame,
    {
      id: 'a-shared',
      game_date: '2026-11-11',
      home_team_master_id: 'a',
      away_team_master_id: 'shared',
      home_score: 3,
      away_score: 0,
      ml_overperformance: 1,
    } as FrozenGame,
    {
      id: 'b-shared',
      game_date: '2026-11-11',
      home_team_master_id: 'b',
      away_team_master_id: 'shared',
      home_score: 0,
      away_score: 2,
      ml_overperformance: -1,
    } as FrozenGame
  );
  const independent = await createFormulaRuntime(p.calibration, process.cwd());
  const control = independent.run(context, SYNTHETIC_CLOCK);
  const weights = Object.fromEntries(WEIGHT_NAMES.map((key, i) => [key, 0.2 + i * 0.17]));
  const reverse = { ...context, teamAInput: context.teamBInput, teamBInput: context.teamAInput };
  const cases = [context, reverse].map((c) => ({
    context: c,
    reference_time: SYNTHETIC_CLOCK,
    prediction: independent.run(c, SYNTHETIC_CLOCK).prediction,
  }));
  const outputs = JSON.parse(
    execFileSync(process.execPath, ['--import', 'tsx', path.join(process.cwd(), 'scripts/run-winner-study.ts')], {
      input: JSON.stringify({ weights, cases }),
      encoding: 'utf8',
      windowsHide: true,
      timeout: 30000,
      env: { ...process.env, NODE_OPTIONS: '--conditions=react-server', TSX_DISABLE_CACHE: '1' },
      stdio: ['pipe', 'pipe', 'pipe'],
    })
  );
  const names = ['strength', 'sos', 'form', 'matchup', 'record', 'evidence', 'headToHead', 'commonOpponent', 'ml'];
  const expected =
    names.reduce((sum, name, i) => sum + control.trace.terms[name] * weights[WEIGHT_NAMES[i]], 0) *
    control.trace.amplification;
  for (const name of names) expect(Math.abs(control.trace.terms[name]), name).toBeGreaterThan(0);
  expect(outputs[0].prediction.components.compositeDiff).toBeCloseTo(expected, 12);
  const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));
  const share = clamp(
    expected + control.trace.predictiveShare + control.trace.mlShare * weights.ml_directional,
    -0.9,
    0.9
  );
  const total = control.trace.totalGoals;
  const margin =
    (2 / (1 + Math.exp(-4.5 * share)) - 1) * total * clamp(control.trace.marginMultiplier / 1.25, 0.85, 1.25);
  const bound = Math.min(total - 0.3, 15 - total);
  expect(outputs[0].prediction.expectedGoals.teamA).toBeCloseTo((total + clamp(margin, -bound, bound)) / 2, 12);
  expect(outputs[0].prediction.winProbabilityA).toBeCloseTo(outputs[1].prediction.winProbabilityB, 12);
  expect(outputs[0].prediction.expectedMargin).toBeCloseTo(-outputs[1].prediction.expectedMargin, 12);
  expect(outputs[0].prediction.blowout4PlusProbability).toBeCloseTo(outputs[1].prediction.blowout4PlusProbability, 12);
}, 60000);
