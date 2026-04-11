import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NextRequest } from 'next/server';
import { AppError } from '@/lib/errors';

vi.mock('server-only', () => ({}));

const { mockRequirePremium, mockCheckRateLimit, mockBuildMatchPrediction, mockMaybeLogShadow } = vi.hoisted(() => ({
  mockRequirePremium: vi.fn(),
  mockCheckRateLimit: vi.fn(),
  mockBuildMatchPrediction: vi.fn(),
  mockMaybeLogShadow: vi.fn(),
}));

vi.mock('@/lib/api/requirePremium', () => ({
  requirePremium: mockRequirePremium,
}));

vi.mock('@/lib/api/rateLimit', () => ({
  checkRateLimit: mockCheckRateLimit,
}));

vi.mock('@/lib/matchPredictionService', () => ({
  buildMatchPredictionWithShadowContext: mockBuildMatchPrediction,
}));

vi.mock('@/lib/matchPredictionShadow', () => ({
  maybeLogMatchPredictionShadow: mockMaybeLogShadow,
}));

import { POST } from '../route';

const TEAM_A_ID = '11111111-1111-1111-1111-111111111111';
const TEAM_B_ID = '22222222-2222-2222-2222-222222222222';

function makeRequest(body: Record<string, unknown>) {
  return new Request('http://localhost/api/match-prediction', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-forwarded-for': '127.0.0.1',
    },
    body: JSON.stringify(body),
  }) as NextRequest;
}

describe('POST /api/match-prediction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockReturnValue(true);
    mockRequirePremium.mockResolvedValue({
      user: { id: 'user-1', email: 'premium@example.com' },
      supabase: { from: vi.fn() },
      error: null,
    });
  });

  it('returns 429 when the IP is rate limited', async () => {
    mockCheckRateLimit.mockReturnValue(false);

    const response = await POST(makeRequest({ teamAId: TEAM_A_ID, teamBId: TEAM_B_ID }));

    expect(response.status).toBe(429);
    await expect(response.json()).resolves.toEqual({
      error: 'Too many requests. Please try again later.',
    });
  });

  it('returns 400 for an invalid Team A ID', async () => {
    const response = await POST(makeRequest({ teamAId: 'bad-id', teamBId: TEAM_B_ID }));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: 'Invalid Team A ID' });
  });

  it('returns 400 when the same team is selected twice', async () => {
    const response = await POST(makeRequest({ teamAId: TEAM_A_ID, teamBId: TEAM_A_ID }));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: 'Please choose two different teams.' });
  });

  it('returns 401 when the request is unauthenticated', async () => {
    mockRequirePremium.mockResolvedValue({
      user: null,
      supabase: null,
      error: new Response(JSON.stringify({ error: 'Not authenticated' }), { status: 401 }),
    });

    const response = await POST(makeRequest({ teamAId: TEAM_A_ID, teamBId: TEAM_B_ID }));

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: 'Not authenticated' });
  });

  it('returns 403 when the user is not premium', async () => {
    mockRequirePremium.mockResolvedValue({
      user: null,
      supabase: null,
      error: new Response(JSON.stringify({ error: 'Premium required' }), { status: 403 }),
    });

    const response = await POST(makeRequest({ teamAId: TEAM_A_ID, teamBId: TEAM_B_ID }));

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ error: 'Premium required' });
  });

  it('returns a prediction payload for a valid premium request', async () => {
    mockBuildMatchPrediction.mockResolvedValue({
      response: {
        teamA: { team_id_master: TEAM_A_ID, team_name: 'Alpha FC', club_name: 'Alpha' },
        teamB: { team_id_master: TEAM_B_ID, team_name: 'Beta FC', club_name: 'Beta' },
        prediction: {
          predictedWinner: 'team_a',
          winProbabilityA: 0.71,
          winProbabilityB: 0.29,
          expectedScore: { teamA: 3, teamB: 1 },
          expectedMargin: 2,
          confidence: 'high',
          confidence_score: 0.82,
          components: {
            powerDiff: 0.1,
            strengthSignal: 0.1,
            sosDiff: 0.04,
            formDiffRaw: 1.2,
            formDiffNorm: 0.1,
            matchupAdvantage: 0.08,
            compositeDiff: 0.22,
            mismatchScore: 0.31,
          },
          formA: 1.2,
          formB: -0.2,
        },
        explanation: {
          summary: 'Alpha FC has the edge with 71% win probability',
          factors: [],
          keyInsights: ['High confidence prediction'],
          predictionQuality: {
            confidence: 'high',
            reliability: 'Based on current calibrated model output',
          },
        },
      },
      shadowContext: {},
    });

    const response = await POST(makeRequest({ teamAId: TEAM_A_ID, teamBId: TEAM_B_ID }));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(mockBuildMatchPrediction).toHaveBeenCalledTimes(1);
    expect(body.teamA.team_name).toBe('Alpha FC');
    expect(body.teamB.team_name).toBe('Beta FC');
    expect(body.prediction.predictedWinner).toBe('team_a');
    expect(body.explanation.summary).toContain('Alpha FC');
  });

  it('maps service availability failures to the route status code', async () => {
    mockBuildMatchPrediction.mockRejectedValue(
      new AppError(
        'Prediction unavailable. Match predictions rely on current ranking data for both teams.',
        'prediction_unavailable',
        422
      )
    );

    const response = await POST(makeRequest({ teamAId: TEAM_A_ID, teamBId: TEAM_B_ID }));

    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toEqual({
      error: 'Prediction unavailable. Match predictions rely on current ranking data for both teams.',
    });
  });
});
