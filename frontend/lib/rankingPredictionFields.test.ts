import type { SupabaseClient } from '@supabase/supabase-js';
import { describe, expect, it, vi } from 'vitest';

import { enrichRankingPredictionFields } from './rankingPredictionFields';

function mockSupabase(result: { data: unknown; error: unknown }): SupabaseClient {
  const inFilter = vi.fn().mockResolvedValue(result);
  const select = vi.fn().mockReturnValue({ in: inFilter });
  return { from: vi.fn().mockReturnValue({ select }) } as unknown as SupabaseClient;
}

describe('enrichRankingPredictionFields', () => {
  it('adds the compatibility score and display-scale version by team id', async () => {
    const rows = [
      { team_id_master: 'a', power_score_final: 0.64 },
      { team_id_master: 'b', power_score_final: 0.49 },
    ];
    const supabase = mockSupabase({
      data: [
        {
          team_id: 'a',
          prediction_power_score: 0.71,
          power_score_scale_version: 'age-gender-v1-2026-09-25',
        },
        {
          team_id: 'b',
          prediction_power_score: 0.56,
          power_score_scale_version: 'age-gender-v1-2026-09-25',
        },
      ],
      error: null,
    });

    await expect(enrichRankingPredictionFields(supabase, rows)).resolves.toEqual([
      {
        ...rows[0],
        prediction_power_score: 0.71,
        power_score_scale_version: 'age-gender-v1-2026-09-25',
      },
      {
        ...rows[1],
        prediction_power_score: 0.56,
        power_score_scale_version: 'age-gender-v1-2026-09-25',
      },
    ]);
  });

  it('keeps legacy ranking rows unchanged before the migration is available', async () => {
    const rows = [{ team_id_master: 'a', power_score_final: 0.71 }];
    const supabase = mockSupabase({
      data: null,
      error: { code: '42703', message: 'column prediction_power_score does not exist' },
    });

    await expect(enrichRankingPredictionFields(supabase, rows)).resolves.toBe(rows);
  });
});
