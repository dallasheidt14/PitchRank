'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { TeamPredictive } from '@/types/TeamPredictive';

interface PredictedMatchCardProps {
  teamA: TeamPredictive | null;
  teamB: TeamPredictive | null;
  teamAName: string;
  teamBName: string;
}

/**
 * PredictedMatchCard component - displays predicted match result
 * Shows expected scores, margin, and win probabilities
 * Hides entirely if predictive data is unavailable
 */
export function PredictedMatchCard({ teamA, teamB, teamAName, teamBName }: PredictedMatchCardProps) {
  // Hide card entirely if predictive values are null
  if (!teamA || !teamB || teamA.exp_margin == null || teamB.exp_margin == null) {
    return null;
  }

  // Calculate relative margin (Team A vs Team B)
  const margin = (teamA.exp_margin ?? 0) - (teamB.exp_margin ?? 0);
  
  // Convert win rates to percentages
  const teamAWinProb = (teamA.exp_win_rate ?? 0) * 100;
  const teamBWinProb = (teamB.exp_win_rate ?? 0) * 100;

  // Get expected goals (use computed values if available)
  const teamAGoals = teamA.exp_goals_for ?? null;
  const teamBGoals = teamB.exp_goals_for ?? null;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Predicted Match Result</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {/* Team names header */}
          <div className="grid grid-cols-3 text-center font-medium text-sm">
            <div className="truncate">{teamAName}</div>
            <div></div>
            <div className="truncate">{teamBName}</div>
          </div>

          {/* Expected scores */}
          <div className="grid grid-cols-3 text-center items-center">
            <div className="text-2xl font-bold">
              {teamAGoals != null ? Math.round(teamAGoals) : '—'}
            </div>
            <div className="text-xl font-semibold text-muted-foreground">–</div>
            <div className="text-2xl font-bold">
              {teamBGoals != null ? Math.round(teamBGoals) : '—'}
            </div>
          </div>

          {/* Expected margin */}
          <div className="text-center text-sm text-muted-foreground">
            Expected Margin: {margin >= 0 ? '+' : ''}{margin.toFixed(2)} goals
            {margin > 0 && <span className="ml-2 text-green-600 dark:text-green-400">({teamAName} favored)</span>}
            {margin < 0 && <span className="ml-2 text-green-600 dark:text-green-400">({teamBName} favored)</span>}
            {margin === 0 && <span className="ml-2 text-muted-foreground">(Even match)</span>}
          </div>

          {/* Win probabilities */}
          <div className="flex justify-between items-center pt-2 border-t">
            <div className="text-sm">
              <span className="text-muted-foreground">{teamAName} Win Probability: </span>
              <span className="font-semibold">{teamAWinProb.toFixed(1)}%</span>
            </div>
            <div className="text-sm">
              <span className="text-muted-foreground">{teamBName} Win Probability: </span>
              <span className="font-semibold">{teamBWinProb.toFixed(1)}%</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

