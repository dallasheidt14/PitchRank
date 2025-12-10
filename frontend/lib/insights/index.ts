/**
 * Team Insight Engine
 *
 * Premium-only scouting-style insights computed from team data.
 * Three insight types:
 * 1. Season Truth Summary - narrative evaluation
 * 2. Consistency Score (0-100)
 * 3. Team Persona Label
 */

export * from "./types";
export { generateSeasonTruth } from "./seasonTruth";
export { generateConsistencyScore } from "./consistency";
export { generatePersonaInsight } from "./persona";

import type { InsightInputData, TeamInsight, TeamInsightsResponse } from "./types";
import { generateSeasonTruth } from "./seasonTruth";
import { generateConsistencyScore } from "./consistency";
import { generatePersonaInsight } from "./persona";

/**
 * Generate all insights for a team
 */
export function generateAllInsights(data: InsightInputData): TeamInsightsResponse {
  const insights: TeamInsight[] = [
    generateSeasonTruth(data),
    generateConsistencyScore(data),
    generatePersonaInsight(data),
  ];

  return {
    teamId: data.team.team_id_master,
    teamName: data.team.team_name,
    insights,
    generatedAt: new Date().toISOString(),
  };
}

/**
 * Get a featured insight for preview display
 * Returns the most "interesting" insight for quick display
 */
export function getFeaturedInsight(data: InsightInputData): TeamInsight {
  const persona = generatePersonaInsight(data);

  // Prioritize non-Wildcard personas as they're more distinctive
  if (persona.label !== "Wildcard") {
    return persona;
  }

  // Next priority: Strong consistency scores
  const consistency = generateConsistencyScore(data);
  if (consistency.label === "very reliable" || consistency.label === "highly volatile") {
    return consistency;
  }

  // Fall back to season truth
  return generateSeasonTruth(data);
}
