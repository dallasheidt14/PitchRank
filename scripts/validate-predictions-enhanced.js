#!/usr/bin/env node
/**
 * Enhanced Match Prediction Validation Script
 *
 * This version adds multiple features to improve accuracy for close matchups:
 * - Recent form (last 5 games goal differential)
 * - SOS differential (battle-tested ratings)
 * - Offense vs Defense matchup asymmetry
 * - Composite scoring with tunable weights
 *
 * Usage: node scripts/validate-predictions-enhanced.js
 */

const { createClient } = require('@supabase/supabase-js');

// ============================================================================
// CONFIGURATION - Tune these parameters
// ============================================================================

const LOOKBACK_DAYS = 180;
const GAME_LIMIT = 1000;
const MIN_GAMES_PLAYED = 3;

// Feature weights (should sum to ~1.0 for main features)
const WEIGHTS = {
  POWER_SCORE: 0.50,      // Base power score differential
  SOS: 0.20,              // Strength of schedule differential
  RECENT_FORM: 0.20,      // Last 5 games performance
  MATCHUP: 0.10,          // Offense vs defense asymmetry
};

// Prediction parameters
const SENSITIVITY = 4.5;         // Logistic function sensitivity (lower = less sensitive)
const MARGIN_COEFFICIENT = 8.0;  // Power diff to goal margin conversion
const RECENT_GAMES_COUNT = 5;    // Number of recent games for form calculation

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Simple logistic function for win probability
 */
function sigmoid(x) {
  return 1 / (1 + Math.exp(-x));
}

/**
 * Calculate recent form from game history
 * Returns average goal differential in last N games
 */
function calculateRecentForm(teamId, allGames, n = RECENT_GAMES_COUNT) {
  // Get team's recent games
  const teamGames = allGames
    .filter(g => g.home_team_master_id === teamId || g.away_team_master_id === teamId)
    .sort((a, b) => new Date(b.game_date) - new Date(a.game_date))
    .slice(0, n);

  if (teamGames.length === 0) return 0;

  // Calculate average goal differential
  let totalGoalDiff = 0;
  let gamesWithScores = 0;

  for (const game of teamGames) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && oppScore !== null) {
      totalGoalDiff += (teamScore - oppScore);
      gamesWithScores++;
    }
  }

  return gamesWithScores > 0 ? totalGoalDiff / gamesWithScores : 0;
}

/**
 * Calculate normalized recent form (0-1 scale)
 * Typical youth soccer: -3 to +3 goal differential per game
 */
function normalizeRecentForm(goalDiff) {
  // Sigmoid normalization centered at 0
  // goalDiff of +2 -> ~0.73, -2 -> ~0.27
  return sigmoid(goalDiff * 0.5);
}

/**
 * Enhanced match prediction with multiple features
 */
function predictMatchEnhanced(teamA, teamB, allGames) {
  // 1. Base power score differential
  const powerDiff = teamA.power_score_final - teamB.power_score_final;

  // 2. SOS differential (already normalized 0-1)
  const sosDiff = (teamA.sos_norm || 0.5) - (teamB.sos_norm || 0.5);

  // 3. Recent form
  const formA = calculateRecentForm(teamA.team_id_master, allGames);
  const formB = calculateRecentForm(teamB.team_id_master, allGames);
  const formDiffRaw = formA - formB;

  // Normalize form to 0-1 scale, then center around 0
  const formDiffNorm = normalizeRecentForm(formDiffRaw) - 0.5;

  // 4. Offense vs Defense matchup asymmetry
  // How good is A's offense vs B's defense, and vice versa
  const offenseA = teamA.offense_norm || 0.5;
  const defenseA = teamA.defense_norm || 0.5;
  const offenseB = teamB.offense_norm || 0.5;
  const defenseB = teamB.defense_norm || 0.5;

  // A's offense advantage vs B's defense minus B's offense advantage vs A's defense
  const matchupAdvantage = (offenseA - defenseB) - (offenseB - defenseA);

  // 5. Composite differential (weighted combination)
  const compositeDiff =
    WEIGHTS.POWER_SCORE * powerDiff +
    WEIGHTS.SOS * sosDiff +
    WEIGHTS.RECENT_FORM * formDiffNorm +
    WEIGHTS.MATCHUP * matchupAdvantage;

  // 6. Win probability using composite differential
  const winProbA = sigmoid(SENSITIVITY * compositeDiff);

  // 7. Expected goal margin
  const predictedMargin = compositeDiff * MARGIN_COEFFICIENT;

  return {
    predictedMargin,
    winProbA,
    compositeDiff,

    // Component breakdowns for analysis
    components: {
      powerDiff,
      sosDiff,
      formDiffRaw,
      formDiffNorm,
      matchupAdvantage,
      formA,
      formB,
    }
  };
}

/**
 * Simple prediction (original version for comparison)
 */
function predictMatchSimple(teamA, teamB) {
  const powerDiff = teamA.power_score_final - teamB.power_score_final;
  const winProbA = sigmoid(5.0 * powerDiff);
  const predictedMargin = powerDiff * 8.0;

  return {
    predictedMargin,
    winProbA,
    powerDiff,
  };
}

// ============================================================================
// VALIDATION LOGIC
// ============================================================================

async function validate() {
  console.log('\n' + '='.repeat(70));
  console.log('ENHANCED MATCH PREDICTION VALIDATION');
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

  // Fetch ALL games (not just recent) for form calculation
  console.log(`\n📅 Fetching all games for form calculation...`);
  const { data: allGamesData, error: allGamesError } = await supabase
    .from('games')
    .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
    .not('home_score', 'is', null)
    .not('away_score', 'is', null)
    .order('game_date', { ascending: false })
    .limit(10000);  // Get more games for form calculation

  if (allGamesError) {
    console.error('❌ Error fetching all games:', allGamesError);
    process.exit(1);
  }

  console.log(`✅ Loaded ${allGamesData.length} games for form analysis`);

  // Fetch recent games for validation
  console.log(`\n📅 Fetching games from last ${LOOKBACK_DAYS} days for validation...`);
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - LOOKBACK_DAYS);

  const { data: validationGamesData, error: validationGamesError } = await supabase
    .from('games')
    .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
    .gte('game_date', cutoffDate.toISOString().split('T')[0])
    .not('home_score', 'is', null)
    .not('away_score', 'is', null)
    .order('game_date', { ascending: false })
    .limit(GAME_LIMIT);

  if (validationGamesError) {
    console.error('❌ Error fetching validation games:', validationGamesError);
    process.exit(1);
  }

  console.log(`✅ Loaded ${validationGamesData.length} games for validation`);

  // Validate predictions - both simple and enhanced
  console.log('\n🔍 Validating predictions...');
  console.log(`   Using weights: Power=${WEIGHTS.POWER_SCORE}, SOS=${WEIGHTS.SOS}, Form=${WEIGHTS.RECENT_FORM}, Matchup=${WEIGHTS.MATCHUP}`);

  const predictionsSimple = [];
  const predictionsEnhanced = [];
  let skipped = 0;

  for (const game of validationGamesData) {
    const teamA = rankings.get(game.home_team_master_id);
    const teamB = rankings.get(game.away_team_master_id);

    if (!teamA || !teamB) {
      skipped++;
      continue;
    }

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

    // Simple prediction
    const predSimple = predictMatchSimple(teamA, teamB);
    // Always pick the favored team (no draw threshold - draws only occur ~16% of the time)
    let predictedWinnerSimple = predSimple.winProbA >= 0.5 ? 'a' : 'b';

    predictionsSimple.push({
      gameDate: game.game_date,
      teamAName: teamA.team_name,
      teamBName: teamB.team_name,
      actualScoreA,
      actualScoreB,
      actualMargin,
      actualWinner,
      predictedMargin: predSimple.predictedMargin,
      winProbA: predSimple.winProbA,
      predictedWinner: predictedWinnerSimple,
      correct: predictedWinnerSimple === actualWinner,
      powerDiff: predSimple.powerDiff,
    });

    // Enhanced prediction
    const predEnhanced = predictMatchEnhanced(teamA, teamB, allGamesData);
    // Always pick the favored team (no draw threshold - draws only occur ~16% of the time)
    let predictedWinnerEnhanced = predEnhanced.winProbA >= 0.5 ? 'a' : 'b';

    predictionsEnhanced.push({
      gameDate: game.game_date,
      teamAName: teamA.team_name,
      teamBName: teamB.team_name,
      actualScoreA,
      actualScoreB,
      actualMargin,
      actualWinner,
      predictedMargin: predEnhanced.predictedMargin,
      winProbA: predEnhanced.winProbA,
      predictedWinner: predictedWinnerEnhanced,
      correct: predictedWinnerEnhanced === actualWinner,
      compositeDiff: predEnhanced.compositeDiff,
      components: predEnhanced.components,
    });
  }

  console.log(`✅ Validated ${predictionsEnhanced.length} games (skipped ${skipped})`);

  if (predictionsEnhanced.length === 0) {
    console.log('\n❌ No predictions to validate!');
    process.exit(1);
  }

  // Calculate metrics for both models
  const metricsSimple = calculateMetrics(predictionsSimple, 'Simple Model');
  const metricsEnhanced = calculateMetrics(predictionsEnhanced, 'Enhanced Model');

  // Print comparison report
  printComparisonReport(metricsSimple, metricsEnhanced, predictionsSimple, predictionsEnhanced);
}

/**
 * Calculate accuracy metrics
 */
function calculateMetrics(predictions, modelName) {
  const correct = predictions.filter(p => p.correct).length;
  const directionAccuracy = correct / predictions.length;

  const marginErrors = predictions.map(p => Math.abs(p.predictedMargin - p.actualMargin));
  const mae = marginErrors.reduce((a, b) => a + b, 0) / marginErrors.length;
  const rmse = Math.sqrt(marginErrors.reduce((a, b) => a + b * b, 0) / marginErrors.length);

  const brierScores = predictions.map(p => {
    const actualOutcome = p.actualWinner === 'a' ? 1.0 : 0.0;
    return Math.pow(p.winProbA - actualOutcome, 2);
  });
  const brierScore = brierScores.reduce((a, b) => a + b, 0) / brierScores.length;

  const highConf = predictions.filter(p => Math.abs(p.winProbA - 0.5) > 0.2);
  const lowConf = predictions.filter(p => Math.abs(p.winProbA - 0.5) <= 0.2);

  const highConfAccuracy = highConf.length > 0
    ? highConf.filter(p => p.correct).length / highConf.length
    : 0;
  const lowConfAccuracy = lowConf.length > 0
    ? lowConf.filter(p => p.correct).length / lowConf.length
    : 0;

  return {
    modelName,
    total: predictions.length,
    correct,
    directionAccuracy,
    mae,
    rmse,
    brierScore,
    highConf: highConf.length,
    highConfAccuracy,
    lowConf: lowConf.length,
    lowConfAccuracy,
  };
}

/**
 * Print comparison report
 */
function printComparisonReport(metricsSimple, metricsEnhanced, predsSimple, predsEnhanced) {
  console.log('\n' + '='.repeat(70));
  console.log('VALIDATION RESULTS - MODEL COMPARISON');
  console.log('='.repeat(70));

  console.log(`\n📊 OVERALL METRICS (n=${metricsEnhanced.total} games)`);
  console.log('-'.repeat(70));
  console.log('Metric'.padEnd(25) + 'Simple Model'.padEnd(20) + 'Enhanced Model'.padEnd(20) + 'Change');
  console.log('-'.repeat(70));

  const dirAccDiff = metricsEnhanced.directionAccuracy - metricsSimple.directionAccuracy;
  const maeDiff = metricsEnhanced.mae - metricsSimple.mae;
  const brierDiff = metricsEnhanced.brierScore - metricsSimple.brierScore;

  console.log(
    'Direction Accuracy'.padEnd(25) +
    `${(metricsSimple.directionAccuracy * 100).toFixed(1)}%`.padEnd(20) +
    `${(metricsEnhanced.directionAccuracy * 100).toFixed(1)}%`.padEnd(20) +
    `${dirAccDiff >= 0 ? '+' : ''}${(dirAccDiff * 100).toFixed(1)}%`
  );

  console.log(
    'MAE (Goal Margin)'.padEnd(25) +
    `${metricsSimple.mae.toFixed(2)}`.padEnd(20) +
    `${metricsEnhanced.mae.toFixed(2)}`.padEnd(20) +
    `${maeDiff >= 0 ? '+' : ''}${maeDiff.toFixed(2)}`
  );

  console.log(
    'Brier Score'.padEnd(25) +
    `${metricsSimple.brierScore.toFixed(3)}`.padEnd(20) +
    `${metricsEnhanced.brierScore.toFixed(3)}`.padEnd(20) +
    `${brierDiff >= 0 ? '+' : ''}${brierDiff.toFixed(3)}`
  );

  console.log(`\n🎯 BY CONFIDENCE LEVEL`);
  console.log('-'.repeat(70));

  const highConfDiff = metricsEnhanced.highConfAccuracy - metricsSimple.highConfAccuracy;
  const lowConfDiff = metricsEnhanced.lowConfAccuracy - metricsSimple.lowConfAccuracy;

  console.log('Confidence Level'.padEnd(25) + 'Simple Model'.padEnd(20) + 'Enhanced Model'.padEnd(20) + 'Change');
  console.log('-'.repeat(70));

  console.log(
    'High (>70%)'.padEnd(25) +
    `${(metricsSimple.highConfAccuracy * 100).toFixed(1)}% (n=${metricsSimple.highConf})`.padEnd(20) +
    `${(metricsEnhanced.highConfAccuracy * 100).toFixed(1)}% (n=${metricsEnhanced.highConf})`.padEnd(20) +
    `${highConfDiff >= 0 ? '+' : ''}${(highConfDiff * 100).toFixed(1)}%`
  );

  console.log(
    'Low (50-70%)'.padEnd(25) +
    `${(metricsSimple.lowConfAccuracy * 100).toFixed(1)}% (n=${metricsSimple.lowConf})`.padEnd(20) +
    `${(metricsEnhanced.lowConfAccuracy * 100).toFixed(1)}% (n=${metricsEnhanced.lowConf})`.padEnd(20) +
    `${lowConfDiff >= 0 ? '+' : ''}${(lowConfDiff * 100).toFixed(1)}%`
  );

  // Sample improved predictions
  console.log(`\n📋 SAMPLE ENHANCED PREDICTIONS`);
  console.log('-'.repeat(70));

  // Find games where enhanced model was correct but simple was wrong
  const improvements = [];
  for (let i = 0; i < predsEnhanced.length; i++) {
    if (predsEnhanced[i].correct && !predsSimple[i].correct) {
      improvements.push({
        ...predsEnhanced[i],
        simpleProb: predsSimple[i].winProbA,
      });
    }
  }

  if (improvements.length > 0) {
    console.log(`\n✅ GAMES WHERE ENHANCED MODEL FIXED ERRORS (showing 5 of ${improvements.length}):`);
    for (const p of improvements.slice(0, 5)) {
      console.log(`\n  ${p.teamAName} vs ${p.teamBName}`);
      console.log(`    Actual: ${p.actualScoreA}-${p.actualScoreB}`);
      console.log(`    Simple:   ${(p.simpleProb * 100).toFixed(0)}% for ${p.teamAName} ❌`);
      console.log(`    Enhanced: ${(p.winProbA * 100).toFixed(0)}% for ${p.teamAName} ✅`);
      console.log(`    Components: Power=${p.components.powerDiff.toFixed(3)}, SOS=${p.components.sosDiff.toFixed(3)}, Form=${p.components.formDiffRaw.toFixed(2)}`);
    }
  } else {
    console.log('\n⚠️  Enhanced model did not fix any errors from simple model');
  }

  // Interpretation
  console.log('\n' + '='.repeat(70));
  console.log('INTERPRETATION');
  console.log('='.repeat(70));

  if (dirAccDiff > 0.05) {
    console.log(`✅ SIGNIFICANT IMPROVEMENT: +${(dirAccDiff * 100).toFixed(1)}% direction accuracy`);
    console.log('   Enhanced features are helping with close matchups!');
  } else if (dirAccDiff > 0.02) {
    console.log(`✅ MODERATE IMPROVEMENT: +${(dirAccDiff * 100).toFixed(1)}% direction accuracy`);
    console.log('   Enhanced features provide some value');
  } else if (dirAccDiff > -0.02) {
    console.log(`⚠️  MARGINAL CHANGE: ${dirAccDiff >= 0 ? '+' : ''}${(dirAccDiff * 100).toFixed(1)}% direction accuracy`);
    console.log('   Enhanced features not adding much value - may need different features');
  } else {
    console.log(`❌ REGRESSION: ${(dirAccDiff * 100).toFixed(1)}% direction accuracy (worse)`);
    console.log('   Enhanced model is overfitting or using wrong features');
  }

  if (metricsEnhanced.directionAccuracy >= 0.60) {
    console.log('\n✅ ACCURACY IS GOOD (>60%): Ready to build explanation engine!');
  } else if (metricsEnhanced.directionAccuracy >= 0.55) {
    console.log('\n⚠️  ACCURACY IS FAIR (55-60%): May want to tune further or accept limitations');
  } else {
    console.log('\n❌ ACCURACY STILL LOW (<55%): Consider alternative approaches');
  }

  console.log('\n' + '='.repeat(70));
  console.log('\nCONFIGURATION USED:');
  console.log(`  Weights: Power=${WEIGHTS.POWER_SCORE}, SOS=${WEIGHTS.SOS}, Form=${WEIGHTS.RECENT_FORM}, Matchup=${WEIGHTS.MATCHUP}`);
  console.log(`  Sensitivity: ${SENSITIVITY}`);
  console.log(`  Recent games for form: ${RECENT_GAMES_COUNT}`);
  console.log('='.repeat(70) + '\n');
}

// Run validation
validate().catch(error => {
  console.error('\n❌ Error:', error.message);
  console.error(error.stack);
  process.exit(1);
});
