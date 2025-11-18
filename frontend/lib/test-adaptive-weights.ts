/**
 * Test script to verify adaptive weight improvements
 *
 * Example: 14B Engilman (32.85) vs Dynamos (46.96)
 * Power diff: 0.1411 (14.11 percentile points)
 */

// Simulate the calculation
const BASE_WEIGHTS = {
  POWER_SCORE: 0.50,
  SOS: 0.18,
  RECENT_FORM: 0.28,
  MATCHUP: 0.04,
};

const BLOWOUT_WEIGHTS = {
  POWER_SCORE: 0.75,
  SOS: 0.10,
  RECENT_FORM: 0.12,
  MATCHUP: 0.03,
};

function getAdaptiveWeights(powerDiff: number) {
  const absPowerDiff = Math.abs(powerDiff);

  if (absPowerDiff < 0.10) return BASE_WEIGHTS;
  if (absPowerDiff >= 0.15) return BLOWOUT_WEIGHTS;

  const transitionProgress = (absPowerDiff - 0.10) / (0.15 - 0.10);

  return {
    POWER_SCORE: BASE_WEIGHTS.POWER_SCORE +
      (BLOWOUT_WEIGHTS.POWER_SCORE - BASE_WEIGHTS.POWER_SCORE) * transitionProgress,
    SOS: BASE_WEIGHTS.SOS +
      (BLOWOUT_WEIGHTS.SOS - BASE_WEIGHTS.SOS) * transitionProgress,
    RECENT_FORM: BASE_WEIGHTS.RECENT_FORM +
      (BLOWOUT_WEIGHTS.RECENT_FORM - BASE_WEIGHTS.RECENT_FORM) * transitionProgress,
    MATCHUP: BASE_WEIGHTS.MATCHUP +
      (BLOWOUT_WEIGHTS.MATCHUP - BASE_WEIGHTS.MATCHUP) * transitionProgress,
  };
}

// Test case: 14B Engilman vs Dynamos
const powerDiff = 0.3285 - 0.4696; // -0.1411
const weights = getAdaptiveWeights(powerDiff);

console.log('\n=== ADAPTIVE WEIGHTS TEST ===\n');
console.log('Power Score Differential:', powerDiff.toFixed(4), '(14.11 percentile points)');
console.log('\nOLD Weights (Fixed 50%):');
console.log('  Power Score: 50%');
console.log('  SOS: 18%');
console.log('  Recent Form: 28%');
console.log('  Matchup: 4%');

console.log('\nNEW Weights (Adaptive):');
console.log('  Power Score:', (weights.POWER_SCORE * 100).toFixed(1) + '%');
console.log('  SOS:', (weights.SOS * 100).toFixed(1) + '%');
console.log('  Recent Form:', (weights.RECENT_FORM * 100).toFixed(1) + '%');
console.log('  Matchup:', (weights.MATCHUP * 100).toFixed(1) + '%');

// Calculate impact
const oldPowerContribution = 0.50 * powerDiff;
const newPowerContribution = weights.POWER_SCORE * powerDiff;

console.log('\nPower Score Contribution:');
console.log('  OLD:', oldPowerContribution.toFixed(4));
console.log('  NEW:', newPowerContribution.toFixed(4));
console.log('  Improvement:', ((newPowerContribution - oldPowerContribution) * 100).toFixed(2) + '%');

// Estimate final compositeDiff (assuming other factors are neutral/small)
const MARGIN_COEFFICIENT = 8.0;

// For the new system, also apply margin amplification
const oldCompositeDiff = oldPowerContribution; // Simplified (assuming other factors neutral)
const newCompositeDiff = newPowerContribution; // Simplified

// Calculate margin amplification for new system
const absCompositeDiff = Math.abs(newCompositeDiff);
let marginMultiplier = 1.0;

if (absCompositeDiff > 0.12) {
  marginMultiplier = 2.5;
} else if (absCompositeDiff > 0.08) {
  const transitionProgress = (absCompositeDiff - 0.08) / (0.12 - 0.08);
  marginMultiplier = 1.0 + (1.5 * transitionProgress);
}

const oldMargin = oldCompositeDiff * MARGIN_COEFFICIENT;
const newMargin = newCompositeDiff * MARGIN_COEFFICIENT * marginMultiplier;

console.log('\nMargin Amplification:');
console.log('  Multiplier:', marginMultiplier.toFixed(2) + 'x', '(for compositeDiff', absCompositeDiff.toFixed(4) + ')');

console.log('\nExpected Goal Margin:');
console.log('  OLD:', oldMargin.toFixed(2), 'goals');
console.log('  NEW (base):', (newCompositeDiff * MARGIN_COEFFICIENT).toFixed(2), 'goals');
console.log('  NEW (amplified):', newMargin.toFixed(2), 'goals');

const leagueAvg = 2.5;
console.log('\nExpected Score:');
console.log('  OLD:', (leagueAvg + oldMargin/2).toFixed(1), 'vs', (leagueAvg - oldMargin/2).toFixed(1));
console.log('  NEW:', (leagueAvg + newMargin/2).toFixed(1), 'vs', (leagueAvg - newMargin/2).toFixed(1));

// Calculate win probability using sigmoid
function sigmoid(x: number): number {
  return 1 / (1 + Math.exp(-x));
}

const SENSITIVITY = 4.5;
const oldWinProb = sigmoid(SENSITIVITY * oldCompositeDiff);
const newWinProb = sigmoid(SENSITIVITY * newCompositeDiff);

console.log('\nWin Probability (Dynamos):');
console.log('  OLD:', (oldWinProb * 100).toFixed(0) + '%');
console.log('  NEW:', (newWinProb * 100).toFixed(0) + '%');

console.log('\n=============================\n');
