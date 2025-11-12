'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { CardSkeleton, ChartSkeleton } from '@/components/ui/skeletons';
import { TeamSelector } from './TeamSelector';
import { useTeam, useRankings } from '@/lib/hooks';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Legend } from 'recharts';
import type { RankingWithTeam } from '@/lib/types';

/**
 * ComparePanel component - allows comparing multiple teams
 */
export function ComparePanel() {
  const [team1Id, setTeam1Id] = useState<string | null>(null);
  const [team2Id, setTeam2Id] = useState<string | null>(null);
  const [team1Data, setTeam1Data] = useState<RankingWithTeam | null>(null);
  const [team2Data, setTeam2Data] = useState<RankingWithTeam | null>(null);

  const { data: team1Details } = useTeam(team1Id || '');
  const { data: team2Details } = useTeam(team2Id || '');

  const handleTeam1Change = (id: string | null, team: RankingWithTeam | null) => {
    setTeam1Id(id);
    setTeam1Data(team);
  };

  const handleTeam2Change = (id: string | null, team: RankingWithTeam | null) => {
    setTeam2Id(id);
    setTeam2Data(team);
  };

  const comparisonData = team1Data && team2Data ? [
    {
      metric: 'Power Score',
      team1: team1Data.national_power_score,
      team2: team2Data.national_power_score,
    },
    {
      metric: 'Win %',
      team1: team1Data.win_percentage || 0,
      team2: team2Data.win_percentage || 0,
    },
    {
      metric: 'Games Played',
      team1: team1Data.games_played,
      team2: team2Data.games_played,
    },
    {
      metric: 'Wins',
      team1: team1Data.wins,
      team2: team2Data.wins,
    },
  ] : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Compare Teams</CardTitle>
        <CardDescription>
          Select two teams to compare their rankings and statistics
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
            <TeamSelector
              label="Team 2"
              value={team2Id}
              onChange={handleTeam2Change}
              excludeTeamId={team1Id || undefined}
            />
          </div>

          {team1Data && team2Data && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4 border-t">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">{team1Data.team_name}</CardTitle>
                    <CardDescription>
                      {team1Data.club_name && <span>{team1Data.club_name}</span>}
                      {team1Data.state_code && (
                        <span className={team1Data.club_name ? ' • ' : ''}>
                          {team1Data.state_code}
                        </span>
                      )}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">National Rank:</span>
                      <span className="font-semibold">
                        {team1Data.national_rank ? `#${team1Data.national_rank}` : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Power Score:</span>
                      <span className="font-semibold">
                        {team1Data.national_power_score.toFixed(1)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Win %:</span>
                      <span className="font-semibold">
                        {team1Data.win_percentage !== null
                          ? `${team1Data.win_percentage.toFixed(1)}%`
                          : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Record:</span>
                      <span className="font-semibold">
                        {team1Data.wins}-{team1Data.losses}
                        {team1Data.draws > 0 && `-${team1Data.draws}`}
                      </span>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">{team2Data.team_name}</CardTitle>
                    <CardDescription>
                      {team2Data.club_name && <span>{team2Data.club_name}</span>}
                      {team2Data.state_code && (
                        <span className={team2Data.club_name ? ' • ' : ''}>
                          {team2Data.state_code}
                        </span>
                      )}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">National Rank:</span>
                      <span className="font-semibold">
                        {team2Data.national_rank ? `#${team2Data.national_rank}` : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Power Score:</span>
                      <span className="font-semibold">
                        {team2Data.national_power_score.toFixed(1)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Win %:</span>
                      <span className="font-semibold">
                        {team2Data.win_percentage !== null
                          ? `${team2Data.win_percentage.toFixed(1)}%`
                          : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Record:</span>
                      <span className="font-semibold">
                        {team2Data.wins}-{team2Data.losses}
                        {team2Data.draws > 0 && `-${team2Data.draws}`}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              </div>

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
                    <Bar dataKey="team1" fill="hsl(var(--chart-1))" name={team1Data.team_name} />
                    <Bar dataKey="team2" fill="hsl(var(--chart-2))" name={team2Data.team_name} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          )}

          {(!team1Data || !team2Data) && (
            <div className="text-center py-8 text-muted-foreground">
              <p>Select two teams to compare their statistics</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
