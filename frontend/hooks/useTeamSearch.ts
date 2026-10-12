import { useEffect, useState, useCallback } from 'react';
import { normalizeAgeGroup } from '@/lib/utils';
import type { TeamSearchMatch, TeamSearchResult } from '@/lib/teamSearchQuery';
import type { RankingRow } from '@/types/RankingRow';

interface SearchResponse {
  teams: RankingRow[];
  match: TeamSearchMatch;
}

const DEBOUNCE_MS = 200;
const MIN_QUERY_LENGTH = 2;

const cache = new Map<string, SearchResponse>();

function toRankingRow(team: TeamSearchResult): RankingRow {
  return {
    team_id_master: team.team_id_master,
    team_name: team.team_name,
    club_name: team.club_name,
    league: team.league,
    distinction: team.distinction,
    state: team.state_code,
    age: normalizeAgeGroup(team.age_group) ?? 0,
    // Database 'Male'|'Female' to the 'M'|'F' the renderers expect
    gender: team.gender === 'Female' ? 'F' : 'M',
    power_score_final: 0,
    sos_norm: 0,
    offense_norm: null,
    defense_norm: null,
    rank_in_cohort_final: 0,
    games_played: 0,
    wins: 0,
    losses: 0,
    draws: 0,
    total_games_played: 0,
    total_wins: 0,
    total_losses: 0,
    total_draws: 0,
    win_percentage: null,
  };
}

async function fetchSearch(query: string, limit: number, signal: AbortSignal): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const response = await fetch(`/api/teams/search?${params.toString()}`, { signal });
  if (!response.ok) throw new Error(`Search failed (${response.status})`);
  const body = (await response.json()) as { teams?: TeamSearchResult[]; match?: TeamSearchMatch };
  return { teams: (body.teams ?? []).map(toRankingRow), match: body.match ?? 'exact' };
}

interface SearchState {
  query: string;
  teams: RankingRow[];
  match: TeamSearchMatch;
  error: Error | null;
}

interface UseTeamSearchOptions {
  limit: number;
  excludeId?: string | null;
}

interface UseTeamSearchReturn {
  /** Rows for the query currently typed; empty until its response arrives. */
  results: RankingRow[];
  match: TeamSearchMatch;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

/**
 * Search teams as the user types, through /api/teams/search.
 *
 * No React Query: the sitewide nav search renders outside DataProviders and should not pull
 * it into the anon bundle. Responses are cached for the page lifetime so back-spacing over a
 * query does not refetch it.
 */
export function useTeamSearch(query: string, { limit, excludeId }: UseTeamSearchOptions): UseTeamSearchReturn {
  const trimmed = query.trim();
  const active = trimmed.length >= MIN_QUERY_LENGTH;
  // One extra row so excluding a team still leaves `limit` to show.
  const requestLimit = limit + 1;

  const [debounced, setDebounced] = useState('');
  const [state, setState] = useState<SearchState>({ query: '', teams: [], match: 'exact', error: null });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(trimmed), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [trimmed]);

  useEffect(() => {
    if (debounced.length < MIN_QUERY_LENGTH) return;

    const key = `${debounced}|${requestLimit}`;
    const cached = cache.get(key);
    const controller = new AbortController();
    // A superseded request can still resolve before its abort lands; cleanup marks it stale.
    let stale = false;

    (cached ? Promise.resolve(cached) : fetchSearch(debounced, requestLimit, controller.signal))
      .then((response) => {
        if (!cached) cache.set(key, response);
        if (stale) return;
        setState({ query: debounced, teams: response.teams, match: response.match, error: null });
      })
      .catch((e) => {
        if (stale) return;
        setState({
          query: debounced,
          teams: [],
          match: 'exact',
          error: e instanceof Error ? e : new Error(String(e)),
        });
      });

    return () => {
      stale = true;
      controller.abort();
    };
  }, [debounced, requestLimit, nonce]);

  // Failed searches are never cached, so a retry only has to run the effect again.
  const refetch = useCallback(() => {
    setState((s) => ({ ...s, query: '', error: null }));
    setNonce((n) => n + 1);
  }, []);

  const settled = active && state.query === trimmed;
  const results = settled ? state.teams.filter((team) => team.team_id_master !== excludeId).slice(0, limit) : [];

  return {
    results,
    match: settled ? state.match : 'exact',
    isLoading: active && !settled,
    isError: settled && state.error !== null,
    error: settled ? state.error : null,
    refetch,
  };
}
