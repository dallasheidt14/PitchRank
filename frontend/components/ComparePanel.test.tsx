import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react-dom/test-utils';

const {
  mockUseTeam,
  mockUseCommonOpponents,
  mockUseMatchPrediction,
} = vi.hoisted(() => ({
  mockUseTeam: vi.fn(),
  mockUseCommonOpponents: vi.fn(),
  mockUseMatchPrediction: vi.fn(),
}));

vi.mock('@/lib/hooks', () => ({
  useTeam: mockUseTeam,
  useCommonOpponents: mockUseCommonOpponents,
  useMatchPrediction: mockUseMatchPrediction,
}));

vi.mock('@/lib/events', () => ({
  trackCompareOpened: vi.fn(),
  trackComparisonGenerated: vi.fn(),
  trackPredictionViewed: vi.fn(),
  trackTeamsSwapped: vi.fn(),
}));

vi.mock('@/components/ui/tooltip', async () => {
  const ReactModule = await import('react');
  return {
    Tooltip: ({ children }: { children: React.ReactNode }) => ReactModule.createElement('div', null, children),
    TooltipTrigger: ({ children }: { children: React.ReactNode }) => ReactModule.createElement('div', null, children),
    TooltipContent: ({ children }: { children: React.ReactNode }) => ReactModule.createElement('div', null, children),
  };
});

vi.mock('recharts', async () => {
  const ReactModule = await import('react');
  const passthrough = ({ children }: { children?: React.ReactNode }) => ReactModule.createElement('div', null, children);

  return {
    RadarChart: passthrough,
    Radar: passthrough,
    PolarGrid: passthrough,
    PolarAngleAxis: passthrough,
    PolarRadiusAxis: passthrough,
    ResponsiveContainer: passthrough,
    Legend: passthrough,
    Tooltip: passthrough,
  };
});

vi.mock('./TeamSelector', async () => {
  const ReactModule = await import('react');

  return {
    TeamSelector: ({
      label,
      onChange,
    }: {
      label: string;
      onChange: (id: string | null, team: { team_name: string }) => void;
    }) => {
      ReactModule.useEffect(() => {
        if (label === 'Team 1') {
          onChange('team-a', { team_name: 'Alpha FC' });
        } else if (label === 'Team 2') {
          onChange('team-b', { team_name: 'Beta FC' });
        }
      }, []);

      return ReactModule.createElement('div', null, label);
    },
  };
});

import { ComparePanel } from './ComparePanel';

const teamA = {
  team_id_master: 'team-a',
  team_name: 'Alpha FC',
  club_name: 'Alpha',
  state: 'TX',
  age: 12,
  gender: 'M',
  rank_in_cohort_final: 12,
  rank_in_state_final: 2,
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
  total_games_played: 21,
  total_wins: 18,
  total_losses: 2,
  total_draws: 1,
  win_percentage: 88.1,
  last_scraped_at: null,
};

const teamB = {
  team_id_master: 'team-b',
  team_name: 'Beta FC',
  club_name: 'Beta',
  state: 'CA',
  age: 12,
  gender: 'M',
  rank_in_cohort_final: 58,
  rank_in_state_final: 11,
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
  total_games_played: 20,
  total_wins: 11,
  total_losses: 8,
  total_draws: 1,
  win_percentage: 57.5,
  last_scraped_at: null,
};

function renderComparePanel() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

async function flushRender(root: Root) {
  await act(async () => {
    root.render(React.createElement(ComparePanel));
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('ComparePanel', () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    vi.clearAllMocks();

    mockUseTeam.mockImplementation((id: string) => ({
      data: id === 'team-a' ? teamA : id === 'team-b' ? teamB : null,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    }));

    mockUseCommonOpponents.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    mockUseMatchPrediction.mockImplementation((teamAId: string | null, teamBId: string | null) => ({
      data:
        teamAId && teamBId
          ? {
              teamA: { team_id_master: 'team-a', team_name: 'Alpha FC', club_name: 'Alpha' },
              teamB: { team_id_master: 'team-b', team_name: 'Beta FC', club_name: 'Beta' },
              prediction: {
                predictedWinner: 'team_a',
                winProbabilityA: 0.74,
                winProbabilityB: 0.26,
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
              },
              explanation: {
                summary: 'Alpha FC is the clear favorite at 74% win probability',
                factors: [],
                keyInsights: ['High confidence prediction'],
                predictionQuality: {
                  confidence: 'high',
                  reliability: 'Based on current calibrated model output',
                },
              },
            }
          : null,
      isLoading: false,
      isError: false,
      error: null,
    }));

    const render = renderComparePanel();
    container = render.container;
    root = render.root;
  });

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }

    container?.remove();
    root = null;
    container = null;
  });

  it('renders the match prediction card when prediction data is available', async () => {
    await flushRender(root!);

    expect(container?.textContent).toContain('Match Prediction');
    expect(container?.textContent).toContain('Alpha FC is the clear favorite at 74% win probability');
  });

  it('renders an explicit error state when the prediction query fails', async () => {
    mockUseMatchPrediction.mockImplementation((teamAId: string | null, teamBId: string | null) => ({
      data: null,
      isLoading: false,
      isError: !!teamAId && !!teamBId,
      error: teamAId && teamBId ? new Error('Route unavailable') : null,
    }));

    await flushRender(root!);

    expect(container?.textContent).toContain('Unable to analyze this matchup right now.');
    expect(container?.textContent).toContain('Route unavailable');
  });
});
