'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { MatchPrediction } from '@/lib/matchPredictor';
import type { MatchExplanation } from '@/lib/matchExplainer';

interface EnhancedPredictionCardProps {
  teamAName: string;
  teamBName: string;
  prediction: MatchPrediction;
  explanation: MatchExplanation;
}

/**
 * Confidence badge with color coding
 */
function ConfidenceBadge({ confidence }: { confidence: 'high' | 'medium' | 'low' }) {
  const styles = {
    high: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    low: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200',
  };

  return (
    <Badge className={styles[confidence]}>
      {confidence.toUpperCase()} CONFIDENCE
    </Badge>
  );
}

/**
 * Explanation factor item
 */
function ExplanationFactor({
  icon,
  description,
  magnitude,
}: {
  icon: string;
  description: string;
  magnitude: 'significant' | 'moderate' | 'minimal';
}) {
  const magnitudeColors = {
    significant: 'border-l-green-500 dark:border-l-green-400',
    moderate: 'border-l-blue-500 dark:border-l-blue-400',
    minimal: 'border-l-gray-400 dark:border-l-gray-500',
  };

  return (
    <div className={`pl-3 py-2 border-l-4 ${magnitudeColors[magnitude]}`}>
      <div className="flex items-start gap-2">
        <span className="text-xl flex-shrink-0">{icon}</span>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

/**
 * Enhanced Prediction Card with explanations
 *
 * Shows:
 * - Predicted winner and score
 * - Win probabilities
 * - Confidence level
 * - Top explanation factors
 * - Key insights
 */
export function EnhancedPredictionCard({
  teamAName,
  teamBName,
  prediction,
  explanation,
}: EnhancedPredictionCardProps) {
  const { predictedWinner, winProbabilityA, winProbabilityB, expectedScore, confidence } = prediction;
  const { summary, factors, keyInsights, predictionQuality } = explanation;

  // Determine favored team for styling
  const teamAFavored = predictedWinner === 'team_a';
  const teamBFavored = predictedWinner === 'team_b';
  const evenMatch = predictedWinner === 'draw';

  return (
    <Card className="mt-4">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Match Prediction</CardTitle>
          <ConfidenceBadge confidence={confidence} />
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Summary */}
        <div className="text-center">
          <p className="text-lg font-semibold text-foreground">
            {summary}
          </p>
        </div>

        {/* Expected Score */}
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-2 text-center">
            Expected Score
          </h4>
          <div className="grid grid-cols-3 text-center items-center">
            <div>
              <div className="text-sm font-medium truncate mb-1">{teamAName}</div>
              <div className={`text-3xl font-bold ${teamAFavored ? 'text-green-600 dark:text-green-400' : 'text-foreground'}`}>
                {expectedScore.teamA.toFixed(0)}
              </div>
            </div>
            <div className="text-2xl font-semibold text-muted-foreground">–</div>
            <div>
              <div className="text-sm font-medium truncate mb-1">{teamBName}</div>
              <div className={`text-3xl font-bold ${teamBFavored ? 'text-green-600 dark:text-green-400' : 'text-foreground'}`}>
                {expectedScore.teamB.toFixed(0)}
              </div>
            </div>
          </div>
        </div>

        {/* Win Probabilities */}
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-2">Win Probability</h4>
          <div className="space-y-2">
            {/* Team A */}
            <div className="flex items-center gap-2">
              <span className="text-sm w-32 truncate">{teamAName}</span>
              <div className="flex-1 h-6 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full ${teamAFavored ? 'bg-green-500' : 'bg-blue-400'} transition-all duration-300`}
                  style={{ width: `${winProbabilityA * 100}%` }}
                />
              </div>
              <span className="text-sm font-semibold w-14 text-right">
                {(winProbabilityA * 100).toFixed(0)}%
              </span>
            </div>
            {/* Team B */}
            <div className="flex items-center gap-2">
              <span className="text-sm w-32 truncate">{teamBName}</span>
              <div className="flex-1 h-6 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full ${teamBFavored ? 'bg-green-500' : 'bg-blue-400'} transition-all duration-300`}
                  style={{ width: `${winProbabilityB * 100}%` }}
                />
              </div>
              <span className="text-sm font-semibold w-14 text-right">
                {(winProbabilityB * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>

        {/* Explanation Factors */}
        {factors.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-3">
              {evenMatch ? 'Why This Match is Close' : `Why ${teamAFavored ? teamAName : teamBName} is Favored`}
            </h4>
            <div className="space-y-2">
              {factors.map((factor, index) => (
                <ExplanationFactor
                  key={index}
                  icon={factor.icon}
                  description={factor.description}
                  magnitude={factor.magnitude}
                />
              ))}
            </div>
          </div>
        )}

        {/* Key Insights */}
        {keyInsights.length > 0 && (
          <div className="pt-4 border-t">
            <h4 className="text-sm font-medium text-muted-foreground mb-2">Key Insights</h4>
            <ul className="space-y-1">
              {keyInsights.map((insight, index) => (
                <li key={index} className="text-sm text-muted-foreground flex items-start gap-2">
                  <span className="text-green-500 mt-0.5">•</span>
                  <span>{insight}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Prediction Quality Footer */}
        <div className="pt-4 border-t text-center">
          <p className="text-xs text-muted-foreground">
            {predictionQuality.reliability}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
