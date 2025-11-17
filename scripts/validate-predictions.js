#!/usr/bin/env node
/**
 * Match Prediction Validation Script
 *
 * Validates prediction accuracy using historical game data
 * Tests simple power-score based predictions
 *
 * Usage: node scripts/validate-predictions.js
 */

const { createClient } = require('@supabase/supabase-js');

// Configuration
const LOOKBACK_DAYS = 180;
const GAME_LIMIT = 1000;
const MIN_GAMES_PLAYED = 3;

// Prediction parameters (tunable)
const SENSITIVITY = 5.0;  // Higher = more sensitive to power differences
const MARGIN_COEFFICIENT = 8.0;  // Power diff to goal margin conversion

/**
 * Simple logistic function for win probability
 */
function sigmoid(x) {
  return 1 / (1 + Math.exp(-x));
}

/**
 * Predict match outcome
 */
function predictMatch(teamA, teamB) {
  const powerDiff = teamA.power_score_final - teamB.power_score_final;

  // Win probability
  const winProbA = sigmoid(SENSITIVITY * powerDiff);

  // Expected goal margin
  const predictedMargin = powerDiff * MARGIN_COEFFICIENT;

  return {
    predictedMargin,
    winProbA,
    powerDiff,
    sosDiff: teamA.sos_norm - teamB.sos_norm
  };
}

/**
 * Main validation function
 */
async function validate() {
  console.log('\n' + '='.repeat(70));
  console.log('MATCH PREDICTION VALIDATION');
  console.log('='.repeat(70));

  // Initialize Supabase
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_SERVICE_KEY;

  if (!supabaseUrl || !supabaseKey) {
    console.error('\n❌ Error: Missing Supabase credentials');
    console.error('Required: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY');
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  // Fetch rankings
  console.log('\n📊 Fetching current rankings...');
  const { data: rankingsData, error: rankingsError } = await supabase
    .from('rankings_view')
    .select('team_id_master, team_name, power_score_final, sos_norm, offense_norm, defense_norm, win_percentage, games_played');

  if (rankingsError) {
    console.error('❌ Error fetching rankings:', rankingsError);
    process.exit(1);
  }

  console.log(`✅ Loaded ${rankingsData.length} team rankings`);

  // Create rankings map
  const rankings = new Map();
  rankingsData.forEach(team => {
    rankings.set(team.team_id_master, team);
  });

  // Fetch recent games
  console.log(`\n📅 Fetching games from last ${LOOKBACK_DAYS} days...`);
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - LOOKBACK_DAYS);

  const { data: gamesData, error: gamesError } = await supabase
    .from('games')
    .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
    .gte('game_date', cutoffDate.toISOString().split('T')[0])
    .not('home_score', 'is', null)
    .not('away_score', 'is', null)
    .order('game_date', { ascending: false })
    .limit(GAME_LIMIT);

  if (gamesError) {
    console.error('❌ Error fetching games:', gamesError);
    process.exit(1);
  }

  console.log(`✅ Loaded ${gamesData.length} games with scores`);

  // Validate predictions
  console.log('\n🔍 Validating predictions...');
  const predictions = [];
  let skipped = 0;

  for (const game of gamesData) {
    const teamA = rankings.get(game.home_team_master_id);
    const teamB = rankings.get(game.away_team_master_id);

    // Skip if rankings not available
    if (!teamA || !teamB) {
      skipped++;
      continue;
    }

    // Skip if insufficient games
    if (teamA.games_played < MIN_GAMES_PLAYED || teamB.games_played < MIN_GAMES_PLAYED) {
      skipped++;
      continue;
    }

    // Actual outcome
    const actualScoreA = game.home_score;
    const actualScoreB = game.away_score;
    const actualMargin = actualScoreA - actualScoreB;

    let actualWinner;
    if (actualMargin > 0) actualWinner = 'a';
    else if (actualMargin < 0) actualWinner = 'b';
    else actualWinner = 'draw';

    // Predict
    const pred = predictMatch(teamA, teamB);

    // Predicted winner (with 5% threshold to avoid too many draws)
    let predictedWinner;
    if (pred.winProbA > 0.55) predictedWinner = 'a';
    else if (pred.winProbA < 0.45) predictedWinner = 'b';
    else predictedWinner = 'draw';

    const correct = predictedWinner === actualWinner;

    predictions.push({
      gameDate: game.game_date,
      teamAName: teamA.team_name,
      teamBName: teamB.team_name,
      actualScoreA,
      actualScoreB,
      actualMargin,
      actualWinner,
      predictedMargin: pred.predictedMargin,
      winProbA: pred.winProbA,
      predictedWinner,
      correct,
      powerDiff: pred.powerDiff,
      sosDiff: pred.sosDiff
    });
  }

  console.log(`✅ Validated ${predictions.length} games (skipped ${skipped})`);

  if (predictions.length === 0) {
    console.log('\n❌ No predictions to validate!');
    process.exit(1);
  }

  // Calculate metrics
  const correct = predictions.filter(p => p.correct).length;
  const directionAccuracy = correct / predictions.length;

  const marginErrors = predictions.map(p => Math.abs(p.predictedMargin - p.actualMargin));
  const mae = marginErrors.reduce((a, b) => a + b, 0) / marginErrors.length;
  const rmse = Math.sqrt(marginErrors.reduce((a, b) => a + b * b, 0) / marginErrors.length);

  // Brier score
  const brierScores = predictions.map(p => {
    const actualOutcome = p.actualWinner === 'a' ? 1.0 : 0.0;
    return Math.pow(p.winProbA - actualOutcome, 2);
  });
  const brierScore = brierScores.reduce((a, b) => a + b, 0) / brierScores.length;

  // Confidence breakdown
  const highConf = predictions.filter(p => Math.abs(p.winProbA - 0.5) > 0.2);
  const lowConf = predictions.filter(p => Math.abs(p.winProbA - 0.5) <= 0.2);

  const highConfAccuracy = highConf.length > 0
    ? highConf.filter(p => p.correct).length / highConf.length
    : 0;
  const lowConfAccuracy = lowConf.length > 0
    ? lowConf.filter(p => p.correct).length / lowConf.length
    : 0;

  // Print report
  console.log('\n' + '='.repeat(70));
  console.log('VALIDATION RESULTS');
  console.log('='.repeat(70));

  console.log(`\n📊 OVERALL METRICS (n=${predictions.length} games)`);
  console.log('-'.repeat(70));
  console.log(`Direction Accuracy:     ${(directionAccuracy * 100).toFixed(1)}% (${correct}/${predictions.length})`);
  console.log(`MAE (Goal Margin):      ${mae.toFixed(2)} goals`);
  console.log(`RMSE (Goal Margin):     ${rmse.toFixed(2)} goals`);
  console.log(`Brier Score:            ${brierScore.toFixed(3)} (lower is better, <0.20 is good)`);

  console.log(`\n🎯 BY CONFIDENCE LEVEL`);
  console.log('-'.repeat(70));
  console.log(`High Confidence (>70%): ${(highConfAccuracy * 100).toFixed(1)}% accurate (n=${highConf.length})`);
  console.log(`Low Confidence (50-70%): ${(lowConfAccuracy * 100).toFixed(1)}% accurate (n=${lowConf.length})`);

  // Calibration
  console.log(`\n📈 CALIBRATION ANALYSIS`);
  console.log('-'.repeat(70));
  console.log('Probability Bin'.padEnd(20) + 'Count'.padEnd(10) + 'Predicted'.padEnd(12) + 'Actual'.padEnd(12) + 'Error');
  console.log('-'.repeat(70));

  const bins = [
    [0.0, 0.1], [0.1, 0.2], [0.2, 0.3], [0.3, 0.4], [0.4, 0.5],
    [0.5, 0.6], [0.6, 0.7], [0.7, 0.8], [0.8, 0.9], [0.9, 1.0]
  ];

  for (const [binMin, binMax] of bins) {
    const binPreds = predictions.filter(p => p.winProbA >= binMin && p.winProbA < binMax);
    if (binPreds.length === 0) continue;

    const actualWins = binPreds.filter(p => p.actualWinner === 'a').length;
    const actualRate = actualWins / binPreds.length;
    const expectedRate = (binMin + binMax) / 2;
    const error = Math.abs(actualRate - expectedRate);

    console.log(
      `${binMin.toFixed(1)}-${binMax.toFixed(1)}`.padEnd(20) +
      binPreds.length.toString().padEnd(10) +
      `${(expectedRate * 100).toFixed(1)}%`.padEnd(12) +
      `${(actualRate * 100).toFixed(1)}%`.padEnd(12) +
      `${(error * 100).toFixed(1)}%`
    );
  }

  // Sample predictions
  console.log(`\n📋 SAMPLE PREDICTIONS`);
  console.log('-'.repeat(70));

  const correctSamples = predictions.filter(p => p.correct).slice(0, 5);
  const incorrectSamples = predictions.filter(p => !p.correct).slice(0, 5);

  console.log('\n✅ CORRECT PREDICTIONS:');
  for (const p of correctSamples) {
    console.log(`  ${p.teamAName} vs ${p.teamBName}`);
    console.log(`    Actual: ${p.actualScoreA}-${p.actualScoreB} | Predicted: ${(p.winProbA * 100).toFixed(0)}% for ${p.teamAName}`);
    console.log(`    Power diff: ${p.powerDiff >= 0 ? '+' : ''}${p.powerDiff.toFixed(3)}`);
  }

  console.log('\n❌ INCORRECT PREDICTIONS:');
  for (const p of incorrectSamples) {
    console.log(`  ${p.teamAName} vs ${p.teamBName}`);
    console.log(`    Actual: ${p.actualScoreA}-${p.actualScoreB} | Predicted: ${(p.winProbA * 100).toFixed(0)}% for ${p.teamAName}`);
    console.log(`    Power diff: ${p.powerDiff >= 0 ? '+' : ''}${p.powerDiff.toFixed(3)}`);
  }

  // Interpretation
  console.log('\n' + '='.repeat(70));
  console.log('INTERPRETATION');
  console.log('='.repeat(70));

  if (directionAccuracy >= 0.70) {
    console.log('✅ EXCELLENT: >70% direction accuracy is very good for sports prediction');
  } else if (directionAccuracy >= 0.60) {
    console.log('✅ GOOD: 60-70% direction accuracy is solid and useful');
  } else if (directionAccuracy >= 0.55) {
    console.log('⚠️  FAIR: 55-60% is better than random but could be improved');
  } else {
    console.log('❌ POOR: <55% accuracy suggests predictions need improvement');
  }

  if (brierScore < 0.20) {
    console.log('✅ GOOD: Brier score <0.20 indicates well-calibrated probabilities');
  } else if (brierScore < 0.25) {
    console.log('⚠️  FAIR: Brier score shows room for calibration improvement');
  } else {
    console.log('❌ POOR: Probabilities are poorly calibrated');
  }

  console.log('\n' + '='.repeat(70));
  console.log('\nNEXT STEPS:');
  if (directionAccuracy >= 0.60) {
    console.log('✅ Accuracy is good! Proceed to build explanation engine');
  } else {
    console.log('⚠️  Consider tuning SENSITIVITY and MARGIN_COEFFICIENT parameters');
    console.log(`   Current values: SENSITIVITY=${SENSITIVITY}, MARGIN_COEFFICIENT=${MARGIN_COEFFICIENT}`);
  }
  console.log('='.repeat(70) + '\n');
}

// Run
validate().catch(error => {
  console.error('\n❌ Error:', error.message);
  process.exit(1);
});
