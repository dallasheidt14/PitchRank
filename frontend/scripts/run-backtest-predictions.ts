import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

import type { Game, TeamWithRanking } from '../lib/types';
import { predictMatch, warmMatchPredictorCalibration } from '../lib/matchPredictor.ts';

interface BatchTeam {
  entrant_id: string;
  team: TeamWithRanking;
}

interface BatchInput {
  schema_version: number;
  teams: BatchTeam[];
  games: Game[];
}

async function main() {
  const inputPath = process.argv[2];
  const outputPath = process.argv[3];
  if (!inputPath || !outputPath) {
    throw new Error('Usage: run-backtest-predictions.ts <input.json> <output.json>');
  }

  const payload = JSON.parse(await readFile(resolve(inputPath), 'utf8')) as BatchInput;
  if (payload.schema_version !== 1 || !Array.isArray(payload.teams) || !Array.isArray(payload.games)) {
    throw new Error('Invalid MatchBalance Compare predictor batch');
  }
  const entrantIds = payload.teams.map((item) => item.entrant_id);
  if (new Set(entrantIds).size !== entrantIds.length) {
    throw new Error('MatchBalance Compare predictor entrants must be unique');
  }

  await warmMatchPredictorCalibration();
  const teams = [...payload.teams].sort((left, right) => left.entrant_id.localeCompare(right.entrant_id));
  const predictions = [];
  for (let leftIndex = 0; leftIndex < teams.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < teams.length; rightIndex += 1) {
      const left = teams[leftIndex];
      const right = teams[rightIndex];
      const prediction = predictMatch(left.team, right.team, payload.games);
      predictions.push({
        entrant_a: left.entrant_id,
        entrant_b: right.entrant_id,
        predicted_winner: prediction.predictedWinner,
        win_probability_a: prediction.winProbabilityA,
        win_probability_b: prediction.winProbabilityB,
        draw_probability: prediction.drawProbability ?? 0,
        expected_score: prediction.expectedScore,
        expected_margin: prediction.expectedMargin,
        expected_absolute_goal_difference: prediction.expectedAbsoluteGoalDifference,
        blowout_4plus_probability: prediction.blowout4PlusProbability,
      });
      predictions.push({
        entrant_a: right.entrant_id,
        entrant_b: left.entrant_id,
        predicted_winner:
          prediction.predictedWinner === 'team_a'
            ? 'team_b'
            : prediction.predictedWinner === 'team_b'
              ? 'team_a'
              : 'draw',
        win_probability_a: prediction.winProbabilityB,
        win_probability_b: prediction.winProbabilityA,
        draw_probability: prediction.drawProbability ?? 0,
        expected_score: {
          teamA: prediction.expectedScore.teamB,
          teamB: prediction.expectedScore.teamA,
        },
        expected_margin: -prediction.expectedMargin,
        expected_absolute_goal_difference: prediction.expectedAbsoluteGoalDifference,
        blowout_4plus_probability: prediction.blowout4PlusProbability,
      });
    }
  }

  await writeFile(resolve(outputPath), JSON.stringify({ schema_version: 1, predictions }), 'utf8');
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? (error.stack ?? error.message) : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
});
