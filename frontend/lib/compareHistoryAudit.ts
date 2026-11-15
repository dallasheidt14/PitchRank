/** Observe the saved history without changing selection, exclusions, or duplicate policy. */
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';
import pin from './compareFormulaPin.json';
import type { MatchPredictionShadowContext } from './matchPredictionService';
import type { Game } from './types';

export function createHistoryAuditor(frontendRoot: string) {
  const source = readFileSync(path.join(frontendRoot, 'lib/matchPredictionService.ts'), 'utf8').replace(/\r\n/g, '\n');
  if (createHash('sha256').update(source).digest('hex') !== pin.source_hashes['matchPredictionService.ts'])
    throw new Error('History audit requires the pinned input service');
  // Reuse the service's actual source-key parser and ordering; no second duplicate policy.
  const ast = ts.createSourceFile('service.ts', source, ts.ScriptTarget.Latest, true);
  const functions = ['sourceFixtureIdentity', 'comparePredictionGames']
    .map((name) => {
      const nodes = ast.statements.filter((node) => ts.isFunctionDeclaration(node) && node.name?.text === name);
      if (nodes.length !== 1) throw new Error('Pinned history helper changed');
      return nodes[0].getText(ast).replace(/^export /, '');
    })
    .join('\n');
  const compiled = ts.transpileModule(functions, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const helpers = vm.runInNewContext(compiled + '\n({sourceFixtureIdentity, comparePredictionGames})', { URL }) as {
    sourceFixtureIdentity: (game: Game) => { namespace: string; id: string } | null;
    comparePredictionGames: (a: Game, b: Game) => number;
  };
  return (context: MatchPredictionShadowContext, referenceTime: string) => {
    const evidence = context.frozenEvidence;
    if (!evidence) throw new Error('Missing frozen history');
    const asOf = referenceTime.slice(0, 10);
    if (!Number.isFinite(Date.parse(referenceTime))) throw new Error('Missing history clock');
    const games = evidence.games;
    const sourceGroups = new Map<string, Set<string>>();
    let unknownSource = 0;
    for (const game of games) {
      const identity = helpers.sourceFixtureIdentity(game);
      if (!identity) {
        unknownSource++;
        continue;
      }
      const key = JSON.stringify(identity);
      if (!sourceGroups.has(key)) sourceGroups.set(key, new Set());
      sourceGroups.get(key)!.add(game.id);
    }
    const sourceCopies = [...sourceGroups.values()].filter((ids) => ids.size > 1).map((ids) => [...ids].sort());
    const duplicateIds = games.length - new Set(games.map((g) => g.id)).size;
    const invalidScores = games
      .filter((g) => [g.home_score, g.away_score].some((v) => typeof v !== 'number' || !Number.isInteger(v) || v < 0))
      .map((g) => g.id);
    const future = games.filter((g) => g.game_date > asOf).map((g) => g.id);
    const excluded = games
      .filter(
        (g) =>
          g.is_excluded ||
          evidence.excluded_team_ids?.some((id) => id === g.home_team_master_id || id === g.away_team_master_id)
      )
      .map((g) => g.id);
    const orderingErrors = games
      .filter((g, i) => i > 0 && helpers.comparePredictionGames(games[i - 1], g) > 0)
      .map((g) => g.id);
    const teams = [context.teamAInput, context.teamBInput].map((team) => {
      // Exactly the predictor's date-only stable sort: report suspect order rather than silently correcting it.
      const history = games
        .filter((g) => g.home_team_master_id === team.team_id_master || g.away_team_master_id === team.team_id_master)
        .sort((a, b) => Date.parse(b.game_date) - Date.parse(a.game_date));
      const recent = history.slice(0, 8);
      const opponents = new Set(
        recent.map((g) =>
          g.home_team_master_id === team.team_id_master ? g.away_team_master_id : g.home_team_master_id
        )
      );
      const ages = recent.map((g) => (Date.parse(asOf) - Date.parse(g.game_date)) / 86400000);
      return {
        team_id: team.team_id_master,
        age: team.age ?? null,
        available_games: history.length,
        recent_ids: recent.map((g) => g.id),
        recent_count: recent.length,
        unique_recent_opponents: opponents.size,
        repeated_opponent_results: recent.length - opponents.size,
        latest_result_age_days: ages.length ? Math.min(...ages) : null,
        oldest_recent_age_days: ages.length ? Math.max(...ages) : null,
        missing_ml_recent: recent.filter((g) => g.ml_overperformance == null).length,
        missing_history: history.length === 0,
        short_history: recent.length < 8,
      };
    });
    return {
      teams,
      duplicate_ids: duplicateIds,
      same_source_fixture_copies: sourceCopies,
      unknown_source_identity: unknownSource,
      invalid_scores: invalidScores,
      future_games: future,
      excluded_games: excluded,
      ordering_errors: orderingErrors,
      omissions: (evidence.omitted ?? []).reduce<Record<string, number>>((counts, item) => {
        counts[item.reason] = (counts[item.reason] ?? 0) + 1;
        return counts;
      }, {}),
      limitations: [
        'Same-day team/score matches are not proof of duplicates.',
        'Saved history cannot establish completeness or historical availability of rows absent from the archive.',
        'Missing ML values retain the live zero fallback; no training provenance is inferred.',
      ],
    };
  };
}
