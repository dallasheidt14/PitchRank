import type {
  HeadToHeadSummary,
  MatchOutcome,
  MissionControlSnapshot,
  ModelPerformanceSummary,
  ModelVersionSummary,
  PipelineSummary,
} from '@/types/mission-control';

const EPSILON = 1e-15;

export interface ProspectiveSnapshotRow {
  fixture_key: string;
  game_date: string | null;
  resolution_status: string | null;
  heuristic_prediction_status: string | null;
  heuristic_model_version: string | null;
  heuristic_prediction: unknown;
  heuristic_predicted_at: string | null;
  offline_prediction_status: string | null;
  offline_model_version: string | null;
  offline_prediction: unknown;
  offline_predicted_at: string | null;
  actual_home_score: number | null;
  actual_away_score: number | null;
  actual_outcome: string | null;
  evaluation_status: string | null;
}

interface ParsedPredictionRow {
  fixtureKey: string;
  gameDate: string | null;
  actualOutcome: MatchOutcome;
  actualScoreA: number | null;
  actualScoreB: number | null;
  actualMargin: number | null;
  predictedOutcome: MatchOutcome;
  probTeamAWin: number;
  probDraw: number;
  probTeamBWin: number;
  predictedScoreA: number | null;
  predictedScoreB: number | null;
  predictedMargin: number | null;
  predictedAt: string | null;
  modelVersion: string | null;
}

function safeJson(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
    } catch {
      return {};
    }
  }
  return {};
}

function safeNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function normalizeOutcome(value: unknown): MatchOutcome | null {
  if (value === 'team_a' || value === 'team_a_win') return 'team_a';
  if (value === 'team_b' || value === 'team_b_win') return 'team_b';
  if (value === 'draw') return 'draw';
  return null;
}

function buildActualOutcome(row: ProspectiveSnapshotRow): MatchOutcome | null {
  const normalized = normalizeOutcome(row.actual_outcome);
  if (normalized) return normalized;
  if (row.actual_home_score == null || row.actual_away_score == null) return null;
  if (row.actual_home_score > row.actual_away_score) return 'team_a';
  if (row.actual_away_score > row.actual_home_score) return 'team_b';
  return 'draw';
}

function normalizeProbabilities(probTeamAWin: number | null, probDraw: number | null, probTeamBWin: number | null) {
  const rawA = Math.max(0, probTeamAWin ?? 0);
  const rawDraw = Math.max(0, probDraw ?? 0);
  const rawB = Math.max(0, probTeamBWin ?? 0);
  const sum = rawA + rawDraw + rawB;
  if (sum <= 0) {
    return {
      teamA: 1 / 3,
      draw: 1 / 3,
      teamB: 1 / 3,
    };
  }
  return {
    teamA: rawA / sum,
    draw: rawDraw / sum,
    teamB: rawB / sum,
  };
}

function argmaxOutcome(probTeamAWin: number, probDraw: number, probTeamBWin: number): MatchOutcome {
  if (probDraw >= probTeamAWin && probDraw >= probTeamBWin) return 'draw';
  return probTeamAWin >= probTeamBWin ? 'team_a' : 'team_b';
}

function parsePrediction(row: ProspectiveSnapshotRow, kind: 'heuristic' | 'offline'): ParsedPredictionRow | null {
  const actualOutcome = buildActualOutcome(row);
  if (!actualOutcome) return null;

  const payload = safeJson(kind === 'heuristic' ? row.heuristic_prediction : row.offline_prediction);
  const prediction =
    kind === 'heuristic'
      ? safeJson(safeJson(payload.response).prediction)
      : safeJson(payload.prediction);

  if (Object.keys(prediction).length === 0) return null;

  const probabilities = normalizeProbabilities(
    safeNumber(prediction.winProbabilityA),
    safeNumber(prediction.drawProbability),
    safeNumber(prediction.winProbabilityB)
  );

  const expectedScore = safeJson(prediction.expectedScore);
  const predictedOutcome = normalizeOutcome(prediction.predictedWinner) ?? argmaxOutcome(probabilities.teamA, probabilities.draw, probabilities.teamB);

  return {
    fixtureKey: row.fixture_key,
    gameDate: row.game_date,
    actualOutcome,
    actualScoreA: row.actual_home_score,
    actualScoreB: row.actual_away_score,
    actualMargin:
      row.actual_home_score != null && row.actual_away_score != null ? row.actual_home_score - row.actual_away_score : null,
    predictedOutcome,
    probTeamAWin: probabilities.teamA,
    probDraw: probabilities.draw,
    probTeamBWin: probabilities.teamB,
    predictedScoreA: safeNumber(expectedScore.teamA),
    predictedScoreB: safeNumber(expectedScore.teamB),
    predictedMargin: safeNumber(prediction.expectedMargin),
    predictedAt: kind === 'heuristic' ? row.heuristic_predicted_at : row.offline_predicted_at,
    modelVersion:
      kind === 'heuristic'
        ? (typeof payload.modelVersion === 'string' ? payload.modelVersion : row.heuristic_model_version)
        : (typeof payload.modelVersion === 'string' ? payload.modelVersion : row.offline_model_version),
  };
}

function mean(values: number[]): number | null {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function roundScore(value: number | null): number | null {
  return value == null ? null : Math.round(value);
}

function computeSummary(rows: ParsedPredictionRow[], modelVersion: string | null): ModelPerformanceSummary {
  if (!rows.length) {
    return {
      modelVersion,
      games: 0,
      winnerAccuracy: null,
      drawRecall: null,
      drawPrecision: null,
      actualDrawRate: null,
      predictedDrawRate: null,
      drawRateGap: null,
      logLoss: null,
      brierScore: null,
      marginMae: null,
      exactScoreAccuracy: null,
      latestPredictedAt: null,
    };
  }

  const correct: number[] = [];
  const drawActualRows: ParsedPredictionRow[] = [];
  const predictedDrawRows: ParsedPredictionRow[] = [];
  const logLossTerms: number[] = [];
  const brierTerms: number[] = [];
  const marginErrors: number[] = [];
  const exactScoreHits: number[] = [];

  let latestPredictedAt: string | null = null;

  for (const row of rows) {
    correct.push(row.predictedOutcome === row.actualOutcome ? 1 : 0);
    if (row.actualOutcome === 'draw') drawActualRows.push(row);
    if (row.predictedOutcome === 'draw') predictedDrawRows.push(row);

    const probs =
      row.actualOutcome === 'team_a'
        ? [row.probTeamAWin, row.probDraw, row.probTeamBWin]
        : row.actualOutcome === 'draw'
          ? [row.probDraw, row.probTeamAWin, row.probTeamBWin]
          : [row.probTeamBWin, row.probTeamAWin, row.probDraw];
    logLossTerms.push(-Math.log(Math.max(EPSILON, probs[0])));

    const actual = {
      team_a: row.actualOutcome === 'team_a' ? 1 : 0,
      draw: row.actualOutcome === 'draw' ? 1 : 0,
      team_b: row.actualOutcome === 'team_b' ? 1 : 0,
    };
    brierTerms.push(
      (row.probTeamAWin - actual.team_a) ** 2 + (row.probDraw - actual.draw) ** 2 + (row.probTeamBWin - actual.team_b) ** 2
    );

    if (row.predictedMargin != null && row.actualMargin != null) {
      marginErrors.push(Math.abs(row.predictedMargin - row.actualMargin));
    }

    if (
      row.predictedScoreA != null &&
      row.predictedScoreB != null &&
      row.actualScoreA != null &&
      row.actualScoreB != null
    ) {
      exactScoreHits.push(
        roundScore(row.predictedScoreA) === row.actualScoreA && roundScore(row.predictedScoreB) === row.actualScoreB ? 1 : 0
      );
    }

    if (row.predictedAt && (!latestPredictedAt || row.predictedAt > latestPredictedAt)) {
      latestPredictedAt = row.predictedAt;
    }
  }

  const winnerAccuracy = mean(correct);
  const drawRecall = drawActualRows.length
    ? drawActualRows.filter((row) => row.predictedOutcome === 'draw').length / drawActualRows.length
    : null;
  const drawPrecision = predictedDrawRows.length
    ? predictedDrawRows.filter((row) => row.actualOutcome === 'draw').length / predictedDrawRows.length
    : null;
  const actualDrawRate = drawActualRows.length / rows.length;
  const predictedDrawRate = predictedDrawRows.length / rows.length;

  return {
    modelVersion,
    games: rows.length,
    winnerAccuracy,
    drawRecall,
    drawPrecision,
    actualDrawRate,
    predictedDrawRate,
    drawRateGap: Math.abs(predictedDrawRate - actualDrawRate),
    logLoss: mean(logLossTerms),
    brierScore: mean(brierTerms),
    marginMae: mean(marginErrors),
    exactScoreAccuracy: mean(exactScoreHits),
    latestPredictedAt,
  };
}

function buildVersionSummaries(rows: ProspectiveSnapshotRow[], kind: 'heuristic' | 'offline'): ModelVersionSummary[] {
  const parsedByVersion = new Map<string, ParsedPredictionRow[]>();

  for (const row of rows) {
    if (row.evaluation_status !== 'settled') continue;
    if ((kind === 'heuristic' ? row.heuristic_prediction_status : row.offline_prediction_status) !== 'completed') continue;
    const parsed = parsePrediction(row, kind);
    if (!parsed?.modelVersion) continue;
    const bucket = parsedByVersion.get(parsed.modelVersion) ?? [];
    bucket.push(parsed);
    parsedByVersion.set(parsed.modelVersion, bucket);
  }

  return Array.from(parsedByVersion.entries())
    .map(([modelVersion, bucket]) => ({
      kind,
      ...computeSummary(bucket, modelVersion),
    }))
    .sort((left, right) => {
      const leftTime = left.latestPredictedAt ?? '';
      const rightTime = right.latestPredictedAt ?? '';
      if (leftTime !== rightTime) return rightTime.localeCompare(leftTime);
      return right.games - left.games;
    });
}

function buildHeadToHead(rows: ProspectiveSnapshotRow[], heuristicVersion: string | null, offlineVersion: string | null): {
  sharedSettledGames: number;
  headToHead: HeadToHeadSummary;
  heuristicSummary: ModelPerformanceSummary;
  offlineSummary: ModelPerformanceSummary;
} {
  const sharedHeuristic: ParsedPredictionRow[] = [];
  const sharedOffline: ParsedPredictionRow[] = [];
  const disagreement: number[] = [];
  const drawDeltas: number[] = [];

  for (const row of rows) {
    if (
      row.evaluation_status !== 'settled' ||
      row.heuristic_prediction_status !== 'completed' ||
      row.offline_prediction_status !== 'completed'
    ) {
      continue;
    }
    if (heuristicVersion && row.heuristic_model_version !== heuristicVersion) continue;
    if (offlineVersion && row.offline_model_version !== offlineVersion) continue;

    const heuristic = parsePrediction(row, 'heuristic');
    const offline = parsePrediction(row, 'offline');
    if (!heuristic || !offline) continue;

    sharedHeuristic.push(heuristic);
    sharedOffline.push(offline);
    disagreement.push(heuristic.predictedOutcome === offline.predictedOutcome ? 0 : 1);
    drawDeltas.push(offline.probDraw - heuristic.probDraw);
  }

  return {
    sharedSettledGames: sharedHeuristic.length,
    headToHead: {
      fixturesWithBothPredictions: sharedHeuristic.length,
      winnerDisagreementRate: mean(disagreement),
      avgDrawProbabilityDeltaOfflineMinusHeuristic: mean(drawDeltas),
    },
    heuristicSummary: computeSummary(sharedHeuristic, heuristicVersion),
    offlineSummary: computeSummary(sharedOffline, offlineVersion),
  };
}

function buildPipelineSummary(rows: ProspectiveSnapshotRow[]): PipelineSummary {
  const evaluationCounts = new Map<string, number>();
  const resolutionCounts = new Map<string, number>();
  let heuristicError = 0;
  let offlineError = 0;

  for (const row of rows) {
    const evaluationStatus = row.evaluation_status ?? 'unknown';
    evaluationCounts.set(evaluationStatus, (evaluationCounts.get(evaluationStatus) ?? 0) + 1);

    const resolutionStatus = row.resolution_status ?? 'unknown';
    resolutionCounts.set(resolutionStatus, (resolutionCounts.get(resolutionStatus) ?? 0) + 1);

    if (row.heuristic_prediction_status === 'error') heuristicError += 1;
    if (row.offline_prediction_status === 'error') offlineError += 1;
  }

  return {
    totalFixtures: rows.length,
    settled: evaluationCounts.get('settled') ?? 0,
    pendingResult: evaluationCounts.get('pending_result') ?? 0,
    pendingResolution: (resolutionCounts.get('partial') ?? 0) + (resolutionCounts.get('unresolved') ?? 0) + (resolutionCounts.get('pending') ?? 0),
    resultNotFound: evaluationCounts.get('result_not_found') ?? 0,
    ambiguousResult: evaluationCounts.get('ambiguous_result') ?? 0,
    heuristicError,
    offlineError,
    resolutionStatusCounts: Array.from(resolutionCounts.entries())
      .map(([status, count]) => ({ status, count }))
      .sort((left, right) => right.count - left.count),
  };
}

export function buildMissionControlSnapshot(
  rows: ProspectiveSnapshotRow[],
  pitCoverage: MissionControlSnapshot['pitCoverage']
): MissionControlSnapshot {
  const heuristicVersions = buildVersionSummaries(rows, 'heuristic');
  const offlineVersions = buildVersionSummaries(rows, 'offline');
  const currentHeuristicVersion = heuristicVersions[0]?.modelVersion ?? null;
  const currentOfflineVersion = offlineVersions[0]?.modelVersion ?? null;
  const { sharedSettledGames, headToHead, heuristicSummary, offlineSummary } = buildHeadToHead(
    rows,
    currentHeuristicVersion,
    currentOfflineVersion
  );

  return {
    generatedAt: new Date().toISOString(),
    currentHeuristicVersion,
    currentOfflineVersion,
    sharedSettledGames,
    headToHead,
    heuristic: heuristicSummary,
    offline: offlineSummary,
    offlineVersions,
    pipeline: buildPipelineSummary(rows),
    pitCoverage,
  };
}
