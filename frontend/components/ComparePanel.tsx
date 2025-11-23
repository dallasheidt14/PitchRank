import { useState, useMemo, memo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { CardSkeleton, ChartSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { InlineLoader } from '@/components/ui/LoadingStates';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { TeamSelector } from './TeamSelector';
import { PredictedMatchCard } from './PredictedMatchCard';
import { EnhancedPredictionCard } from './EnhancedPredictionCard';
import { useTeam, useCommonOpponents, usePredictive, useMatchPrediction } from '@/lib/hooks';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Legend } from 'recharts';
import { ArrowLeftRight } from 'lucide-react';
import { formatPowerScore } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

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
                        (team1Id && team2Id && opponentsLoading);

  // Check for errors
  const hasErrors = (team1Id && (team1Error || team2Error)) ||
                    (team1Id && team2Id && opponentsError);

  return (
    <Card className="border-l-4 border-l-accent">
      <CardHeader>
        <CardTitle className="font-display text-xl uppercase tracking-wide">Compare Teams</CardTitle>
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
            </div>
          )}

          {team1Details && team2Details && !isLoadingData && (
            <>
              {/* Head-to-Head Stats Comparison */}
              <div className="pt-4 border-t">
                <h3 className="font-display text-lg font-bold uppercase tracking-wide text-primary mb-4">Head-to-Head Comparison</h3>
                <div className="overflow-x-auto -mx-4 sm:mx-0 touch-pan-x">
                  <table className="w-full min-w-[600px]">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left py-3 px-3 sm:px-4 text-xs sm:text-sm font-medium text-muted-foreground">Metric</th>
                        <th className="text-center py-3 px-2 sm:px-3 text-xs sm:text-sm font-medium truncate max-w-[150px]">{team1Details.team_name}</th>
                        <th className="text-center py-3 px-2 sm:px-3 text-xs sm:text-sm font-medium truncate max-w-[150px]">{team2Details.team_name}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      <tr>
                        <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground">National Rank</td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team1Details.rank_in_cohort_final ? `#${team1Details.rank_in_cohort_final}` : '—'}
                        </td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team2Details.rank_in_cohort_final ? `#${team2Details.rank_in_cohort_final}` : '—'}
                        </td>
                      </tr>
                      {(team1Details.state && team1Details.rank_in_state_final) || (team2Details.state && team2Details.rank_in_state_final) ? (
                        <tr>
                          <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground">State Rank</td>
                          <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                            {team1Details.state && team1Details.rank_in_state_final
                              ? `#${team1Details.rank_in_state_final} (${team1Details.state.toUpperCase()})`
                              : '—'}
                          </td>
                          <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                            {team2Details.state && team2Details.rank_in_state_final
                              ? `#${team2Details.rank_in_state_final} (${team2Details.state.toUpperCase()})`
                              : '—'}
                          </td>
                        </tr>
                      ) : null}
                      <tr>
                        <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground">Power Score</td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {formatPowerScore(team1Details.power_score_final)}
                        </td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {formatPowerScore(team2Details.power_score_final)}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground whitespace-nowrap">SOS Rank</td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team1Details.sos_rank_state || team1Details.sos_rank_national ? (
                            <div className="flex flex-col gap-0.5">
                              {team1Details.sos_rank_state && (
                                <span>#{team1Details.sos_rank_state} {team1Details.state || ''}</span>
                              )}
                              {team1Details.sos_rank_national && (
                                <span className="text-xs text-muted-foreground">#{team1Details.sos_rank_national} Nat'l</span>
                              )}
                            </div>
                          ) : '—'}
                        </td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team2Details.sos_rank_state || team2Details.sos_rank_national ? (
                            <div className="flex flex-col gap-0.5">
                              {team2Details.sos_rank_state && (
                                <span>#{team2Details.sos_rank_state} {team2Details.state || ''}</span>
                              )}
                              {team2Details.sos_rank_national && (
                                <span className="text-xs text-muted-foreground">#{team2Details.sos_rank_national} Nat'l</span>
                              )}
                            </div>
                          ) : '—'}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground">Offense</td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team1Details.offense_norm !== null ? team1Details.offense_norm.toFixed(3) : '—'}
                        </td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team2Details.offense_norm !== null ? team2Details.offense_norm.toFixed(3) : '—'}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground">Defense</td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team1Details.defense_norm !== null ? team1Details.defense_norm.toFixed(3) : '—'}
                        </td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team2Details.defense_norm !== null ? team2Details.defense_norm.toFixed(3) : '—'}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground">Win %</td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team1Details.win_percentage !== null ? `${team1Details.win_percentage.toFixed(1)}%` : '—'}
                        </td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team2Details.win_percentage !== null ? `${team2Details.win_percentage.toFixed(1)}%` : '—'}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground">Record</td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team1Details.total_wins ?? 0}-{team1Details.total_losses ?? 0}{(team1Details.total_draws ?? 0) > 0 && `-${team1Details.total_draws}`}
                        </td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team2Details.total_wins ?? 0}-{team2Details.total_losses ?? 0}{(team2Details.total_draws ?? 0) > 0 && `-${team2Details.total_draws}`}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-3 px-3 sm:px-4 text-xs sm:text-sm text-muted-foreground">Games</td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team1Details.games_played}/{team1Details.total_games_played ?? 0}
                        </td>
                        <td className="py-3 px-2 sm:px-3 text-center text-sm sm:text-base font-semibold">
                          {team2Details.games_played}/{team2Details.total_games_played ?? 0}
                        </td>
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

              {/* Common Opponents */}
              {commonOpponents && commonOpponents.length > 0 && (
                <div className="pt-4 border-t">
                  <h3 className="font-display text-lg font-bold uppercase tracking-wide text-primary mb-4">Common Opponents</h3>
                  <div className="space-y-2">
                    {commonOpponents.slice(0, 10).map((opponent) => (
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
                    {commonOpponents.length > 10 && (
                      <p className="text-sm text-muted-foreground text-center">
                        Showing 10 of {commonOpponents.length} common opponents
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Side-by-Side Comparison Chart */}
              <div className="pt-4 border-t">
                <h3 className="font-display text-lg font-bold uppercase tracking-wide text-primary mb-4">Side-by-Side Comparison</h3>
                <div className="w-full h-[300px] sm:h-[350px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={comparisonData}
                      margin={{
                        top: 20,
                        right: 10,
                        left: 0,
                        bottom: 5
                      }}
                    >
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis
                        dataKey="metric"
                        className="text-xs"
                        tick={{ fill: 'currentColor', fontSize: 11 }}
                        stroke="currentColor"
                        angle={-15}
                        textAnchor="end"
                        height={60}
                      />
                      <YAxis
                        className="text-xs"
                        tick={{ fill: 'currentColor', fontSize: 11 }}
                        stroke="currentColor"
                        width={40}
                      />
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: 'hsl(var(--card))',
                          border: '1px solid hsl(var(--border))',
                          borderRadius: '0.5rem',
                          fontSize: '12px',
                        }}
                        labelStyle={{ color: 'hsl(var(--foreground))' }}
                      />
                      <Legend
                        wrapperStyle={{ fontSize: '12px' }}
                        iconSize={12}
                      />
                      <Bar dataKey="team1" fill="hsl(var(--chart-1))" name={team1Details.team_name} radius={[4, 4, 0, 0]} />
                      <Bar dataKey="team2" fill="hsl(var(--chart-2))" name={team2Details.team_name} radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
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
