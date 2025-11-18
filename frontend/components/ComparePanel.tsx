'use client';

import { useState, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { CardSkeleton, ChartSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { InlineLoader } from '@/components/ui/LoadingStates';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { TeamSelector } from './TeamSelector';
import { PredictedMatchCard } from './PredictedMatchCard';
import { EnhancedPredictionCard } from './EnhancedPredictionCard';
import { useTeam, useRankings, useCommonOpponents, usePredictive, useMatchPrediction } from '@/lib/hooks';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Legend } from 'recharts';
import { ArrowLeftRight, TrendingUp, TrendingDown } from 'lucide-react';
import { formatPowerScore } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Calculate percentile for a value in a distribution
 */
function calculatePercentile(value: number, allValues: number[]): number {
  if (allValues.length === 0) return 0;
  const sorted = [...allValues].sort((a, b) => a - b);
  const below = sorted.filter(v => v < value).length;
  return Math.round((below / sorted.length) * 100);
}

/**
 * Get percentile label
 */
function getPercentileLabel(percentile: number): string {
  if (percentile >= 97) return 'Top 3%';
  if (percentile >= 95) return 'Top 5%';
  if (percentile >= 90) return 'Top 10%';
  if (percentile >= 75) return 'Top 25%';
  if (percentile >= 50) return 'Top 50%';
  return `Bottom ${100 - percentile}%`;
}

/**
 * PercentileBar component - visual representation of percentile
 */
function PercentileBar({ value, maxValue, percentile }: { value: number; maxValue: number; percentile: number }) {
  const percentage = (value / maxValue) * 100;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{value.toFixed(1)}</span>
        <Badge variant="outline" className="text-xs">
          {getPercentileLabel(percentile)}
        </Badge>
      </div>
      <div className="w-full bg-muted rounded-full h-2">
        <div
          className="bg-primary h-2 rounded-full transition-all duration-300"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

/**
 * ComparePanel component - enhanced team comparison with all features
 */
export function ComparePanel() {
  const [team1Id, setTeam1Id] = useState<string | null>(null);
  const [team2Id, setTeam2Id] = useState<string | null>(null);
  const [team1Data, setTeam1Data] = useState<RankingRow | null>(null);
  const [team2Data, setTeam2Data] = useState<RankingRow | null>(null);

  const { data: team1Details, isLoading: team1Loading, isError: team1Error, error: team1ErrorObj, refetch: refetchTeam1 } = useTeam(team1Id || '');
  const { data: team2Details, isLoading: team2Loading, isError: team2Error, error: team2ErrorObj, refetch: refetchTeam2 } = useTeam(team2Id || '');
  const { data: commonOpponents, isLoading: opponentsLoading, isError: opponentsError, error: opponentsErrorObj, refetch: refetchOpponents } = useCommonOpponents(team1Id, team2Id);
  
  // Fetch predictive data in parallel (non-blocking)
  // Use team_id_master from state (team1Id/team2Id are already team_id_master UUIDs)
  const { data: team1Predictive } = usePredictive(team1Id);
  const { data: team2Predictive } = usePredictive(team2Id);

  // Fetch enhanced match prediction with explanations
  const { data: matchPrediction, isLoading: predictionLoading } = useMatchPrediction(team1Id, team2Id);
  
  // Get rankings for percentile calculation
  const { data: allRankings, isLoading: rankingsLoading, isError: rankingsError, error: rankingsErrorObj, refetch: refetchRankings } = useRankings(
    team1Details?.state || undefined,
    team1Details?.age != null ? `u${team1Details.age}` : undefined,
    team1Details?.gender
  );

  // Calculate percentiles for all metrics
  const percentiles = useMemo(() => {
    if (!team1Details || !team2Details || !allRankings || allRankings.length === 0) {
      return {
        team1: { powerScore: 0, winPercentage: 0, gamesPlayed: 0 },
        team2: { powerScore: 0, winPercentage: 0, gamesPlayed: 0 },
      };
    }

    const powerScores = allRankings.map(r => r.power_score_final);
    const winPercentages = allRankings.map(r => r.win_percentage ?? 0).filter(v => v > 0);
    const gamesPlayed = allRankings.map(r => r.games_played);

    return {
      team1: {
        powerScore: calculatePercentile(team1Details.power_score_final ?? 0, powerScores),
        winPercentage: team1Details.win_percentage
          ? calculatePercentile(team1Details.win_percentage, winPercentages)
          : 0,
        gamesPlayed: calculatePercentile(team1Details.games_played, gamesPlayed),
      },
      team2: {
        powerScore: calculatePercentile(team2Details.power_score_final ?? 0, powerScores),
        winPercentage: team2Details.win_percentage
          ? calculatePercentile(team2Details.win_percentage, winPercentages)
          : 0,
        gamesPlayed: calculatePercentile(team2Details.games_played, gamesPlayed),
      },
    };
  }, [team1Details, team2Details, allRankings]);

  const maxPowerScore = useMemo(() => {
    return Math.max(
      team1Details?.power_score_final ?? 0,
      team2Details?.power_score_final ?? 0
    );
  }, [team1Details, team2Details]);

  const handleTeam1Change = (id: string | null, team: RankingRow | null) => {
    setTeam1Id(id);
    setTeam1Data(team);
  };

  const handleTeam2Change = (id: string | null, team: RankingRow | null) => {
    setTeam2Id(id);
    setTeam2Data(team);
  };

  const handleSwap = () => {
    const tempId = team1Id;
    const tempData = team1Data;
    setTeam1Id(team2Id);
    setTeam1Data(team2Data);
    setTeam2Id(tempId);
    setTeam2Data(tempData);
  };

  const comparisonData = team1Details && team2Details ? [
    {
      metric: 'PowerScore (ML Adjusted)',
      team1: team1Details.power_score_final ?? 0,
      team2: team2Details.power_score_final ?? 0,
    },
    {
      metric: 'Win %',
      team1: team1Details.win_percentage || 0,
      team2: team2Details.win_percentage || 0,
    },
    {
      metric: 'Games Played',
      team1: team1Details.games_played,
      team2: team2Details.games_played,
    },
    {
      metric: 'Wins',
      team1: team1Details.wins,
      team2: team2Details.wins,
    },
  ] : [];

  // Show loading state when teams are being fetched
  const isLoadingData = (team1Id && (team1Loading || team2Loading)) ||
                        (team1Id && team2Id && (opponentsLoading || rankingsLoading));

  // Check for errors
  const hasErrors = (team1Id && (team1Error || team2Error)) ||
                    (team1Id && team2Id && (opponentsError || rankingsError));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Compare Teams</CardTitle>
        <CardDescription>
          Select two teams to compare their rankings, statistics, and performance metrics side-by-side
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <TeamSelector
              label="Team 1"
              value={team1Id}
              onChange={handleTeam1Change}
              excludeTeamId={team2Id || undefined}
            />
            <div className="flex items-end">
              {team1Id && team2Id && (
                <Button
                  onClick={handleSwap}
                  variant="outline"
                  size="icon"
                  className="mb-2"
                  aria-label="Swap teams"
                >
                  <ArrowLeftRight className="h-4 w-4" />
                </Button>
              )}
            </div>
            <TeamSelector
              label="Team 2"
              value={team2Id}
              onChange={handleTeam2Change}
              excludeTeamId={team1Id || undefined}
            />
          </div>

          {/* Show loading state */}
          {isLoadingData && (
            <div className="flex justify-center py-8">
              <InlineLoader text="Loading team data..." />
            </div>
          )}

          {/* Show errors */}
          {hasErrors && !isLoadingData && (
            <div className="space-y-4">
              {team1Id && team1Error && (
                <ErrorDisplay error={team1ErrorObj} retry={refetchTeam1} compact />
              )}
              {team2Id && team2Error && (
                <ErrorDisplay error={team2ErrorObj} retry={refetchTeam2} compact />
              )}
              {team1Id && team2Id && opponentsError && (
                <ErrorDisplay error={opponentsErrorObj} retry={refetchOpponents} compact />
              )}
              {team1Id && team2Id && rankingsError && (
                <ErrorDisplay error={rankingsErrorObj} retry={refetchRankings} compact />
              )}
            </div>
          )}

          {team1Details && team2Details && !isLoadingData && (
            <>
              {/* Head-to-Head Stats Comparison */}
              <div className="pt-4 border-t">
                <h3 className="text-lg font-semibold mb-4">Head-to-Head Comparison</h3>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left py-2 px-2 text-sm font-medium text-muted-foreground">Metric</th>
                        <th className="text-center py-2 px-2 text-sm font-medium">{team1Details.team_name}</th>
                        <th className="text-center py-2 px-2 text-sm font-medium">{team2Details.team_name}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      <tr>
                        <td className="py-3 px-2 text-sm text-muted-foreground">National Rank</td>
                        <td className="py-3 px-2 text-center font-semibold">
                          {team1Details.rank_in_cohort_final ? `#${team1Details.rank_in_cohort_final}` : '—'}
                        </td>
                        <td className="py-3 px-2 text-center font-semibold">
                          {team2Details.rank_in_cohort_final ? `#${team2Details.rank_in_cohort_final}` : '—'}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-2 text-sm text-muted-foreground">Power Score</td>
                        <td className="py-3 px-2 text-center font-semibold">
                          {formatPowerScore(team1Details.power_score_final)}
                        </td>
                        <td className="py-3 px-2 text-center font-semibold">
                          {formatPowerScore(team2Details.power_score_final)}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-2 text-sm text-muted-foreground">Win %</td>
                        <td className="py-3 px-2 text-center font-semibold">
                          {team1Details.win_percentage !== null ? `${team1Details.win_percentage.toFixed(1)}%` : '—'}
                        </td>
                        <td className="py-3 px-2 text-center font-semibold">
                          {team2Details.win_percentage !== null ? `${team2Details.win_percentage.toFixed(1)}%` : '—'}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-2 text-sm text-muted-foreground">Record</td>
                        <td className="py-3 px-2 text-center font-semibold">
                          {team1Details.wins}-{team1Details.losses}{team1Details.draws > 0 && `-${team1Details.draws}`}
                        </td>
                        <td className="py-3 px-2 text-center font-semibold">
                          {team2Details.wins}-{team2Details.losses}{team2Details.draws > 0 && `-${team2Details.draws}`}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-2 text-sm text-muted-foreground">Games Played</td>
                        <td className="py-3 px-2 text-center font-semibold">{team1Details.games_played}</td>
                        <td className="py-3 px-2 text-center font-semibold">{team2Details.games_played}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Match Prediction - Prominently Displayed */}
              {matchPrediction && (
                <EnhancedPredictionCard
                  teamAName={team1Details.team_name}
                  teamBName={team2Details.team_name}
                  prediction={matchPrediction.prediction}
                  explanation={matchPrediction.explanation}
                />
              )}

              {/* Loading state for prediction */}
              {predictionLoading && (
                <Card className="mt-4">
                  <CardContent className="py-8">
                    <InlineLoader />
                    <p className="text-center text-sm text-muted-foreground mt-2">
                      Analyzing matchup...
                    </p>
                  </CardContent>
                </Card>
              )}

              {/* Fallback to old prediction card if enhanced prediction fails */}
              {!matchPrediction && !predictionLoading && (
                <PredictedMatchCard
                  teamA={team1Predictive || null}
                  teamB={team2Predictive || null}
                  teamAName={team1Details.team_name}
                  teamBName={team2Details.team_name}
                />
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4 border-t">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">{team1Details.team_name}</CardTitle>
                    <CardDescription>
                      {team1Details.club_name && <span>{team1Details.club_name}</span>}
                      {team1Details.state && (
                        <span className={team1Details.club_name ? ' • ' : ''}>
                          {team1Details.state}
                        </span>
                      )}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="text-muted-foreground">National Rank:</span>
                        <span className="font-semibold">
                          {team1Details.rank_in_cohort_final ? `#${team1Details.rank_in_cohort_final}` : '—'}
                        </span>
                      </div>
                      {team1Details.state && team1Details.rank_in_state_final && (
                        <div className="flex justify-between items-center">
                          <span className="text-muted-foreground">State Rank:</span>
                          <span className="font-semibold">
                            #{team1Details.rank_in_state_final} ({team1Details.state.toUpperCase()})
                          </span>
                        </div>
                      )}
                    </div>

                    <div className="space-y-3 pt-2 border-t">
                      <div>
                        <div className="flex justify-between mb-1">
                          <span className="text-muted-foreground">PowerScore (ML Adjusted):</span>
                          <span className="font-semibold">
                            {formatPowerScore(team1Details.power_score_final)}
                          </span>
                        </div>
                        <PercentileBar
                          value={team1Details.power_score_final ?? 0}
                          maxValue={maxPowerScore}
                          percentile={percentiles?.team1?.powerScore ?? 0}
                        />
                      </div>

                      <div>
                        <div className="flex justify-between mb-1">
                          <span className="text-muted-foreground">Win %:</span>
                          <span className="font-semibold">
                            {team1Details.win_percentage !== null
                              ? `${team1Details.win_percentage.toFixed(1)}%`
                              : '—'}
                          </span>
                        </div>
                        {team1Details.win_percentage !== null && (
                          <PercentileBar
                            value={team1Details.win_percentage ?? 0}
                            maxValue={100}
                            percentile={percentiles?.team1?.winPercentage ?? 0}
                          />
                        )}
                      </div>

                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Record:</span>
                        <span className="font-semibold">
                          {team1Details.wins}-{team1Details.losses}
                          {team1Details.draws > 0 && `-${team1Details.draws}`}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Games Played:</span>
                        <span className="font-semibold">{team1Details.games_played}</span>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">{team2Details.team_name}</CardTitle>
                    <CardDescription>
                      {team2Details.club_name && <span>{team2Details.club_name}</span>}
                      {team2Details.state && (
                        <span className={team2Details.club_name ? ' • ' : ''}>
                          {team2Details.state}
                        </span>
                      )}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="text-muted-foreground">National Rank:</span>
                        <span className="font-semibold">
                          {team2Details.rank_in_cohort_final ? `#${team2Details.rank_in_cohort_final}` : '—'}
                        </span>
                      </div>
                      {team2Details.state && team2Details.rank_in_state_final && (
                        <div className="flex justify-between items-center">
                          <span className="text-muted-foreground">State Rank:</span>
                          <span className="font-semibold">
                            #{team2Details.rank_in_state_final} ({team2Details.state.toUpperCase()})
                          </span>
                        </div>
                      )}
                    </div>

                    <div className="space-y-3 pt-2 border-t">
                      <div>
                        <div className="flex justify-between mb-1">
                          <span className="text-muted-foreground">PowerScore (ML Adjusted):</span>
                          <span className="font-semibold">
                            {formatPowerScore(team2Details.power_score_final)}
                          </span>
                        </div>
                        <PercentileBar
                          value={team2Details.power_score_final ?? 0}
                          maxValue={maxPowerScore}
                          percentile={percentiles?.team2?.powerScore ?? 0}
                        />
                      </div>

                      <div>
                        <div className="flex justify-between mb-1">
                          <span className="text-muted-foreground">Win %:</span>
                          <span className="font-semibold">
                            {team2Details.win_percentage !== null
                              ? `${team2Details.win_percentage.toFixed(1)}%`
                              : '—'}
                          </span>
                        </div>
                        {team2Details.win_percentage !== null && (
                          <PercentileBar
                            value={team2Details.win_percentage ?? 0}
                            maxValue={100}
                            percentile={percentiles?.team2?.winPercentage ?? 0}
                          />
                        )}
                      </div>

                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Record:</span>
                        <span className="font-semibold">
                          {team2Details.wins}-{team2Details.losses}
                          {team2Details.draws > 0 && `-${team2Details.draws}`}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Games Played:</span>
                        <span className="font-semibold">{team2Details.games_played}</span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>


              {/* Common Opponents */}
              {commonOpponents && commonOpponents.length > 0 && (
                <div className="pt-4 border-t">
                  <h3 className="text-lg font-semibold mb-4">Common Opponents</h3>
                  <div className="space-y-2">
                    {commonOpponents.slice(0, 5).map((opponent) => (
                      <Card key={opponent.opponent_id} className="p-3">
                        <div className="flex items-center justify-between">
                          <div className="font-medium">{opponent.opponent_name}</div>
                          <div className="flex items-center gap-4 text-sm">
                            <div className="flex items-center gap-2">
                              <span className="text-muted-foreground">{team1Details.team_name}:</span>
                              <span className={`font-semibold ${
                                opponent.team1_result === 'W' ? 'text-green-600' :
                                opponent.team1_result === 'L' ? 'text-red-600' :
                                'text-yellow-600'
                              }`}>
                                {opponent.team1_result || '—'}
                              </span>
                              {opponent.team1_score !== null && (
                                <span className="text-muted-foreground">
                                  ({opponent.team1_score}-{opponent.opponent_score_team1})
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-muted-foreground">{team2Details.team_name}:</span>
                              <span className={`font-semibold ${
                                opponent.team2_result === 'W' ? 'text-green-600' :
                                opponent.team2_result === 'L' ? 'text-red-600' :
                                'text-yellow-600'
                              }`}>
                                {opponent.team2_result || '—'}
                              </span>
                              {opponent.team2_score !== null && (
                                <span className="text-muted-foreground">
                                  ({opponent.team2_score}-{opponent.opponent_score_team2})
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </Card>
                    ))}
                    {commonOpponents.length > 5 && (
                      <p className="text-sm text-muted-foreground text-center">
                        Showing 5 of {commonOpponents.length} common opponents
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Side-by-Side Comparison Chart */}
              <div className="pt-4 border-t">
                <h3 className="text-lg font-semibold mb-4">Side-by-Side Comparison</h3>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={comparisonData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                    <XAxis
                      dataKey="metric"
                      className="text-xs"
                      tick={{ fill: 'currentColor' }}
                      stroke="currentColor"
                    />
                    <YAxis
                      className="text-xs"
                      tick={{ fill: 'currentColor' }}
                      stroke="currentColor"
                    />
                    <RechartsTooltip
                      contentStyle={{
                        backgroundColor: 'hsl(var(--card))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '0.5rem',
                      }}
                      labelStyle={{ color: 'hsl(var(--foreground))' }}
                    />
                    <Legend />
                    <Bar dataKey="team1" fill="hsl(var(--chart-1))" name={team1Details.team_name} />
                    <Bar dataKey="team2" fill="hsl(var(--chart-2))" name={team2Details.team_name} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          )}

          {(!team1Details || !team2Details) && !isLoadingData && (
            <div className="text-center py-8 text-muted-foreground">
              <p>Select two teams to compare their statistics</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
