import { NextRequest, NextResponse } from 'next/server';
import type { PostgrestError, SupabaseClient } from '@supabase/supabase-js';
import { createServiceSupabase } from '@/lib/supabase/service';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { parseTeamSearchQuery, type TeamSearchMatch, type TeamSearchResult } from '@/lib/teamSearchQuery';
import { escapeRegex } from '@/lib/utils';

interface SearchRow {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  age_group: string;
  gender: string;
  state_code: string | null;
  league: string | null;
  distinction: string | null;
  is_ranked: boolean;
  match_pos: number;
}

const RATE_LIMIT_MAX = 120;
const RATE_LIMIT_WINDOW_MS = 60_000;
const MAX_QUERY_LENGTH = 100;

/**
 * Connection-level failures, which a second try can get past: no error code (the request
 * never reached Postgres), PostgREST's connection codes, or Postgres connection, shutdown
 * and too-many-connections states. A statement timeout (57014) or a missing function would
 * fail the same way again.
 */
function isTransient(error: PostgrestError): boolean {
  const code = error.code ?? '';
  return (
    code === '' || code.startsWith('08') || code.startsWith('57P') || code === '53300' || /^PGRST00[0-3]$/.test(code)
  );
}

/** Call search_teams for one mode, retrying once on a transient error. */
async function searchMode(
  supabase: SupabaseClient,
  args: Record<string, unknown>,
  query: string
): Promise<{ rows: SearchRow[] } | { error: PostgrestError }> {
  for (let attempt = 1; ; attempt++) {
    const { data, error } = await supabase.rpc('search_teams', args);
    if (!error) return { rows: (data as SearchRow[] | null) ?? [] };

    console.warn(`[teams/search] search_teams ${args.p_mode} attempt ${attempt} failed:`, {
      message: error.message,
      code: error.code,
      details: error.details,
      hint: error.hint,
      query,
    });
    if (attempt === 2 || !isTransient(error)) return { error };
    await new Promise((r) => setTimeout(r, 500));
  }
}

/**
 * Search teams by the words of a typed query against name, club, league and distinction, with
 * any age or gender it names as constraints. The typo-tolerant passes run only when the exact
 * one finds nothing.
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    // Cut by code point: half of an emoji's surrogate pair is a string Postgres rejects.
    const query = Array.from((searchParams.get('q') || '').trim())
      .slice(0, MAX_QUERY_LENGTH)
      .join('');
    const ageGroup = searchParams.get('ageGroup');
    const gender = searchParams.get('gender');
    const stateCode = searchParams.get('stateCode');
    const limit = Math.min(parseInt(searchParams.get('limit') || '20', 10) || 20, 100);

    if (query.length < 2) {
      return NextResponse.json({ teams: [] });
    }

    if (!checkRateLimit(`team-search:${getClientIp(request)}`, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_MS)) {
      return NextResponse.json({ error: 'Too many searches. Please slow down.' }, { status: 429 });
    }

    const parsed = parseTeamSearchQuery(query);
    const hasConstraint = parsed.ageGroups.length > 0 || parsed.gender !== null;
    if (parsed.terms.length === 0 && !hasConstraint) {
      return NextResponse.json({ teams: [] });
    }

    const ageFilter = ageGroup
      ? ageGroup
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
      : [];

    const baseArgs = {
      p_terms: parsed.terms,
      p_age_groups: parsed.ageGroups,
      // The name-side age spellings only alongside a term the index can narrow on: with nothing
      // to narrow first, the regex runs against every team.
      p_age_regex:
        parsed.fuzzyTerms.length && parsed.ageSpellings.length
          ? `\\m(${parsed.ageSpellings.map(escapeRegex).join('|')})\\M`
          : null,
      p_gender: parsed.gender,
      p_age_filter: ageFilter,
      p_gender_filter: gender || null,
      p_state: stateCode || null,
      p_limit: limit,
    };

    const modes: TeamSearchMatch[] = ['exact'];
    // The looser passes need words to loosen, long enough for the index to narrow on.
    if (parsed.fuzzyTerms.length > 0) {
      modes.push('similar');
      // `relaxed` only differs from `similar` by dropping the age and gender read from the
      // query; caller filters still apply.
      if (hasConstraint) modes.push('relaxed');
    }

    const supabase = createServiceSupabase();
    const startTime = Date.now();

    let rows: SearchRow[] = [];
    let match: TeamSearchMatch = 'exact';
    for (const mode of modes) {
      const terms = mode === 'exact' ? parsed.terms : parsed.fuzzyTerms;
      const result = await searchMode(supabase, { ...baseArgs, p_terms: terms, p_mode: mode }, query);
      if ('error' in result) {
        console.error('[teams/search] Search failed:', { ...result.error, query, mode });
        return NextResponse.json({ error: 'Failed to search teams' }, { status: 500 });
      }
      rows = result.rows;
      match = mode;
      if (rows.length > 0) break;
    }

    const duration = Date.now() - startTime;
    if (duration > 2000) {
      console.warn('[teams/search] Slow query:', {
        query,
        duration: `${duration}ms`,
        match,
        resultCount: rows.length,
      });
    }

    const teams: TeamSearchResult[] = rows.map((row) => ({
      team_id_master: row.team_id_master,
      team_name: row.team_name,
      club_name: row.club_name,
      age_group: row.age_group,
      gender: row.gender,
      state_code: row.state_code,
      state: row.state_code,
      league: row.league,
      distinction: row.distinction,
      is_ranked: row.is_ranked,
    }));

    return NextResponse.json(
      { teams, match },
      {
        headers: {
          'Cache-Control': 'public, s-maxage=60, stale-while-revalidate=120',
        },
      }
    );
  } catch (error) {
    console.error('[teams/search] Unexpected error:', error);
    return NextResponse.json({ error: 'An unexpected error occurred' }, { status: 500 });
  }
}
