// @vitest-environment node
import path from 'node:path';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { createFormulaRuntime, FORMULA_ARMS, instrumentFormula } from './compareFormulaResearch';
import { formulaSyntheticCases, SYNTHETIC_CLOCK } from './compareFormulaCases';
import { matchCalibrationSnapshot, predictMatch, warmMatchPredictorCalibration } from './matchPredictor';
import { createHistoryAuditor } from './compareHistoryAudit';
import { readFileSync } from 'node:fs';

let runtime: Awaited<ReturnType<typeof createFormulaRuntime>>;
let cases: ReturnType<typeof formulaSyntheticCases>;
beforeAll(async () => {
  await warmMatchPredictorCalibration();
  cases = formulaSyntheticCases(matchCalibrationSnapshot());
  runtime = await createFormulaRuntime(matchCalibrationSnapshot(), process.cwd());
});

describe('isolated formula research', () => {
  it('distinguishes frozen baseline verification from reconstructed candidate predictions', () => {
    const context = cases[1];
    const baseline = runtime.run(context, SYNTHETIC_CLOCK).prediction;
    const variants = runtime.variants(context, SYNTHETIC_CLOCK, baseline);
    expect(variants.baseline.receipt.prediction_provenance).toBe('frozen_replay');
    for (const arm of FORMULA_ARMS.filter((arm) => arm !== 'baseline')) {
      expect(variants[arm].receipt.baseline_provenance).toBe('frozen_baseline_replay');
      expect(variants[arm].receipt.prediction_provenance).toBe('reconstructed');
    }
  });

  it('keeps the fixed-SOS control separate from the fixed-all-weights control', () => {
    const context = cases[301];
    const improved = {
      ...context,
      teamAInput: { ...context.teamAInput, power_score_final: context.teamAInput.power_score_final! + 0.005 },
    };
    const result = runtime.diagnose(context, improved, SYNTHETIC_CLOCK);
    expect(result.after.trace.weights).not.toEqual(result.before.trace.weights);
    expect(result.fixed_weights.trace.weights).toEqual(result.before.trace.weights);
    expect(result.fixed_sos.trace.weights).toEqual({
      ...result.after.trace.weights,
      SOS: result.before.trace.weights.SOS,
    });
    expect(result.after.prediction.winProbabilityA).toBeLessThan(result.before.prediction.winProbabilityA);
    expect(result.fixed_sos.prediction.winProbabilityA).toBeGreaterThan(result.before.prediction.winProbabilityA);
  });

  it('freezes date-sensitive age fallback and common-opponent recency across host clocks and zones', () => {
    const context = structuredClone(cases[1]);
    context.teamAInput.age = null;
    context.teamBInput.age = null;
    context.teamAInput.team_name = 'A 14B';
    context.teamBInput.team_name = 'B 14B';
    context.frozenEvidence!.games = [
      { ...context.frozenEvidence!.games[0], id: 'a-shared', game_date: '2026-09-10', away_team_master_id: 'shared' },
      { ...context.frozenEvidence!.games[20], id: 'b-shared', game_date: '2026-11-01', away_team_master_id: 'shared' },
    ];
    const zone = process.env.TZ;
    vi.useFakeTimers();
    try {
      process.env.TZ = 'UTC';
      vi.setSystemTime(new Date(SYNTHETIC_CLOCK));
      const expected = predictMatch(context.teamAInput, context.teamBInput, context.frozenEvidence!.games);
      expect(expected.components!.commonOpponentCount).toBe(1);
      process.env.TZ = 'Pacific/Honolulu';
      vi.setSystemTime(new Date('2030-08-01T00:15:00Z'));
      expect(runtime.run(context, SYNTHETIC_CLOCK, {}, expected).prediction).toEqual(expected);
      const later = runtime.run(context, '2027-08-01T00:15:00Z');
      expect(later.prediction).not.toEqual(expected);
      expect(process.env.TZ).toBe('Pacific/Honolulu');
    } finally {
      vi.useRealTimers();
      if (zone === undefined) delete process.env.TZ;
      else process.env.TZ = zone;
    }
  });
  it('reproduces every baseline output from the actual TS predictor and replays deterministically', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(SYNTHETIC_CLOCK));
    try {
      for (const c of cases.slice(0, 8)) {
        const frozen = predictMatch(c.teamAInput, c.teamBInput, c.frozenEvidence!.games);
        const result = runtime.run(c, SYNTHETIC_CLOCK, {}, frozen);
        expect(result.prediction).toEqual(frozen);
        expect(runtime.run(c, SYNTHETIC_CLOCK, {}, frozen)).toEqual(result);
      }
    } finally {
      vi.useRealTimers();
    }
  });

  it('changes only the declared contribution and retains both ML contributions', () => {
    const c = cases[1],
      variants = runtime.variants(c, SYNTHETIC_CLOCK);
    const base = variants.baseline.trace;
    for (const arm of FORMULA_ARMS) {
      const t = variants[arm].trace;
      expect(t.mlComposite).toBe(base.mlComposite);
      expect(t.mlShare).toBe(base.mlShare);
      expect(t.totalGoals).toBe(base.totalGoals);
      expect(t.strengthSignal).toBe(base.strengthSignal);
      const untouched = arm === 'extra_record_off' ? 'sos' : 'record';
      expect(t.terms[untouched]).toBe(base.terms[untouched]);
      for (const key of ['strength', 'form', 'matchup', 'ml', 'evidence', 'headToHead', 'commonOpponent'])
        expect(t.terms[key]).toBe(base.terms[key]);
      expect(Object.values(t.terms).reduce((a, b) => a + b, 0)).toBe(t.beforeAmplification);
      expect(t.beforeAmplification * t.amplification).toBe(t.compositeDiff);
    }
    expect(variants.sos_x0.trace.terms.sos).toBeCloseTo(0, 14);
    expect(variants['sos_x0.5'].trace.terms.sos).toBe(base.terms.sos / 2);
    expect(variants['fixed_sos_0.06'].trace.weights.SOS).toBe(0.06);
    expect(variants['fixed_sos_0.12'].trace.weights.SOS).toBe(0.12);
    expect(variants['fixed_sos_0.18'].trace.weights.SOS).toBe(0.18);
  });

  it('keeps the record fallback when Glicko is unavailable', () => {
    const c = structuredClone(cases[1]);
    c.teamAInput.glicko_rating = null;
    c.teamBInput.glicko_rating = null;
    const variants = runtime.variants(c, SYNTHETIC_CLOCK);
    expect(variants.extra_record_off.trace.hasGlicko).toBe(false);
    expect(variants.extra_record_off.trace.recordDiff).not.toBe(0);
    expect(variants.extra_record_off.trace.strengthSignal).toBe(variants.baseline.trace.strengthSignal);
    expect(variants.extra_record_off.trace.strengthSignal).toBeCloseTo(
      variants.baseline.trace.powerDiff * 0.5 + variants.baseline.trace.recordDiff * 0.25,
      14
    );
    expect(variants.extra_record_off.trace.terms.record).toBe(0);
  });

  it('swaps all candidate probabilities, margins, goals and four-goal risk', () => {
    for (const c of cases.slice(0, 5)) {
      const a = runtime.variants(c, SYNTHETIC_CLOCK);
      const b = runtime.variants({ ...c, teamAInput: c.teamBInput, teamBInput: c.teamAInput }, SYNTHETIC_CLOCK);
      for (const arm of FORMULA_ARMS) {
        const p = a[arm].prediction,
          q = b[arm].prediction;
        expect(p.winProbabilityA).toBeCloseTo(q.winProbabilityB, 12);
        expect(p.drawProbability).toBeCloseTo(q.drawProbability!, 12);
        expect(p.expectedMargin).toBeCloseTo(-q.expectedMargin, 12);
        expect(p.expectedGoals!.teamA).toBeCloseTo(q.expectedGoals!.teamB, 12);
        expect(p.blowout4PlusProbability).toBeCloseTo(q.blowout4PlusProbability!, 12);
      }
    }
  });

  it('rejects a different baseline, calibration, clock, and changed instrumentation anchors', () => {
    const c = cases[1],
      p = runtime.run(c, SYNTHETIC_CLOCK).prediction;
    expect(() => runtime.run(c, SYNTHETIC_CLOCK, {}, { ...p, expectedMargin: p.expectedMargin + 0.1 })).toThrow(
      'replay'
    );
    expect(() => runtime.run({ ...c, calibration: { ...c.calibration!, probability: null } }, SYNTHETIC_CLOCK)).toThrow(
      'calibration'
    );
    expect(() => runtime.run(c, '2026-11-13')).toThrow('clock');
    const source = readFileSync(path.join(process.cwd(), 'lib/matchPredictor.ts'), 'utf8').replace(/\r\n/g, '\n');
    expect(() => instrumentFormula(source.replace('recordDiff * 0.08 +', 'recordDiff * 0.09 +'))).toThrow('anchor');
  });
});

describe('frozen history audit', () => {
  it('reports source duplicates without discarding real rematches or treating team-history URLs as fixture proof', () => {
    const c = structuredClone(cases[1]);
    const g = c.frozenEvidence!.games[0];
    c.frozenEvidence!.games = [
      { ...g, id: 'a', provider_id: 'p', source_url: 'https://example.test/matches/101' },
      { ...g, id: 'b', provider_id: 'p', source_url: 'https://example.test/matches/101' },
      { ...g, id: 'c', provider_id: 'p', source_url: 'https://example.test/matches/102' },
      { ...g, id: 'd', provider_id: 'p', source_url: 'https://example.test/team/1/game-history' },
    ];
    const before = structuredClone(c);
    const result = createHistoryAuditor(process.cwd())(c, SYNTHETIC_CLOCK);
    expect(result.same_source_fixture_copies).toEqual([['a', 'b']]);
    expect(result.unknown_source_identity).toBe(1);
    expect(result.teams[0].recent_count).toBe(4);
    expect(result.teams[0].unique_recent_opponents).toBe(1);
    expect(result.teams[1].missing_history).toBe(true);
    expect(c).toEqual(before);
  });

  it('reports invalid, future, excluded, missing ML, and unstable same-day ordering separately', () => {
    const c = structuredClone(cases[1]),
      g = c.frozenEvidence!.games[0];
    c.frozenEvidence!.games = [
      { ...g, id: 'z', home_score: -1, is_excluded: true },
      { ...g, id: 'a', ml_overperformance: null },
      { ...g, id: 'future', game_date: '2027-01-01' },
    ];
    const r = createHistoryAuditor(process.cwd())(c, SYNTHETIC_CLOCK);
    expect(r.invalid_scores).toEqual(['z']);
    expect(r.excluded_games).toEqual(['z']);
    expect(r.future_games).toEqual(['future']);
    expect(r.ordering_errors).toEqual(['a', 'future']);
    expect(r.teams[0].missing_ml_recent).toBe(1);
  });
});
