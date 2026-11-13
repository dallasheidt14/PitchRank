'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { MatchPrediction } from '@/lib/matchPredictor';
import type { MatchExplanation } from '@/lib/matchExplainer';
import type { MatchEvidenceSummary } from '@/lib/matchEvidence';
import { presentMatchup } from '@/lib/matchupPresentation';

interface EnhancedPredictionCardProps {
  teamAName: string;
  teamBName: string;
  prediction: MatchPrediction;
  explanation: MatchExplanation;
  evidence?: MatchEvidenceSummary;
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
    significant: 'border-l-green-500',
    moderate: 'border-l-blue-500',
    minimal: 'border-l-gray-400',
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
 * - Top explanation factors
 * - Key insights
 */
export function EnhancedPredictionCard({
  teamAName,
  teamBName,
  prediction,
  explanation,
  evidence,
}: EnhancedPredictionCardProps) {
  const { winProbabilityA, winProbabilityB, drawProbability, expectedScore } = prediction;
  const { factors, keyInsights, counterFactors = [] } = explanation;
  const presentation = presentMatchup(prediction, teamAName, teamBName);
  const cautions: string[] = [];
  if (evidence) {
    for (const [name, team] of [
      [teamAName, evidence.teamA],
      [teamBName, evidence.teamB],
    ] as const) {
      if (team.formSampleSize < evidence.formSampleLimit) {
        cautions.push(`${name}: limited recent results available.`);
      }
    }
  }

  // Determine favored team for styling
  const teamAFavored = presentation.favorite === 'team_a';
  const teamBFavored = presentation.favorite === 'team_b';
  const evenMatch = presentation.favorite === null;

  return (
    <Card className="mt-4">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Match Prediction</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Summary */}
        <div className="text-center">
          <p className="text-lg font-semibold text-foreground">{presentation.summary}</p>
          {presentation.closelyMatched && <p className="text-sm text-muted-foreground mt-1">Closely matched</p>}
        </div>

        {/* Expected Score */}
        {presentation.showScore && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2 text-center">Projected scoreline</h4>
            <div className="grid grid-cols-3 text-center items-center">
              <div>
                <div className="text-sm font-medium truncate mb-1">{teamAName}</div>
                <div className={`text-3xl font-bold ${teamAFavored ? 'text-green-600' : 'text-foreground'}`}>
                  {Math.round(expectedScore.teamA)}
                </div>
              </div>
              <div className="text-2xl font-semibold text-muted-foreground">–</div>
              <div>
                <div className="text-sm font-medium truncate mb-1">{teamBName}</div>
                <div className={`text-3xl font-bold ${teamBFavored ? 'text-green-600' : 'text-foreground'}`}>
                  {Math.round(expectedScore.teamB)}
                </div>
              </div>
            </div>
            <p className="text-xs text-muted-foreground text-center mt-2">
              Most likely scoreline for the predicted result. Other scorelines and outcomes remain possible.
            </p>
          </div>
        )}

        {/* Win Probabilities */}
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-2">Outcome probabilities</h4>
          <div className="space-y-2">
            {/* Team A */}
            <div className="flex items-center gap-2">
              <span className="text-sm w-20 sm:w-32 truncate">{teamAName}</span>
              <div className="flex-1 h-6 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-full ${teamAFavored ? 'bg-green-500' : 'bg-blue-400'} transition-all duration-300`}
                  style={{ width: `${winProbabilityA * 100}%` }}
                />
              </div>
              <span className="text-sm font-semibold w-14 text-right">{(winProbabilityA * 100).toFixed(0)}%</span>
            </div>
            {/* Team B */}
            <div className="flex items-center gap-2">
              <span className="text-sm w-20 sm:w-32 truncate">{teamBName}</span>
              <div className="flex-1 h-6 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-full ${teamBFavored ? 'bg-green-500' : 'bg-blue-400'} transition-all duration-300`}
                  style={{ width: `${winProbabilityB * 100}%` }}
                />
              </div>
              <span className="text-sm font-semibold w-14 text-right">{(winProbabilityB * 100).toFixed(0)}%</span>
            </div>
            {
              <div className="flex items-center gap-2">
                <span className="text-sm w-20 sm:w-32 truncate">Draw</span>
                <div className="flex-1 h-6 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gray-500 transition-all duration-300"
                    style={{ width: `${(drawProbability ?? 0) * 100}%` }}
                  />
                </div>
                <span className="text-sm font-semibold min-w-14 text-right">
                  {drawProbability == null ? 'Unavailable' : `${(drawProbability * 100).toFixed(0)}%`}
                </span>
              </div>
            }
          </div>
        </div>

        {/* Explanation Factors */}
        {factors.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-3">
              {evenMatch ? 'Evidence for each team' : `Why ${teamAFavored ? teamAName : teamBName} is Favored`}
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

        {(counterFactors.length > 0 || cautions.length > 0) && (
          <section aria-label="Reasons for caution">
            <h4 className="text-sm font-semibold mb-2">Reasons for caution</h4>
            <div className="space-y-2">
              {counterFactors.map((factor) => (
                <ExplanationFactor key={factor.factor} {...factor} />
              ))}
              {cautions.map((caution, index) => (
                <p key={`${index}:${caution}`} className="text-sm text-muted-foreground">
                  {caution}
                </p>
              ))}
            </div>
          </section>
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
      </CardContent>
    </Card>
  );
}
