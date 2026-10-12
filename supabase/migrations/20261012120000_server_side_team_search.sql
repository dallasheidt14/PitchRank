-- Server-side team search for /api/teams/search. The route parses the typed query into
-- TEXT terms, an age set and a gender; search_teams() only filters, ranks and limits.

-- Normalises the stored team text the way frontend/lib/teamSearchQuery.ts normalises the
-- typed words (search_teams uses its terms as received): lowercase, typographic apostrophes
-- become ', separators (- _ / | and the en and em dash) become spaces, whitespace collapses.
-- The parser also splits typed words on other ASCII punctuation, which only ever shortens a
-- term.
--
-- IMMUTABLE so it can back an index, and deliberately without a SET clause: a SET
-- clause stops the planner inlining the body and adds a GUC save/restore to every
-- index recheck. Every operator and function it uses lives in pg_catalog, which is
-- always searched.
CREATE OR REPLACE FUNCTION public.team_search_text(
  p_team_name text,
  p_club_name text,
  p_league text,
  p_distinction text
)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT pg_catalog.btrim(
    pg_catalog.regexp_replace(
      pg_catalog.regexp_replace(
        pg_catalog.regexp_replace(
          pg_catalog.lower(
            coalesce(p_team_name, '') || ' ' || coalesce(p_club_name, '') || ' '
              || coalesce(p_league, '') || ' ' || coalesce(p_distinction, '')
          ),
          '[\u2018\u2019]', '''', 'g'
        ),
        '[-_/|\u2013\u2014]', ' ', 'g'
      ),
      '\s+', ' ', 'g'
    )
  )
$$;

CREATE INDEX IF NOT EXISTS idx_teams_search_text_trgm
  ON public.teams
  USING gin (public.team_search_text(team_name, club_name, league, distinction) public.gin_trgm_ops)
  WHERE is_deprecated = false;

-- search_teams' SET pg_trgm.* clause needs pg_trgm's library loaded in this session: a
-- non-superuser cannot store a parameter the library has not registered yet, and on a
-- re-run the index build above is skipped. Calling any pg_trgm function loads it.
SELECT public.word_similarity('', '');

-- p_mode:
--   exact   - every term is a substring of the normalised text; age and gender apply.
--             Terms carry no LIKE wildcards: the route's parser never sends % or _.
--   similar - every term is word-similar to the text (typos); age and gender apply
--   relaxed - as similar, without the age and gender constraint
-- p_age_filter / p_gender_filter / p_state are the route's caller filters and apply in
-- every mode.
--
-- The WHERE is built dynamically so each term gets its own scalar predicate: the
-- trigram index serves `expr LIKE $1[1] AND expr LIKE $1[2]`, but not strpos(), an
-- ALL(array) comparison or an unnest() loop over the terms. Terms stay bound
-- parameters; only the array subscripts are formatted into the statement.
CREATE OR REPLACE FUNCTION public.search_teams(
  p_terms text[],
  p_age_groups text[],
  p_age_regex text,
  p_gender text,
  p_mode text,
  p_age_filter text[],
  p_gender_filter text,
  p_state text,
  p_limit integer
)
RETURNS TABLE (
  team_id_master uuid,
  team_name text,
  club_name text,
  age_group text,
  gender text,
  state_code text,
  league text,
  distinction text,
  is_ranked boolean,
  match_pos integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
SET pg_trgm.word_similarity_threshold = 0.4
AS $$
DECLARE
  v_text constant text := 'public.team_search_text(t.team_name, t.club_name, t.league, t.distinction)';
  v_term_count integer := coalesce(pg_catalog.cardinality(p_terms), 0);
  v_patterns text[] := '{}';
  v_where text := 't.is_deprecated = false';
  v_positions text[] := '{}';
  v_similarities text[] := '{}';
  v_pos text := '1000000';
  v_order text;
  v_has_age boolean := coalesce(pg_catalog.cardinality(p_age_groups), 0) > 0 OR p_age_regex IS NOT NULL;
  v_has_filter boolean := coalesce(pg_catalog.cardinality(p_age_filter), 0) > 0
    OR p_gender_filter IS NOT NULL OR p_state IS NOT NULL;
  i integer;
BEGIN
  IF p_mode IS NULL OR p_mode NOT IN ('exact', 'similar', 'relaxed') THEN
    RAISE EXCEPTION 'search_teams: unknown mode %', p_mode;
  END IF;

  IF v_term_count = 0 AND NOT v_has_age AND p_gender IS NULL AND NOT v_has_filter THEN
    RETURN;
  END IF;

  FOR i IN 1..v_term_count LOOP
    v_patterns := v_patterns || ('%' || p_terms[i] || '%');
    IF p_mode = 'exact' THEN
      v_where := v_where || pg_catalog.format(' AND %s LIKE $1[%s]', v_text, i);
    ELSE
      v_where := v_where || pg_catalog.format(' AND $9[%s] OPERATOR(public.<%%) %s', i, v_text);
    END IF;
    v_positions := v_positions || pg_catalog.format('NULLIF(pg_catalog.strpos(%s, $9[%s]), 0)', v_text, i);
    v_similarities := v_similarities || pg_catalog.format('public.word_similarity($9[%s], %s)', i, v_text);
  END LOOP;

  IF p_mode <> 'relaxed' THEN
    IF v_has_age THEN
      v_where := v_where || pg_catalog.format(
        ' AND (t.age_group = ANY($2) OR ($3 IS NOT NULL AND %s ~ $3))', v_text
      );
    END IF;
    IF p_gender IS NOT NULL THEN
      v_where := v_where || ' AND t.gender = $4';
    END IF;
  END IF;

  IF coalesce(pg_catalog.cardinality(p_age_filter), 0) > 0 THEN
    v_where := v_where || ' AND t.age_group = ANY($5)';
  END IF;
  IF p_gender_filter IS NOT NULL THEN
    v_where := v_where || ' AND t.gender = $6';
  END IF;
  IF p_state IS NOT NULL THEN
    v_where := v_where || ' AND t.state_code = $7';
  END IF;

  IF v_term_count > 0 THEN
    v_pos := 'coalesce(LEAST(' || pg_catalog.array_to_string(v_positions, ', ') || '), 1000000)';
  END IF;

  IF p_mode = 'exact' OR v_term_count = 0 THEN
    v_order := 'match_pos ASC, is_ranked DESC, t.team_name ASC, t.team_id_master ASC';
  ELSE
    v_order := 'GREATEST(' || pg_catalog.array_to_string(v_similarities, ', ')
      || ') DESC, is_ranked DESC, t.team_name ASC, t.team_id_master ASC';
  END IF;

  RETURN QUERY EXECUTE pg_catalog.format(
    'SELECT t.team_id_master, t.team_name, t.club_name, t.age_group, t.gender, t.state_code::text, '
    || 't.league, t.distinction, '
    || 'EXISTS (SELECT 1 FROM public.rankings_full r '
    || 'WHERE r.team_id = t.team_id_master AND r.rank_in_cohort_final IS NOT NULL) AS is_ranked, '
    || '(%s)::integer AS match_pos '
    || 'FROM public.teams t WHERE %s ORDER BY %s LIMIT $8',
    v_pos, v_where, v_order
  )
  USING v_patterns, p_age_groups, p_age_regex, p_gender, p_age_filter, p_gender_filter, p_state,
    LEAST(GREATEST(coalesce(p_limit, 20), 1), 100), p_terms;
END;
$$;

-- Server-only: /api/teams/search is the rate-limited door. A browser-role grant would
-- let anyone holding the anon key call this through PostgREST and skip the route.
REVOKE EXECUTE ON FUNCTION public.search_teams(text[], text[], text, text, text, text[], text, text, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.search_teams(text[], text[], text, text, text, text[], text, text, integer)
  TO service_role;

COMMENT ON FUNCTION public.search_teams(text[], text[], text, text, text, text[], text, text, integer) IS
  'Lenient team search for /api/teams/search: per-term trigram predicates, age/gender constraints, ranked teams first.';
