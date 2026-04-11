import type { GameExplainability } from './types';

export type GameExplainabilityTone = 'positive' | 'negative' | 'neutral';

export interface GameExplainabilityFactor {
  label: string;
  detail: string;
  tone: GameExplainabilityTone;
}

export interface GameExplainabilityMetric {
  label: string;
  value: string;
}

export interface GameExplainabilitySummary {
  headline: string;
  summary: string;
  impactLabel: string;
  impactTone: GameExplainabilityTone;
  factors: GameExplainabilityFactor[];
  metrics: GameExplainabilityMetric[];
}

interface ScoredFactor extends GameExplainabilityFactor {
  score: number;
}

function toNumber(value: number | null | undefined, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function formatSigned(value: number, digits = 3): string {
  const rounded = value.toFixed(digits);
  return value > 0 ? `+${rounded}` : rounded;
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatWeight(weight: number): string {
  if (weight >= 1.15) return 'High';
  if (weight >= 0.95) return 'Normal';
  if (weight >= 0.8) return 'Light';
  return 'Very light';
}

function impactLabel(absContribution: number): string {
  if (absContribution >= 0.18) return 'Major rating swing';
  if (absContribution >= 0.08) return 'Meaningful rating swing';
  if (absContribution >= 0.03) return 'Modest rating nudge';
  return 'Light rating touch';
}

function impactTone(contribution: number): GameExplainabilityTone {
  if (contribution >= 0.015) return 'positive';
  if (contribution <= -0.015) return 'negative';
  return 'neutral';
}

function surpriseFactor(surprise: number): ScoredFactor | null {
  const absSurprise = Math.abs(surprise);
  if (absSurprise < 0.14) return null;

  if (surprise > 0) {
    return {
      label: absSurprise >= 0.28 ? 'Big result above expectation' : 'Beat expectation',
      detail:
        absSurprise >= 0.28
          ? 'The team got much more from this game than the rating model expected going in.'
          : 'The result landed above the pregame expectation, which lifted its rating value.',
      tone: 'positive',
      score: absSurprise * 3,
    };
  }

  return {
    label: absSurprise >= 0.28 ? 'Big miss versus expectation' : 'Below expectation',
    detail:
      absSurprise >= 0.28
        ? 'The result came in well short of expectation, so this game dragged on the rating.'
        : 'The team got less from this result than expected, which limited its rating value.',
    tone: 'negative',
    score: absSurprise * 3,
  };
}

function opponentFactor(teamMu: number, oppMu: number): ScoredFactor | null {
  const gap = oppMu - teamMu;
  const absGap = Math.abs(gap);
  if (absGap < 65) return null;

  if (gap > 0) {
    return {
      label: absGap >= 125 ? 'Stepped up in class' : 'Faced a stronger opponent',
      detail:
        absGap >= 125
          ? 'This came against a clearly stronger opponent, so overperforming carried extra value.'
          : 'The opponent profile was stronger than this team’s, which raised the leverage of the result.',
      tone: 'positive',
      score: absGap / 100,
    };
  }

  return {
    label: absGap >= 125 ? 'Result against weaker opposition' : 'Faced a weaker opponent',
    detail:
      absGap >= 125
        ? 'Because the opponent rated much lower, this result had less room to create upside.'
        : 'The opponent profile was weaker, so the bar to impress was higher in this matchup.',
    tone: 'neutral',
    score: absGap / 110,
  };
}

function recencyFactor(weight: number): ScoredFactor | null {
  if (weight >= 1.05) {
    return {
      label: weight >= 1.18 ? 'Recent result carried extra weight' : 'Recent result',
      detail:
        weight >= 1.18
          ? 'This game sits near the front of the ranking window, so it counted more than an average result.'
          : 'This result is recent enough to matter more than an older game in the same sample.',
      tone: 'neutral',
      score: weight,
    };
  }

  if (weight <= 0.82) {
    return {
      label: 'Older result in the sample',
      detail: 'This game still counted, but its influence was reduced because it is older in the ranking window.',
      tone: 'neutral',
      score: 1 - weight,
    };
  }

  return null;
}

function offenseFactor(offResidual: number): ScoredFactor | null {
  const absResidual = Math.abs(offResidual);
  if (absResidual < 0.6) return null;

  if (offResidual > 0) {
    return {
      label: absResidual >= 1.4 ? 'Attack surged past expectation' : 'Attack beat expectation',
      detail:
        absResidual >= 1.4
          ? 'The team scored far more than its rating context would normally project in this spot.'
          : 'The attack created a bit more than expected against this opponent.',
      tone: 'positive',
      score: absResidual,
    };
  }

  return {
    label: absResidual >= 1.4 ? 'Attack fell well short' : 'Attack fell short',
    detail:
      absResidual >= 1.4
        ? 'The team scored materially less than expected, which capped the game’s upside.'
        : 'The attack finished a little below what the matchup suggested.',
    tone: 'negative',
    score: absResidual,
  };
}

function defenseFactor(defResidual: number): ScoredFactor | null {
  const absResidual = Math.abs(defResidual);
  if (absResidual < 0.6) return null;

  if (defResidual > 0) {
    return {
      label: absResidual >= 1.4 ? 'Defense shut the door' : 'Defense beat expectation',
      detail:
        absResidual >= 1.4
          ? 'The team allowed far less than expected, which made this result look sturdier to the model.'
          : 'The defense held the opponent slightly below expectation.',
      tone: 'positive',
      score: absResidual,
    };
  }

  return {
    label: absResidual >= 1.4 ? 'Defense leaked chances' : 'Defense fell short',
    detail:
      absResidual >= 1.4
        ? 'The team conceded materially more than expected, which hurt the game’s rating value.'
        : 'The defense allowed a little more than the matchup baseline.',
    tone: 'negative',
    score: absResidual,
  };
}

export function explainGameBreakdown(breakdown: GameExplainability): GameExplainabilitySummary {
  const contribution = toNumber(breakdown.rating_contribution);
  const absContribution = Math.abs(contribution);
  const surprise = toNumber(breakdown.outcome_surprise);
  const expected = toNumber(breakdown.expected_outcome);
  const actual = toNumber(breakdown.actual_outcome);
  const recencyWeight = toNumber(breakdown.recency_weight, 1);
  const teamMu = toNumber(breakdown.team_mu, 1500);
  const oppMu = toNumber(breakdown.opp_mu, 1500);
  const offResidual = toNumber(breakdown.off_residual);
  const defResidual = toNumber(breakdown.def_residual);

  const tone = impactTone(contribution);
  const headline =
    tone === 'positive'
      ? absContribution >= 0.08
        ? 'This game helped the rating'
        : 'This game added a small boost'
      : tone === 'negative'
        ? absContribution >= 0.08
          ? 'This game pulled the rating down'
          : 'This game cost a little ground'
        : 'This game was close to neutral';

  let summary = 'The result landed close to expectation, so its net rating effect stayed fairly contained.';
  if (tone === 'positive') {
    summary =
      actual > expected
        ? 'The team outperformed the pregame expectation, so this result added positive rating value.'
        : 'The game still graded positively overall, even if it was not a dramatic swing.';
  } else if (tone === 'negative') {
    summary =
      actual < expected
        ? 'The team came in below the pregame expectation, so this result pulled on the rating.'
        : 'This game graded negatively overall once opponent context and performance details were applied.';
  }

  const factors = [
    surpriseFactor(surprise),
    opponentFactor(teamMu, oppMu),
    recencyFactor(recencyWeight),
    offenseFactor(offResidual),
    defenseFactor(defResidual),
  ]
    .filter((factor): factor is ScoredFactor => factor !== null)
    .sort((a, b) => b.score - a.score)
    .slice(0, 4)
    .map(({ score: _score, ...factor }) => factor);

  const metrics: GameExplainabilityMetric[] = [
    { label: 'Expected result', value: formatPercent(expected) },
    { label: 'Actual result', value: formatPercent(actual) },
    { label: 'Rating impact', value: formatSigned(contribution) },
    { label: 'Recency weight', value: formatWeight(recencyWeight) },
  ];

  return {
    headline,
    summary,
    impactLabel: impactLabel(absContribution),
    impactTone: tone,
    factors,
    metrics,
  };
}
