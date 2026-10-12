"""Pin the parts of the server-side team search migration that fail silently.

ci.yml applies no migrations, so these text assertions stand in for execution:

  - search_teams granted to a browser role. /api/teams/search rate-limits and
    validates; a grant to anon or authenticated lets anyone holding the public key
    call the RPC through PostgREST and skip both.
  - an unqualified `<%`, `word_similarity(` or `team_search_text(`. pg_trgm and the
    normaliser live in schema public, and under `SET search_path = ''` a bare name does
    not resolve, so every search (or every similar and relaxed one) would fail at runtime.
  - the similarity threshold moving off 0.4: at pg_trgm's default 0.6 an
    ordinary typo ("rebles" for "rebels") matches nothing, and much lower lets unrelated
    names through.
  - the file setting pg_trgm.word_similarity_threshold before anything loads pg_trgm. A
    non-superuser cannot store a parameter the library has not registered, so a re-run,
    where the index build is skipped, fails.
  - a SET clause on team_search_text, which blocks inlining and adds a GUC
    save/restore to every index recheck.
  - team_search_text not folding typographic apostrophes and dashes the way the route's
    parser folds the typed words: an iPhone's curly apostrophe then never matches exactly.
  - a caller filter (age, gender, state) moving inside the block the relaxed pass skips,
    so a caller's relaxed results escape the cohort it asked for.
  - the result order drifting from earliest-match-first, ranked-teams-next
    (exact) and most-similar-first, ranked-teams-next (similar and relaxed).

Functions resolve by name across every migration, newest definition wins, so a later
file that redefines either one is what these tests read.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

BROWSER_ROLES = ("public", "anon", "authenticated")


def _executable(text: str) -> str:
    """`text` with -- line and /* */ block comments removed."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def _migrations() -> list[Path]:
    """Every migration, oldest first: filenames are timestamp-prefixed."""
    return sorted(MIGRATIONS.glob("*.sql"))


def _newest_function(name: str) -> tuple[Path, str]:
    """The newest CREATE FUNCTION for `name`, through the end of its $$ body."""
    pattern = re.compile(rf"(?is)create\s+(?:or\s+replace\s+)?function\s+(?:public\.)?{name}\s*\(")
    found = None
    for path in _migrations():
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in pattern.finditer(sql):
            body_start = sql.index("$$", match.end())
            body_end = sql.index("$$", body_start + 2)
            found = (path, sql[match.start() : body_end + 2])
    assert found is not None, f"no migration defines {name}"
    return found


def _header(definition: str) -> str:
    """Everything before the function body: arguments, return type and attributes."""
    return definition[: definition.index("$$")]


def _normalized_header(definition: str) -> str:
    return re.sub(r"\s+", " ", _header(definition)).lower()


def _body(definition: str) -> str:
    return definition[definition.index("$$") + 2 : definition.rindex("$$")]


def _if_block(body: str, opening: str) -> str:
    """The IF ... END IF; block that starts at `opening`, nested blocks included."""
    start = body.index(opening)
    depth = 0
    for match in re.finditer(r"\bEND IF\b|\bIF\b", body[start:]):
        depth += -1 if match.group(0) == "END IF" else 1
        if depth == 0:
            return body[start : start + match.end()]
    raise AssertionError(f"unterminated {opening}")


def _grant_statements(name: str, paths: list[Path]) -> list[str]:
    statements = []
    for path in paths:
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in re.finditer(rf"(?is)\b(grant|revoke)\b[^;]*?\b{name}\b[^;]*;", sql):
            statements.append(re.sub(r"\s+", " ", match.group(0)).strip().lower())
    return statements


def test_search_teams_runs_as_definer_with_an_empty_search_path():
    _, definition = _newest_function("search_teams")
    header = _normalized_header(definition)

    assert "security definer" in header
    assert "set search_path = ''" in header


def test_search_teams_pins_a_similarity_threshold_that_accepts_typos():
    _, definition = _newest_function("search_teams")
    header = _normalized_header(definition)

    match = re.search(r"set pg_trgm\.word_similarity_threshold = ([0-9.]+)", header)
    assert match is not None, "search_teams must pin pg_trgm.word_similarity_threshold"
    # word_similarity('rebles', 'las vegas rebels 2014 girls') is 0.43.
    assert match.group(1) == "0.4"


def test_search_teams_migration_loads_pg_trgm_before_setting_its_threshold():
    defining_file, definition = _newest_function("search_teams")
    sql = _executable(defining_file.read_text(encoding="utf-8"))

    assert re.search(r"(?is)\bselect\s+public\.word_similarity\s*\(", sql[: sql.index(definition)]), (
        "call a pg_trgm function before CREATE FUNCTION search_teams so its SET clause can register"
    )


def test_search_teams_qualifies_every_trigram_operator():
    _, definition = _newest_function("search_teams")
    body = _body(definition)

    # The body builds its WHERE with format(), where % is written %%.
    assert "OPERATOR(public.<%%)" in body
    assert re.search(r"(?<!public\.)<%", body) is None, "a bare <% does not resolve under search_path = ''"
    for name in ("word_similarity", "team_search_text"):
        assert f"public.{name}(" in body
        assert re.search(rf"(?<!public\.)\b{name}\(", body) is None, (
            f"a bare {name}( does not resolve under search_path = ''"
        )


def test_search_teams_orders_earliest_match_then_ranked_teams_first():
    _, definition = _newest_function("search_teams")
    body = re.sub(r"\s+", " ", _body(definition))
    ties = "is_ranked DESC, t.team_name ASC, t.team_id_master ASC"

    assert (
        "IF p_mode = 'exact' OR v_term_count = 0 THEN "
        f"v_order := 'match_pos ASC, {ties}'; "
        "ELSE "
        f"v_order := 'GREATEST(' || pg_catalog.array_to_string(v_similarities, ', ') || ') DESC, {ties}'; "
        "END IF;"
    ) in body


def test_search_teams_applies_caller_filters_in_every_mode():
    _, definition = _newest_function("search_teams")
    body = re.sub(r"\s+", " ", _body(definition))
    caller_filters = (
        "IF coalesce(pg_catalog.cardinality(p_age_filter), 0) > 0 THEN "
        "v_where := v_where || ' AND t.age_group = ANY($5)'; END IF; "
        "IF p_gender_filter IS NOT NULL THEN v_where := v_where || ' AND t.gender = $6'; END IF; "
        "IF p_state IS NOT NULL THEN v_where := v_where || ' AND t.state_code = $7'; END IF;"
    )

    assert caller_filters in body
    assert caller_filters not in _if_block(body, "IF p_mode <> 'relaxed' THEN")
    assert "USING v_patterns, p_age_groups, p_age_regex, p_gender, p_age_filter, p_gender_filter, p_state," in body


def test_team_search_text_is_immutable_and_inlinable():
    _, definition = _newest_function("team_search_text")
    header = _normalized_header(definition)

    assert " immutable" in header
    assert re.search(r"\bset\s+\w", header) is None, "a SET clause blocks inlining"


def test_team_search_text_folds_typographic_punctuation_like_the_parser():
    _, definition = _newest_function("team_search_text")
    body = _body(definition)

    # frontend/lib/teamSearchQuery.ts folds the same four characters in the typed words.
    assert r"'[\u2018\u2019]', '''', 'g'" in body
    assert r"'[-_/|\u2013\u2014]', ' ', 'g'" in body


def test_search_teams_is_server_only():
    defining_file, _ = _newest_function("search_teams")
    statements = _grant_statements("search_teams", [p for p in _migrations() if p >= defining_file])

    revoked_from = [s.rsplit(" from ", 1)[1] for s in statements if s.startswith("revoke")]
    assert any(all(re.search(rf"\b{role}\b", roles) for role in BROWSER_ROLES) for roles in revoked_from), statements
    assert any(s.startswith("grant") and s.endswith("to service_role;") for s in statements), statements

    for statement in statements:
        if statement.startswith("grant"):
            grantees = statement.rsplit(" to ", 1)[1]
            assert not any(re.search(rf"\b{role}\b", grantees) for role in BROWSER_ROLES), statement


def test_search_index_is_partial_on_live_teams():
    statement = None
    for path in _migrations():
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"(?is)create\s+index[^;]*idx_teams_search_text_trgm[^;]*;", sql):
            statement = re.sub(r"\s+", " ", match.group(0)).lower()
    assert statement is not None, "no migration creates idx_teams_search_text_trgm"

    expression = "public.team_search_text(team_name, club_name, league, distinction) public.gin_trgm_ops"
    assert f"using gin ({expression})" in statement
    assert statement.endswith("where is_deprecated = false;")
