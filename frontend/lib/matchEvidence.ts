import type { Game, TeamWithRanking } from './types';

export const MATCH_FORM_SAMPLE_SIZE = 8;
export interface TeamMatchEvidence {
  usableResults: number;
  formSampleSize: number;
  latestResultDate: string | null;
  ratingSnapshotDate: string | null;
  uniqueOpponents: number;
}
export interface CommonOpponentEvidence {
  opponent_id: string;
  opponent_name: string | null;
  team1_result: 'W' | 'L' | 'D';
  team2_result: 'W' | 'L' | 'D';
  team1_score: number;
  team2_score: number;
  opponent_score_team1: number;
  opponent_score_team2: number;
  team1_date: string;
  team2_date: string;
}
export interface MatchEvidenceSummary {
  asOf: string;
  windowStart: string;
  formSampleLimit: number;
  teamA: TeamMatchEvidence;
  teamB: TeamMatchEvidence;
  headToHeadMeetings: number;
  sharedOpponents: number;
  commonOpponents: CommonOpponentEvidence[];
}
type EvidenceTeam = TeamWithRanking & { ratings_as_of?: string | null };
export function summarizeMatchEvidence(
  evidence: { as_of: string; window_start: string; games: Game[] },
  teamA: EvidenceTeam,
  teamB: EvidenceTeam
): MatchEvidenceSummary {
  // The caller supplies the predictor's already canonicalized, scored, cleaned window.
  const games = evidence.games;
  function forTeam(team: EvidenceTeam) {
    const own = games.filter(
      (game) => game.home_team_master_id === team.team_id_master || game.away_team_master_id === team.team_id_master
    );
    const opponents = new Map<string, Game>();
    for (const game of own) {
      const opponent =
        game.home_team_master_id === team.team_id_master ? game.away_team_master_id : game.home_team_master_id;
      if (!opponent) continue;
      const prior = opponents.get(opponent);
      if (!prior || game.game_date > prior.game_date || (game.game_date === prior.game_date && game.id < prior.id))
        opponents.set(opponent, game);
    }
    return {
      opponents,
      summary: {
        usableResults: own.length,
        formSampleSize: Math.min(own.length, MATCH_FORM_SAMPLE_SIZE),
        latestResultDate: own.length
          ? own.reduce((latest, game) => (game.game_date > latest ? game.game_date : latest), '')
          : null,
        ratingSnapshotDate: team.ratings_as_of ?? null,
        uniqueOpponents: opponents.size,
      },
    };
  }
  const a = forTeam(teamA),
    b = forTeam(teamB);
  function result(game: Game, teamId: string) {
    const home = game.home_team_master_id === teamId;
    const scored = (home ? game.home_score : game.away_score)!;
    const conceded = (home ? game.away_score : game.home_score)!;
    return { scored, conceded, outcome: (scored > conceded ? 'W' : scored < conceded ? 'L' : 'D') as 'W' | 'L' | 'D' };
  }
  const commonOpponents = [...a.opponents.keys()]
    .filter((id) => b.opponents.has(id))
    .sort()
    .map((id) => {
      const first = a.opponents.get(id)!,
        second = b.opponents.get(id)!;
      const one = result(first, teamA.team_id_master),
        two = result(second, teamB.team_id_master);
      return {
        opponent_id: id,
        opponent_name: null,
        team1_result: one.outcome,
        team2_result: two.outcome,
        team1_score: one.scored,
        team2_score: two.scored,
        opponent_score_team1: one.conceded,
        opponent_score_team2: two.conceded,
        team1_date: first.game_date,
        team2_date: second.game_date,
      };
    });
  return {
    asOf: evidence.as_of,
    windowStart: evidence.window_start,
    formSampleLimit: MATCH_FORM_SAMPLE_SIZE,
    teamA: a.summary,
    teamB: b.summary,
    headToHeadMeetings: games.filter(
      (game) =>
        (game.home_team_master_id === teamA.team_id_master && game.away_team_master_id === teamB.team_id_master) ||
        (game.home_team_master_id === teamB.team_id_master && game.away_team_master_id === teamA.team_id_master)
    ).length,
    sharedOpponents: commonOpponents.length,
    commonOpponents,
  };
}
