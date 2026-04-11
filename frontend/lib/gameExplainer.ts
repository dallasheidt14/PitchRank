import type { GameExplainability } from './types';

export type GameExplanationTone = 'positive' | 'negative' | 'neutral';

export interface GameBreakdownExplanation {
  headline: string;
  highlightReason: string | null;
  expectationLine: string;
  actualLine: string;
  details: string[];
  tone: GameExplanationTone;
}

const SURPRISE_THRESHOLD = 0.06;
const OFFENSE_THRESHOLD = 0.75;
const DEFENSE_THRESHOLD = 0.75;
const OPPONENT_GAP_THRESHOLD = 75;

function toNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function clampGoals(value: number): number {
  return Math.max(0, value);
}

function roundGoals(value: number): number {
  return Math.max(0, Math.round(value));
}

function buildExpectedScoreline(breakdown: GameExplainability): string | null {
  const gf = toNumber(breakdown.gf);
  const ga = toNumber(breakdown.ga);
  const offResidual = toNumber(breakdown.off_residual);
  const defResidual = toNumber(breakdown.def_residual);

  if (gf === null || ga === null || offResidual === null || defResidual === null) {
    return null;
  }

  const expectedGoalsFor = roundGoals(clampGoals(gf - offResidual));
  const expectedGoalsAgainst = roundGoals(clampGoals(ga + defResidual));
  return `${expectedGoalsFor}-${expectedGoalsAgainst}`;
}

function buildActualScoreline(breakdown: GameExplainability): string | null {
  const gf = toNumber(breakdown.gf);
  const ga = toNumber(breakdown.ga);

  if (gf === null || ga === null) {
    return null;
  }

  return `${roundGoals(gf)}-${roundGoals(ga)}`;
}

function formatGoalAmount(value: number): string {
  const rounded = Math.round(Math.abs(value) * 10) / 10;
  return rounded.toFixed(1);
}

function describeMarginOutcome(value: number): string {
  if (Math.abs(value) < 0.05) {
    return 'draw';
  }

  return value > 0 ? `${formatGoalAmount(value)}-goal win` : `${formatGoalAmount(value)}-goal loss`;
}

function describeTeamResult(scoreline: string, value: number): string {
  if (Math.abs(value) < 0.05) {
    return `This team drew ${scoreline}.`;
  }

  return value > 0 ? `This team won ${scoreline}.` : `This team lost ${scoreline}.`;
}

function getSignal(breakdown: GameExplainability): number {
  return toNumber(breakdown.outcome_surprise) ?? toNumber(breakdown.rating_contribution) ?? 0;
}

function getTone(signal: number): GameExplanationTone {
  if (signal >= SURPRISE_THRESHOLD) return 'positive';
  if (signal <= -SURPRISE_THRESHOLD) return 'negative';
  return 'neutral';
}

function getHeadline(tone: GameExplanationTone): string {
  if (tone === 'positive') return 'Outperformed expectation';
  if (tone === 'negative') return 'Came in below expectation';
  return 'Landed close to expectation';
}

function buildHighlightReason(residual: number | null): string | null {
  if (residual === null) {
    return null;
  }

  if (residual >= 2) {
    return `Result came in ${formatGoalAmount(residual)} goals better than model expectation.`;
  }

  if (residual <= -2) {
    return `Result came in ${formatGoalAmount(residual)} goals worse than model expectation.`;
  }

  return null;
}

function buildExpectationLine(breakdown: GameExplainability, residual: number | null): string {
  const gf = toNumber(breakdown.gf);
  const ga = toNumber(breakdown.ga);

  if (gf !== null && ga !== null && residual !== null) {
    const actualMargin = gf - ga;
    const expectedMargin = actualMargin - residual;
    return `Model expected this team to have a ${describeMarginOutcome(expectedMargin)}.`;
  }

  const expectedScoreline = buildExpectedScoreline(breakdown);
  if (expectedScoreline) {
    return `PitchRank expected roughly ${expectedScoreline}.`;
  }

  return 'PitchRank had this game close to expectation.';
}

function buildActualLine(breakdown: GameExplainability): string {
  const actualScoreline = buildActualScoreline(breakdown);
  if (actualScoreline) {
    const gf = toNumber(breakdown.gf) ?? 0;
    const ga = toNumber(breakdown.ga) ?? 0;
    const actualMargin = gf - ga;
    if (Math.abs(actualMargin) < 0.05) {
      return describeTeamResult(actualScoreline, actualMargin);
    }
    return `${describeTeamResult(actualScoreline, actualMargin)} Margin was ${formatGoalAmount(actualMargin)} goals.`;
  }

  return 'Actual result is unavailable.';
}

function buildDetails(breakdown: GameExplainability, tone: GameExplanationTone): string[] {
  const details: string[] = [];
  const offResidual = toNumber(breakdown.off_residual);
  const defResidual = toNumber(breakdown.def_residual);
  const teamMu = toNumber(breakdown.team_mu);
  const oppMu = toNumber(breakdown.opp_mu);

  if (offResidual !== null) {
    if (offResidual >= OFFENSE_THRESHOLD) {
      details.push('They scored more than PitchRank expected.');
    } else if (offResidual <= -OFFENSE_THRESHOLD) {
      details.push('They scored less than PitchRank expected.');
    }
  }

  if (defResidual !== null) {
    if (defResidual >= DEFENSE_THRESHOLD) {
      details.push('They allowed fewer goals than PitchRank expected.');
    } else if (defResidual <= -DEFENSE_THRESHOLD) {
      details.push('They allowed more goals than PitchRank expected.');
    }
  }

  if (teamMu !== null && oppMu !== null) {
    const ratingGap = oppMu - teamMu;
    if (tone === 'positive' && ratingGap >= OPPONENT_GAP_THRESHOLD) {
      details.push('It stood out more because it came against a stronger opponent.');
    } else if (tone === 'negative' && ratingGap <= -OPPONENT_GAP_THRESHOLD) {
      details.push('It hurt more because PitchRank saw this as the easier matchup.');
    }
  }

  if (details.length === 0 && tone === 'neutral') {
    details.push('Nothing major stood out beyond the result itself.');
  }

  return details.slice(0, 3);
}

export function explainGameBreakdown(
  breakdown: GameExplainability,
  residual: number | null = null
): GameBreakdownExplanation {
  const signal = getSignal(breakdown);
  const tone = getTone(signal);

  return {
    headline: getHeadline(tone),
    highlightReason: buildHighlightReason(residual),
    expectationLine: buildExpectationLine(breakdown, residual),
    actualLine: buildActualLine(breakdown),
    details: buildDetails(breakdown, tone),
    tone,
  };
}
