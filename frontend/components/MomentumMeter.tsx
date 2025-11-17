'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useTeamGames, useTeam } from '@/lib/hooks';
import { useMemo, useState, useEffect } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { api } from '@/lib/api';
import type { GameWithTeams } from '@/lib/types';

interface MomentumMeterProps {
  teamId: string;
}

// Constants from v53e backend
const PERFORMANCE_GOAL_SCALE = 5.0; // Expected goal margin per 1.0 power difference
const PERFORMANCE_THRESHOLD = 2.0; // Noise threshold for quality detection

interface GameQuality {
  game: GameWithTeams;
  opponentName: string;
  opponentRank: number | null;
  opponentPower: number | null;
  teamScore: number;
  oppScore: number;
  result: 'W' | 'L' | 'D';
  goalDiff: number;
  expectedMargin: number;
  performanceDelta: number;
  qualityType: 'dominant-win' | 'quality-win' | 'competitive-loss' | 'expected-loss' | 'bad-loss' | 'standard' | 'expected-win' | 'struggle-win';
  qualityIcon: string;
  rawPoints: number;
  qualityMultiplier: number;
  totalPoints: number;
}

/**
 * Interpolate color from red → gray → lime based on score (0-100)
 */
function interpolateMomentumColor(score: number): string {
  // Red (low) → Gray (mid) → Lime (high)
  if (score < 33) {
    // Red to gray: score 0-33
    const t = score / 33;
    // Red: hsl(0, 70%, 50%) → Gray: hsl(0, 0%, 50%)
    return `hsl(0, ${70 * (1 - t)}%, 50%)`;
  } else if (score < 66) {
    // Gray: score 33-66
    return 'hsl(0, 0%, 50%)';
  } else {
    // Gray to lime: score 66-100
    const t = (score - 66) / 34;
    // Gray: hsl(0, 0%, 50%) → Lime: hsl(120, 70%, 50%)
    return `hsl(${120 * t}, ${70 * t}%, 50%)`;
  }
}

/**
 * Calculate quality-adjusted momentum from recent games
 */
async function calculateQualityMomentum(
  teamId: string,
  teamPower: number | null,
  teamRank: number | null,
  games: GameWithTeams[],
  numberOfGames: number = 5
): Promise<{
  score: number;
  gamesAnalyzed: GameQuality[];
  record: { wins: number; losses: number; draws: number };
}> {
  // Take the most recent N games
  const recentGames = games.slice(0, numberOfGames);

  if (recentGames.length === 0) {
    return { score: 50, gamesAnalyzed: [], record: { wins: 0, losses: 0, draws: 0 } };
  }

  // Get opponent team IDs
  const opponentIds = recentGames
    .map(game => {
      const oppId = game.home_team_master_id === teamId
        ? game.away_team_master_id
        : game.home_team_master_id;
      return oppId;
    })
    .filter((id): id is string => id !== null);

  // Fetch opponent rankings
  const opponentRankings = await api.getTeamRankings(opponentIds);

  // Analyze each game
  const gamesAnalyzed: GameQuality[] = [];
  let wins = 0, losses = 0, draws = 0;

  for (const game of recentGames) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;
    const opponentId = isHome ? game.away_team_master_id : game.home_team_master_id;
    const opponentName = isHome ? game.away_team_name : game.home_team_name;

    if (teamScore === null || oppScore === null || !opponentId) {
      continue;
    }

    const goalDiff = teamScore - oppScore;
    let result: 'W' | 'L' | 'D';
    if (goalDiff > 0) {
      result = 'W';
      wins++;
    } else if (goalDiff < 0) {
      result = 'L';
      losses++;
    } else {
      result = 'D';
      draws++;
    }

    const opponentRanking = opponentRankings.get(opponentId);
    const opponentPower = opponentRanking?.power_score_final ?? null;
    const opponentRank = opponentRanking?.rank_in_cohort_final ?? null;

    // Calculate expected margin and performance delta
    let expectedMargin = 0;
    let performanceDelta = 0;
    let powerDiff = 0;

    if (teamPower !== null && opponentPower !== null) {
      powerDiff = teamPower - opponentPower;
      expectedMargin = PERFORMANCE_GOAL_SCALE * powerDiff;
      performanceDelta = goalDiff - expectedMargin;
    }

    // Base points for result
    let rawPoints = 0;
    if (result === 'W') rawPoints = 100;
    else if (result === 'D') rawPoints = 50;
    else rawPoints = 0;

    // Quality multiplier based on opponent strength
    let qualityMultiplier = 1.0;
    let qualityType: GameQuality['qualityType'] = 'standard';
    let qualityIcon = '➡️';

    if (opponentPower !== null && teamPower !== null) {
      const STRENGTH_THRESHOLD = 0.15; // Power difference to be considered "much stronger/weaker"

      // Also use rank-based classification as fallback
      // If opponent rank is significantly worse (>3x or >500 ranks), they're weaker even if power is similar
      let isWeakerByRank = false;
      let isStrongerByRank = false;
      if (teamRank !== null && opponentRank !== null) {
        const rankRatio = opponentRank / teamRank;
        const rankDiff = opponentRank - teamRank;

        // Opponent is weaker if their rank number is much higher (worse)
        if (rankRatio > 3.0 || rankDiff > 500) {
          isWeakerByRank = true;
        }
        // Opponent is stronger if their rank number is much lower (better)
        else if (rankRatio < 0.33 || rankDiff < -500) {
          isStrongerByRank = true;
        }
      }

      if (powerDiff < -STRENGTH_THRESHOLD || isStrongerByRank) {
        // Opponent is significantly stronger
        qualityIcon = '⬆️';

        if (result === 'W') {
          // Beat a stronger opponent
          if (performanceDelta > PERFORMANCE_THRESHOLD) {
            qualityType = 'dominant-win';
            qualityMultiplier = 1.8; // Huge boost for dominant upset
          } else {
            qualityType = 'quality-win';
            qualityMultiplier = 1.5; // Big boost for quality win
          }
        } else if (result === 'L') {
          // Lost to stronger opponent
          if (performanceDelta > -PERFORMANCE_THRESHOLD) {
            qualityType = 'competitive-loss';
            qualityMultiplier = 0.7; // Small penalty for competitive loss
          } else {
            qualityType = 'expected-loss';
            qualityMultiplier = 0.5; // Moderate penalty for expected loss
          }
        } else {
          // Draw vs stronger opponent
          qualityMultiplier = 1.3;
        }
      } else if (powerDiff > STRENGTH_THRESHOLD || isWeakerByRank) {
        // Opponent is significantly weaker
        qualityIcon = '⬇️';

        if (result === 'W') {
          // Beat a weaker opponent
          if (performanceDelta < -PERFORMANCE_THRESHOLD || goalDiff <= 1) {
            // Struggled against weak team - RED FLAG
            qualityType = 'struggle-win';
            qualityMultiplier = 0.6; // Penalty for struggling against weak opponent
          } else if (performanceDelta > PERFORMANCE_THRESHOLD) {
            // Beat them as expected (dominantly)
            qualityType = 'expected-win';
            qualityMultiplier = 0.9; // Neutral - just doing what's expected
          } else {
            // Standard win against weaker team
            qualityType = 'expected-win';
            qualityMultiplier = 0.85; // Expected win but counts less
          }
        } else if (result === 'L') {
          // Lost to weaker opponent - BAD
          qualityType = 'bad-loss';
          qualityMultiplier = 0.2; // Heavy penalty for bad loss
        } else {
          // Draw vs weaker opponent
          qualityMultiplier = 0.6; // Should have won
        }
      } else {
        // Similar strength opponents
        qualityIcon = '➡️';
        qualityMultiplier = 1.0;

        if (result === 'W' && performanceDelta > PERFORMANCE_THRESHOLD) {
          // Dominant win against similar opponent
          qualityType = 'dominant-win';
          qualityMultiplier = 1.3; // Good boost for dominant win vs peer
        } else if (result === 'W') {
          qualityType = 'quality-win';
          qualityMultiplier = 1.1;
        } else if (result === 'L' && performanceDelta < -PERFORMANCE_THRESHOLD) {
          qualityMultiplier = 0.8;
        }
      }
    }

    // Add performance bonus/penalty (normalized)
    const performanceBonus = Math.max(-10, Math.min(10, (performanceDelta / 2) * 5));
    const totalPoints = (rawPoints * qualityMultiplier) + performanceBonus;

    gamesAnalyzed.push({
      game,
      opponentName: opponentName || 'Unknown',
      opponentRank,
      opponentPower,
      teamScore,
      oppScore,
      result,
      goalDiff,
      expectedMargin,
      performanceDelta,
      qualityType,
      qualityIcon,
      rawPoints,
      qualityMultiplier,
      totalPoints,
    });
  }

  // Calculate final momentum score (0-100)
  const totalPoints = gamesAnalyzed.reduce((sum, g) => sum + g.totalPoints, 0);
  const maxPossiblePoints = numberOfGames * 100 * 1.8; // Max if all dominant upsets
  const normalizedScore = (totalPoints / maxPossiblePoints) * 100;
  const score = Math.max(0, Math.min(100, normalizedScore));

  return {
    score,
    gamesAnalyzed,
    record: { wins, losses, draws },
  };
}

/**
 * MomentumMeter component - displays quality-adjusted team momentum
 */
export function MomentumMeter({ teamId }: MomentumMeterProps) {
  const { data: gamesData, isLoading: gamesLoading, isError: gamesError, error: gamesErrorObj, refetch } = useTeamGames(teamId, 12);
  const { data: teamData, isLoading: teamLoading } = useTeam(teamId);

  const [animatedScore, setAnimatedScore] = useState(50);
  const [momentumData, setMomentumData] = useState<{
    score: number;
    gamesAnalyzed: GameQuality[];
    record: { wins: number; losses: number; draws: number };
  } | null>(null);

  // Calculate momentum when games data is available
  useEffect(() => {
    if (!gamesData?.games || gamesData.games.length === 0) {
      setMomentumData(null);
      return;
    }

    let isMounted = true;
    const teamPower = teamData?.power_score_final ?? null;
    const teamRank = teamData?.rank_in_cohort_final ?? null;

    calculateQualityMomentum(teamId, teamPower, teamRank, gamesData.games, 8)
      .then(result => {
        if (isMounted) {
          setMomentumData(result);
        }
      })
      .catch(error => {
        console.error('Error calculating momentum:', error);
        if (isMounted) {
          setMomentumData(null);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [gamesData, teamData, teamId]);

  // Animate score change
  useEffect(() => {
    if (!momentumData) return;

    const targetScore = momentumData.score;
    const duration = 1000; // 1 second animation
    const startTime = Date.now();
    const startScore = animatedScore;

    const animate = () => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out animation
      const easeOut = 1 - Math.pow(1 - progress, 3);
      const currentScore = startScore + (targetScore - startScore) * easeOut;

      setAnimatedScore(currentScore);

      if (progress < 1) {
        requestAnimationFrame(animate);
      } else {
        setAnimatedScore(targetScore);
      }
    };

    // Only start animation if target score is different
    if (Math.abs(targetScore - animatedScore) > 0.1) {
      requestAnimationFrame(animate);
    } else {
      setAnimatedScore(targetScore);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [momentumData?.score]);

  const momentumLabel = useMemo(() => {
    if (!momentumData) return 'Neutral';
    const score = momentumData.score;
    if (score >= 80) return 'Hot Streak';
    if (score >= 60) return 'Building Momentum';
    if (score >= 40) return 'Mixed Results';
    if (score >= 20) return 'Struggling';
    return 'Slumping';
  }, [momentumData]);

  const momentumColor = useMemo(() => {
    return interpolateMomentumColor(animatedScore);
  }, [animatedScore]);

  if (gamesLoading || teamLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Momentum</CardTitle>
          <CardDescription>Last 8 Games Quality-adjusted performance trend</CardDescription>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={200} />
        </CardContent>
      </Card>
    );
  }

  if (gamesError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Momentum</CardTitle>
          <CardDescription>Last 8 Games Quality-adjusted performance trend</CardDescription>
        </CardHeader>
        <CardContent>
          <ErrorDisplay error={gamesErrorObj} retry={refetch} fallback={
            <div className="h-48 flex items-center justify-center text-muted-foreground">
              <p>Insufficient data to calculate momentum</p>
            </div>
          } />
        </CardContent>
      </Card>
    );
  }

  if (!momentumData || momentumData.gamesAnalyzed.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Momentum</CardTitle>
          <CardDescription>Last 8 Games Quality-adjusted performance trend</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-48 flex items-center justify-center text-muted-foreground">
            <p>Insufficient data to calculate momentum</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const { record, gamesAnalyzed } = momentumData;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Recent Momentum</CardTitle>
            <CardDescription>Last 8 Games Quality-adjusted performance trend</CardDescription>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="text-xs text-muted-foreground cursor-help focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded"
                aria-label="Momentum calculation information"
              >
                ℹ️
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              <p className="font-semibold mb-1">How Momentum is Calculated:</p>
              <p className="text-xs mb-2">Based on last {gamesAnalyzed.length} games, weighted by opponent strength and performance vs. expectations.</p>
              <div className="text-xs space-y-1">
                <p><strong>Performance Quality Colors:</strong></p>
                <p className="text-green-600 dark:text-green-400">Green = Dominant win</p>
                <p className="text-muted-foreground">Gray = Neutral/expected performance</p>
                <p className="text-red-600 dark:text-red-400">Red = Underperformance (struggle win or bad loss)</p>
              </div>
            </TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col">
          {/* Momentum status bar */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <div
                className="px-3 py-1 rounded-full text-sm font-semibold text-white transition-all duration-300"
                style={{ backgroundColor: momentumColor }}
              >
                {momentumLabel}
              </div>
              <div className="text-xs text-muted-foreground">
                {record.wins}W-{record.draws}D-{record.losses}L
              </div>
            </div>
          </div>

          {/* Game-by-game breakdown */}
          <div className="w-full space-y-1.5">
            <h4 className="text-sm font-semibold text-muted-foreground mb-1">Recent Games:</h4>
            {gamesAnalyzed.map((gameQuality, idx) => {
              const { result, opponentName, teamScore, oppScore, qualityIcon, opponentRank, opponentPower, performanceDelta } = gameQuality;

              // Determine result color and label
              let resultColor = 'text-muted-foreground';
              let resultBg = 'bg-muted';
              if (result === 'W') {
                resultColor = 'text-green-700 dark:text-green-400';
                resultBg = 'bg-green-100 dark:bg-green-950';
              } else if (result === 'L') {
                resultColor = 'text-red-700 dark:text-red-400';
                resultBg = 'bg-red-100 dark:bg-red-950';
              }

              // Determine performance quality color
              let performanceColor = 'text-muted-foreground';
              if (gameQuality.qualityType === 'dominant-win') {
                performanceColor = 'text-green-600 dark:text-green-400 font-semibold'; // Dominant win
              } else if (gameQuality.qualityType === 'quality-win' || gameQuality.qualityType === 'expected-win') {
                performanceColor = 'text-muted-foreground'; // Neutral/expected performance
              } else if (gameQuality.qualityType === 'struggle-win' || gameQuality.qualityType === 'bad-loss') {
                performanceColor = 'text-red-600 dark:text-red-400 font-semibold'; // Underperformance
              }

              // Quality indicator text
              let qualityText = '';
              if (gameQuality.qualityType === 'dominant-win') {
                qualityText = 'Dominant Win';
              } else if (gameQuality.qualityType === 'quality-win') {
                qualityText = 'Quality Win';
              } else if (gameQuality.qualityType === 'expected-win') {
                qualityText = 'Expected Win';
              } else if (gameQuality.qualityType === 'struggle-win') {
                qualityText = 'Underperformed';
              } else if (gameQuality.qualityType === 'competitive-loss') {
                qualityText = 'Competitive Loss';
              } else if (gameQuality.qualityType === 'bad-loss') {
                qualityText = 'Bad Loss';
              }

              return (
                <div
                  key={idx}
                  className={`flex items-center justify-between px-2 py-1.5 rounded text-xs ${resultBg}`}
                >
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className={`font-bold ${resultColor}`}>{result}</span>
                    <span className="truncate">{opponentName}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={resultColor}>
                      {teamScore}-{oppScore}
                    </span>
                    {qualityText && (
                      <span className={`text-xs italic ${performanceColor}`}>
                        {qualityText}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
