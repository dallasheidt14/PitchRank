import { describe, expect, it, vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';
vi.mock('server-only', () => ({}));
import { filteringClientMock } from '@/test/supabase-mock';
import { captureForecasts, type CaptureOptions } from './prospectiveCapture';
import { MATCH_PREDICTION_VERSION, type buildMatchPredictionWithShadowContext } from './matchPredictionService';

const options: CaptureOptions = {
  execute: true,
  status: 'pending',
  source: 'database',
  limit: 500,
  concurrency: 4,
  budgetMinutes: 45,
};
const now = () => new Date('2026-11-11T23:59:00Z');
const identity = { codeRevision: 'test-revision', algorithmHash: 'test-algorithm' };
function fixture(extra = {}) {
  return {
    id: 'f',
    fixture_key: 'database:g',
    game_date: '2026-11-12',
    source_game_id: 'g',
    source_system: 'database_games',
    provider_code: 'test',
    home_team_master_id: 'a',
    away_team_master_id: 'b',
    resolution_status: 'resolved',
    heuristic_prediction_status: 'pending',
    fixture_payload: {
      cohort: 'u13|Male',
      source_snapshot: {
        game_date: '2026-11-12',
        home_team_master_id: 'a',
        away_team_master_id: 'b',
        provider_id: 'p',
        source_url: null,
      },
    },
    ...extra,
  };
}
function setup(extraRows: ReturnType<typeof fixture>[] = []) {
  const row = fixture();
  const mock = filteringClientMock({
    prospective_match_predictions: [row, ...extraRows],
    games: [
      { id: 'g', ...row.fixture_payload.source_snapshot, home_score: null, away_score: null, is_excluded: false },
    ],
  });
  const rpc = vi.fn(async (_name: string, values: Record<string, unknown>) => {
    const record = mock.tableRows.prospective_match_predictions.find((item) => item.id === values.p_fixture_id);
    if (!record || record.heuristic_prediction_status === 'completed') return { data: false, error: null };
    record.heuristic_prediction_status = 'completed';
    record.heuristic_prediction = values.p_prediction;
    return { data: true, error: null };
  });
  mock.client.rpc = rpc as unknown as SupabaseClient['rpc'];
  const predict = vi.fn(
    async () =>
      ({
        response: { prediction: { winProbabilityA: 0.6, drawProbability: 0.2, winProbabilityB: 0.2 } },
        shadowContext: {
          predictorVersion: MATCH_PREDICTION_VERSION,
          preOutcomeCalibration: [0.7, 0.15, 0.15],
          calibration: { outcome: { alpha: 0.55 }, confidence: {}, probability: {}, margin: {}, ageGroups: {} },
          frozenEvidence: { games: [], as_of: '2026-11-11' },
        },
      }) as unknown as Awaited<ReturnType<typeof buildMatchPredictionWithShadowContext>>
  );
  return { ...mock, rpc, predict, deps: { now, identity, predict } };
}
describe('prospective capture', () => {
  it('filters old, same-day, far-future, completed and unresolved fixtures before inference', async () => {
    const setupResult = setup([
      fixture({ id: 'old', game_date: '2026-11-10' }),
      fixture({ id: 'same-day', game_date: '2026-11-11' }),
      fixture({ id: 'future', game_date: '2026-11-19' }),
      fixture({ id: 'completed', heuristic_prediction_status: 'completed' }),
      fixture({ id: 'unresolved', resolution_status: 'unresolved' }),
    ]);
    const summary = await captureForecasts(setupResult.client, options, setupResult.deps);
    expect(summary.eligible).toBe(1);
    expect(summary.frozen).toBe(1);
    expect(summary.frozenIds).toEqual(['f']);
    expect(setupResult.predict).toHaveBeenCalledTimes(1);
    expect(setupResult.predict).toHaveBeenCalledWith(setupResult.client, 'a', 'b', setupResult.client, {
      freezeInputs: true,
    });
    expect(setupResult.rpc.mock.calls[0][0]).toBe('freeze_prospective_forecast');
  });
  it('holds a changed provider match link before prediction', async () => {
    const s = setup();
    s.tableRows.games[0].source_url = 'https://example.com/games/456';
    const result = await captureForecasts(s.client, options, s.deps);
    expect(result.skipped).toBe(1);
    expect(s.predict).not.toHaveBeenCalled();
    expect(s.rpc).not.toHaveBeenCalled();
  });
  it('does not freeze when midnight passes during inference', async () => {
    const s = setup();
    let current = now();
    s.predict.mockImplementation(async () => {
      current = new Date('2026-11-12T00:00:00Z');
      return {
        shadowContext: {
          predictorVersion: MATCH_PREDICTION_VERSION,
          calibration: {},
          frozenEvidence: { games: [] },
          preOutcomeCalibration: [0.5, 0.2, 0.3],
        },
      } as unknown as Awaited<ReturnType<typeof buildMatchPredictionWithShadowContext>>;
    });
    const result = await captureForecasts(s.client, options, { ...s.deps, now: () => current });
    expect(result.errors[0].reason).toBe('match_day_started');
    expect(s.rpc).not.toHaveBeenCalled();
  });
  it.each(['home_score', 'away_score'])('refuses a fixture with %s already recorded, including zero', async (field) => {
    const s = setup();
    s.tableRows.games[0][field] = 0;
    const summary = await captureForecasts(s.client, options, s.deps);
    expect(summary.errors[0].reason).toBe('source_fixture_changed');
    expect(s.predict).not.toHaveBeenCalled();
    expect(s.rpc).not.toHaveBeenCalled();
  });
  it('dry-run does not mutate either completed or pending rows', async () => {
    const s = setup();
    const before = structuredClone(s.tableRows);
    const result = await captureForecasts(s.client, { ...options, execute: false }, s.deps);
    expect(result.wouldFreeze).toBe(1);
    expect(result.frozen).toBe(0);
    expect(s.tableRows).toEqual(before);
    expect(s.rpc).not.toHaveBeenCalled();
  });
  it('freezes once under a race and cannot reset a completed forecast on retry', async () => {
    const s = setup();
    const results = await Promise.all([
      captureForecasts(s.client, options, s.deps),
      captureForecasts(s.client, options, s.deps),
    ]);
    expect(results.reduce((total, result) => total + result.frozen, 0)).toBe(1);
    const payload = structuredClone(s.tableRows.prospective_match_predictions[0].heuristic_prediction);
    expect((await captureForecasts(s.client, options, s.deps)).eligible).toBe(0);
    expect(s.tableRows.prospective_match_predictions[0].heuristic_prediction).toEqual(payload);
  });
  it('rejects a mismatched predictor version instead of relabeling it', async () => {
    const s = setup();
    const normal = await s.predict();
    normal.shadowContext.predictorVersion = 'another-version';
    s.predict.mockResolvedValue(normal);
    const summary = await captureForecasts(s.client, options, s.deps);
    expect(summary.errors[0].reason).toBe('model_version_mismatch');
    expect(s.rpc).not.toHaveBeenCalled();
  });
});
