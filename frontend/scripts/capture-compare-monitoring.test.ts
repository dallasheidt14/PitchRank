// @vitest-environment node
import { createHash } from 'node:crypto';
import { beforeEach, expect, it, vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';
import { captureMonitoring } from './capture-compare-monitoring';

const doubles = vi.hoisted(() => ({ predict: vi.fn(), run: vi.fn(), create: vi.fn(), close: vi.fn() }));
vi.mock('../lib/matchPredictionService', () => ({
  MATCH_PREDICTION_VERSION: 'test-live',
  buildMatchPredictionWithShadowContext: doubles.predict,
}));
vi.mock('../lib/matchPredictor', () => ({
  warmMatchPredictorCalibration: async () => {},
  matchCalibrationSnapshot: () => ({ margin: {} }),
}));
vi.mock('../lib/sosResearch', () => ({ SOS_MULTIPLIERS: [0, 0.5, 1, 1.5], createSosRuntime: doubles.create }));
vi.mock('../lib/prospectiveCapture', async () => {
  const { createHash } = await import('node:crypto');
  return {
    captureCodeIdentity: () => ({ codeRevision: 'd'.repeat(40), algorithmHash: 'b'.repeat(64) }),
    digest: (v: unknown) => createHash('sha256').update(JSON.stringify(v)).digest('hex'),
  };
});

function database(count = 2, existingCount = 0) {
  const day = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  const rows = Array.from({ length: count }, (_, i) => ({
    id: String(i).padStart(5, '0'),
    game_date: day,
    home_team_master_id: 'a',
    away_team_master_id: 'b',
    source_game_id: String(i),
    heuristic_prediction_status: 'completed',
    source_system: 'database_games',
  }));
  const saved = new Set(rows.slice(0, existingCount).map((r) => r.id));
  const terminals: Array<{ kind: string; start?: number; payload?: Record<string, unknown> }> = [];
  let mismatch = false,
    refuse = false;
  const client = {
    from(table: string) {
      const predicates: Array<(r: Record<string, unknown>) => boolean> = [];
      const query = {
        select() {
          return query;
        },
        eq(key: string, value: unknown) {
          predicates.push((r) => r[key] === value);
          return query;
        },
        gt(key: string, value: string) {
          predicates.push((r) => String(r[key]) > value);
          return query;
        },
        lte(key: string, value: string) {
          predicates.push((r) => String(r[key]) <= value);
          return query;
        },
        order() {
          return query;
        },
        async range(start: number, end: number) {
          terminals.push({ kind: 'queue', start });
          return { data: rows.filter((r) => predicates.every((p) => p(r))).slice(start, end + 1), error: null };
        },
        async maybeSingle() {
          expect(table).toBe('compare_monitoring_forecasts');
          const records = [...saved].map((id) => ({ baseline_forecast_id: id, monitor_signature: signature }));
          return { data: records.find((r) => predicates.every((p) => p(r))) ?? null, error: null };
        },
      };
      return query;
    },
    async rpc(name: string, payload: Record<string, string>) {
      terminals.push({ kind: name, payload });
      if (name === 'register_compare_monitor') {
        signature = createHash('sha256').update(payload.p_manifest).digest('hex');
        return { data: mismatch ? 'wrong' : signature, error: null };
      }
      expect(name).toBe('freeze_compare_monitor');
      if (refuse) return { data: null, error: { message: 'private failure details' } };
      saved.add(payload.p_baseline);
      return { data: true, error: null };
    },
  };
  let signature = '';
  return {
    client: client as unknown as SupabaseClient,
    terminals,
    saved,
    mismatch: () => {
      mismatch = true;
    },
    refuse: () => {
      refuse = true;
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  doubles.predict.mockResolvedValue({
    response: { prediction: { winProbabilityA: 0.6 } },
    shadowContext: { calibration: { margin: {} }, frozenEvidence: { games: [] } },
  });
  doubles.run.mockReturnValue({
    variants: { '1': { winProbabilityA: 0.6 } },
    receipt: { algorithm_hash: 'b'.repeat(64), aa_parity: true },
  });
  doubles.create.mockResolvedValue({ run: doubles.run, close: doubles.close });
});

it('preview performs no registration, research or writes', async () => {
  const db = database();
  const result = await captureMonitoring(db.client, { limit: 20, execute: false });
  expect(result.selected).toBe(2);
  expect(db.terminals.every((c) => c.kind === 'queue')).toBe(true);
  expect(doubles.predict).not.toHaveBeenCalled();
  expect(doubles.create).not.toHaveBeenCalled();
});

it('existing records do not consume the cap and the queue paginates', async () => {
  const db = database(1002, 1000);
  const result = await captureMonitoring(db.client, { limit: 1, execute: true });
  expect(result.existing).toBe(1000);
  expect(result.captured).toBe(1);
  expect(db.terminals.filter((c) => c.kind === 'queue').map((c) => c.start)).toEqual([0, 1000]);
  expect(doubles.create).toHaveBeenCalledTimes(1);
  expect(doubles.close).toHaveBeenCalledTimes(1);
  const captured = db.terminals.find((c) => c.kind === 'freeze_compare_monitor')!;
  expect(captured.payload!.p_baseline).toBe('01000');
  expect(JSON.parse(captured.payload!.p_payload as string).receipt.aa_parity).toBe(true);
});

it('refuses a registration mismatch before predicting', async () => {
  const db = database();
  db.mismatch();
  await expect(captureMonitoring(db.client, { limit: 20, execute: true })).rejects.toThrow('registration');
  expect(doubles.predict).not.toHaveBeenCalled();
});

it('counts failed writes and reuses one research runtime', async () => {
  const db = database();
  db.refuse();
  const result = await captureMonitoring(db.client, { limit: 20, execute: true });
  expect(result.errors).toBe(2);
  expect(result.captured).toBe(0);
  expect(doubles.create).toHaveBeenCalledTimes(1);
  expect(doubles.close).toHaveBeenCalledTimes(1);
});
