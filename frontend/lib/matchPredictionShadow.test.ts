import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { insertMock, fromMock, createServiceSupabaseMock } = vi.hoisted(() => ({
  insertMock: vi.fn(),
  fromMock: vi.fn(),
  createServiceSupabaseMock: vi.fn(),
}));

vi.mock('server-only', () => ({}));

vi.mock('@/lib/supabase/service', () => ({
  createServiceSupabase: createServiceSupabaseMock,
}));

import { maybeLogMatchPredictionShadow } from './matchPredictionShadow';

describe('maybeLogMatchPredictionShadow', () => {
  const originalEnv = process.env.ENABLE_MATCH_PREDICTION_SHADOW_LOGGING;

  beforeEach(() => {
    vi.clearAllMocks();
    insertMock.mockResolvedValue({ error: null });
    fromMock.mockReturnValue({ insert: insertMock });
    createServiceSupabaseMock.mockReturnValue({ from: fromMock });
  });

  afterEach(() => {
    if (originalEnv == null) {
      delete process.env.ENABLE_MATCH_PREDICTION_SHADOW_LOGGING;
    } else {
      process.env.ENABLE_MATCH_PREDICTION_SHADOW_LOGGING = originalEnv;
    }
  });

  it('skips writes when shadow logging is disabled', async () => {
    process.env.ENABLE_MATCH_PREDICTION_SHADOW_LOGGING = 'false';

    await maybeLogMatchPredictionShadow({
      userId: 'user-1',
      teamAId: '11111111-1111-1111-1111-111111111111',
      teamBId: '22222222-2222-2222-2222-222222222222',
      requestIp: '127.0.0.1',
      response: {
        teamA: { team_id_master: 'a', team_name: 'Alpha', club_name: 'Alpha Club' },
        teamB: { team_id_master: 'b', team_name: 'Beta', club_name: 'Beta Club' },
        prediction: {} as never,
        explanation: {} as never,
      },
      shadowContext: {
        predictorVersion: 'heuristic_v3_shadow_ready',
        resolvedTeamAIds: ['a'],
        resolvedTeamBIds: ['b'],
        relevantGameIds: ['g1'],
        relevantGameCount: 1,
        teamAInput: {} as never,
        teamBInput: {} as never,
      },
    });

    expect(createServiceSupabaseMock).not.toHaveBeenCalled();
  });

  it('writes a shadow payload when enabled', async () => {
    process.env.ENABLE_MATCH_PREDICTION_SHADOW_LOGGING = 'true';

    await maybeLogMatchPredictionShadow({
      userId: 'user-1',
      teamAId: '11111111-1111-1111-1111-111111111111',
      teamBId: '22222222-2222-2222-2222-222222222222',
      requestIp: '127.0.0.1',
      response: {
        teamA: { team_id_master: 'a', team_name: 'Alpha', club_name: 'Alpha Club' },
        teamB: { team_id_master: 'b', team_name: 'Beta', club_name: 'Beta Club' },
        prediction: {} as never,
        explanation: {} as never,
      },
      shadowContext: {
        predictorVersion: 'heuristic_v3_shadow_ready',
        resolvedTeamAIds: ['a'],
        resolvedTeamBIds: ['b'],
        relevantGameIds: ['g1'],
        relevantGameCount: 1,
        teamAInput: {} as never,
        teamBInput: {} as never,
      },
    });

    expect(createServiceSupabaseMock).toHaveBeenCalledTimes(1);
    expect(fromMock).toHaveBeenCalledWith('match_prediction_shadow_log');
    expect(insertMock).toHaveBeenCalledTimes(1);
  });
});
