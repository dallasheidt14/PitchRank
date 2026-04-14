export type MatchOutcome = 'team_a' | 'draw' | 'team_b';

export interface ModelPerformanceSummary {
  modelVersion: string | null;
  games: number;
  winnerAccuracy: number | null;
  drawRecall: number | null;
  drawPrecision: number | null;
  actualDrawRate: number | null;
  predictedDrawRate: number | null;
  drawRateGap: number | null;
  logLoss: number | null;
  brierScore: number | null;
  marginMae: number | null;
  exactScoreAccuracy: number | null;
  latestPredictedAt: string | null;
}

export interface ModelVersionSummary extends ModelPerformanceSummary {
  kind: 'heuristic' | 'offline';
}

export interface HeadToHeadSummary {
  fixturesWithBothPredictions: number;
  winnerDisagreementRate: number | null;
  avgDrawProbabilityDeltaOfflineMinusHeuristic: number | null;
}

export interface PipelineSummary {
  totalFixtures: number;
  settled: number;
  pendingResult: number;
  pendingResolution: number;
  resultNotFound: number;
  ambiguousResult: number;
  heuristicError: number;
  offlineError: number;
  resolutionStatusCounts: Array<{ status: string; count: number }>;
}

export interface PitCoverageSummary {
  snapshotRows: number | null;
  windowStart: string | null;
  windowEnd: string | null;
  totalScoredGames: number | null;
  trainableScoredGames: number | null;
  last365ScoredGames: number | null;
  last365TrainableGames: number | null;
}

export interface MissionControlSnapshot {
  generatedAt: string;
  currentHeuristicVersion: string | null;
  currentOfflineVersion: string | null;
  sharedSettledGames: number;
  headToHead: HeadToHeadSummary;
  heuristic: ModelPerformanceSummary;
  offline: ModelPerformanceSummary;
  offlineVersions: ModelVersionSummary[];
  pipeline: PipelineSummary;
  pitCoverage: PitCoverageSummary;
}
