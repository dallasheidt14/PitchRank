import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockPredictMatch, mockExplainMatch, mockWarmMatchPredictorCalibration } = vi.hoisted(() => ({
  mockPredictMatch: vi.fn(),
  mockExplainMatch: vi.fn(),
  mockWarmMatchPredictorCalibration: vi.fn(),
}));

vi.mock('server-only', () => ({}));

vi.mock('./matchPredictor', () => ({
  predictMatch: mockPredictMatch,
  warmMatchPredictorCalibration: mockWarmMatchPredictorCalibration,
}));

vi.mock('./matchExplainer', () => ({
  explainMatch: mockExplainMatch,
}));

import { buildMatchPrediction } from './matchPredictionService';

const TEAM_A_ID = '11111111-1111-1111-1111-111111111111';
const TEAM_B_ID = '22222222-2222-2222-2222-222222222222';
const TEAM_A_DEPRECATED = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';

type QueryState = {
  table: string;
  filters: Record<string, unknown>;
  orFilter?: string;
};

function createMockSupabase() {
  const resolveQuery = (state: QueryState) => {
    switch (state.table) {
      case 'team_merge_map':
        if (state.filters.deprecated_team_id === TEAM_A_DEPRECATED) {
          return { data: { canonical_team_id: TEAM_A_ID }, error: null };
        }
        if (state.filters.canonical_team_id === TEAM_A_ID) {
          return { data: [{ deprecated_team_id: TEAM_A_DEPRECATED }], error: null };
        }
        return { data: [], error: null };
      case 'teams':
        if (state.filters.team_id_master === TEAM_A_ID) {
          return {
            data: {
              team_id_master: TEAM_A_ID,
              team_name: 'Alpha FC',
              club_name: 'Alpha',
              state: 'TX',
              state_code: 'TX',
              age_group: 'u12',
              gender: 'Male',
              last_scraped_at: null,
            },
            error: null,
          };
        }
        if (state.filters.team_id_master === TEAM_B_ID) {
          return {
            data: {
              team_id_master: TEAM_B_ID,
              team_name: 'Beta FC',
              club_name: 'Beta',
              state: 'CA',
              state_code: 'CA',
              age_group: 'u12',
              gender: 'Male',
              last_scraped_at: null,
            },
            error: null,
          };
        }
        return { data: null, error: null };
      case 'rankings_view':
        if (state.filters.team_id_master === TEAM_A_ID) {
          return {
            data: {
              age: 12,
              gender: 'M',
              rank_in_cohort_final: 12,
              power_score_final: 0.81,
              glicko_rating: 1680,
              glicko_rd: 48,
              glicko_volatility: 0.04,
              sos_norm: 0.72,
              offense_norm: 0.8,
              defense_norm: 0.76,
              wins: 18,
              losses: 2,
              draws: 1,
              games_played: 21,
            },
            error: null,
          };
        }
        if (state.filters.team_id_master === TEAM_B_ID) {
          return {
            data: {
              age: 12,
              gender: 'M',
              rank_in_cohort_final: 58,
              power_score_final: 0.62,
              glicko_rating: 1542,
              glicko_rd: 71,
              glicko_volatility: 0.06,
              sos_norm: 0.51,
              offense_norm: 0.58,
              defense_norm: 0.55,
              wins: 11,
              losses: 8,
              draws: 1,
              games_played: 20,
            },
            error: null,
          };
        }
        return { data: null, error: null };
      case 'state_rankings_view':
      case 'rankings_full':
      case 'team_predictive_view':
        return { data: null, error: null };
      case 'games':
        return {
          data: [
            {
              id: 'game-1',
              game_date: '2026-03-10',
              home_team_master_id: TEAM_A_DEPRECATED,
              away_team_master_id: TEAM_B_ID,
              home_score: 3,
              away_score: 1,
            },
            {
              id: 'game-2',
              game_date: '2026-02-25',
              home_team_master_id: TEAM_A_ID,
              away_team_master_id: TEAM_B_ID,
              home_score: 2,
              away_score: 0,
            },
          ],
          error: null,
        };
      default:
        return { data: null, error: null };
    }
  };

  const createBuilder = (table: string) => {
    const state: QueryState = { table, filters: {} };
    const builder = {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn((field: string, value: unknown) => {
        state.filters[field] = value;
        return builder;
      }),
      gte: vi.fn((field: string, value: unknown) => {
        state.filters[field] = value;
        return builder;
      }),
      not: vi.fn().mockReturnThis(),
      or: vi.fn((value: string) => {
        state.orFilter = value;
        return builder;
      }),
      order: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn(async () => resolveQuery(state)),
      then: (resolve: (value: unknown) => unknown, reject?: (reason: unknown) => unknown) =>
        Promise.resolve(resolveQuery(state)).then(resolve, reject),
    };

    return builder;
  };

  return {
    from: vi.fn((table: string) => createBuilder(table)),
  };
}

describe('buildMatchPrediction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockWarmMatchPredictorCalibration.mockResolvedValue(undefined);
    mockPredictMatch.mockReturnValue({
      predictedWinner: 'team_a',
      winProbabilityA: 0.77,
      winProbabilityB: 0.23,
      drawProbability: 0,
      expectedScore: { teamA: 3, teamB: 1 },
      expectedMargin: 2,
      confidence: 'high',
      confidence_score: 0.81,
      components: {
        powerDiff: 0.19,
        strengthSignal: 0.21,
        sosDiff: 0.21,
        formDiffRaw: 1.2,
        formDiffNorm: 0.11,
        matchupAdvantage: 0.18,
        compositeDiff: 0.28,
        mismatchScore: 0.35,
      },
      formA: 1.2,
      formB: -0.1,
      h2h: {
        gamesPlayed: 2,
        avgMargin: 2,
      },
    });
    mockExplainMatch.mockReturnValue({
      summary: 'Alpha FC is the clear favorite at 77% win probability',
      factors: [],
      keyInsights: ['Mocked explanation'],
      predictionQuality: {
        confidence: 'high',
        reliability: 'Mocked reliability',
      },
    });
  });

  it('includes merged-team games when building the prediction context', async () => {
    const supabase = createMockSupabase();

    const result = await buildMatchPrediction(supabase as never, TEAM_A_ID, TEAM_B_ID);

    expect(result.teamA.team_name).toBe('Alpha FC');
    expect(mockPredictMatch).toHaveBeenCalledTimes(1);

    const [, , predictionGames] = mockPredictMatch.mock.calls[0];
    expect(Array.isArray(predictionGames)).toBe(true);
    expect(predictionGames).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          home_team_master_id: TEAM_A_DEPRECATED,
          away_team_master_id: TEAM_B_ID,
          home_score: 3,
          away_score: 1,
        }),
      ])
    );
  });

  it('rejects teams that resolve to the same canonical identity', async () => {
    const supabase = createMockSupabase();

    await expect(buildMatchPrediction(supabase as never, TEAM_A_ID, TEAM_A_DEPRECATED)).rejects.toMatchObject({
      message: 'Please choose two different teams.',
      statusCode: 400,
    });
  });
});
