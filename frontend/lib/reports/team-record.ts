type TeamRecordFields = {
  wins?: number | null;
  losses?: number | null;
  draws?: number | null;
  total_wins?: number | null;
  total_losses?: number | null;
  total_draws?: number | null;
};

/**
 * Format a "W-L-D" record string, choosing the lifetime (`total_*`) or season
 * record as a single group. Mixing the two — e.g. lifetime wins with season
 * losses when one `total_*` field is null — would misstate the record (C32).
 */
export function formatTeamRecord(ranking: TeamRecordFields): string {
  const hasTotalRecord = ranking.total_wins != null || ranking.total_losses != null || ranking.total_draws != null;
  const [wins, losses, draws] = hasTotalRecord
    ? [ranking.total_wins, ranking.total_losses, ranking.total_draws]
    : [ranking.wins, ranking.losses, ranking.draws];
  return `${wins ?? 0}-${losses ?? 0}-${draws ?? 0}`;
}
