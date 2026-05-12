/**
 * Team Insight Engine
 *
 * Premium-only scouting-style insights computed from team data.
 * Insight types:
 * 1. Season Truth Summary - narrative evaluation
 * 2. Consistency Score (0-100)
 * 3. Team Persona Label (tier + auto-picked trait)
 * 4. Form Badge (Surging / Slumping; optional)
 */

export * from './types';
export { generateSeasonTruth } from './seasonTruth';
export { generateConsistencyScore } from './consistency';
export { generatePersonaInsight } from './persona';
export { generateFormBadge } from './formBadge';

import type { InsightInputData, TeamInsight, TeamInsightsResponse } from './types';
import { generateSeasonTruth } from './seasonTruth';
import { generateConsistencyScore } from './consistency';
import { generatePersonaInsight } from './persona';
import { generateFormBadge } from './formBadge';

export function generateAllInsights(data: InsightInputData): TeamInsightsResponse {
  const insights: TeamInsight[] = [
    generateSeasonTruth(data),
    generateConsistencyScore(data),
    generatePersonaInsight(data),
  ];

  const formBadge = generateFormBadge(data);
  if (formBadge) insights.push(formBadge);

  return {
    teamId: data.team.team_id_master,
    teamName: data.team.team_name,
    insights,
    generatedAt: new Date().toISOString(),
  };
}
