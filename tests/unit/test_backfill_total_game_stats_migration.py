"""Pin the parts of the total-game-stats backfill whose loss produces no error.

ci.yml applies no migrations, so nothing in CI executes this SQL. These text
assertions stand in for execution, and they cover only the shapes that fail
silently: merge resolution going missing (3,058 teams' totals stay below their
own capped games_played, a pair that is near-impossible on fresh totals and that
nothing raises on), the self-match
exclusion going missing (985 games repo-wide would each add a phantom win and a
phantom loss), the UPDATE losing its IS DISTINCT FROM guard (every page rewrites
every row), and the keyset paging collapsing back to a whole-table call, which is
cancelled at 8s in production and never in a test.

The last one is the defect this migration exists for. `backfill_total_game_stats`
carried `SET LOCAL statement_timeout = '300s'`, which is inert -- PostgreSQL arms
that timer once per top-level command and statements inside a function never
re-arm it -- so it was cancelled on every run for months while reporting nothing.
A test that let that pattern back in would be worthless, so it is asserted
against by name.

Objects resolve by NAME across every migration, newest definition wins. Pinning
to a filename looks equivalent and is not: objects here are superseded by new
migration files rather than edited in place, so a path-pinned guard stops
covering its object the moment anyone redefines it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"
CALLER = ROOT / "scripts" / "calculate_rankings.py"

FUNCTION = "backfill_total_game_stats_page"
SUPERSEDED = "backfill_total_game_stats"


def _executable(text: str) -> str:
    """`text` with -- line comments removed, leaving only SQL the server runs.

    Behavioural assertions must go through this. A substring check against
    comment-preserving text is satisfied by a commented-out clause -- and this
    migration's header comment names most of the things asserted below.
    """
    return "\n".join(re.sub(r"--.*$", "", line) for line in text.splitlines())


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", _executable(text)).strip()


def _migrations() -> list[Path]:
    """Every migration, oldest first: filenames are timestamp-prefixed."""
    return sorted(MIGRATIONS.glob("*.sql"))


def _function_body(name: str) -> str:
    """The newest dollar-quoted body defined for `name`, across all migrations."""
    pattern = rf"(?is)create\s+or\s+replace\s+function\s+(?:public\.)?{re.escape(name)}\s*\("
    found = None
    for path in _migrations():
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in re.finditer(pattern, sql):
            start = sql.index("$$", match.end())
            found = sql[start : sql.index("$$", start + 2) + 2]
    assert found is not None, f"no migration defines {name}"
    return found


def _newest_file_defining(name: str) -> Path:
    pattern = rf"(?is)create\s+or\s+replace\s+function\s+(?:public\.)?{re.escape(name)}\s*\("
    found = None
    for path in _migrations():
        if re.search(pattern, _executable(path.read_text(encoding="utf-8"))):
            found = path
    assert found is not None, f"no migration defines {name}"
    return found


def _update_statement() -> str:
    """The body's `UPDATE public.rankings_full ... ;` alone.

    Scoped deliberately. Asserting IS DISTINCT FROM against the whole body would
    also be satisfied by the dry-run branch's SELECT, which carries the same
    predicate -- so the guard could be deleted from the write and stay green.
    """
    body = _function_body(FUNCTION)
    start = re.search(r"(?is)\bupdate\s+public\.rankings_full\b", body)
    assert start, "the function no longer updates rankings_full"
    return _flat(body[start.start() : body.index(";", start.start()) + 1])


def test_the_page_resolves_team_merge_map():
    """Without this a team that absorbed a merge is counted from its own id only."""
    body = _flat(_function_body(FUNCTION))

    assert "public.team_merge_map" in body
    assert re.search(r"(?i)m\.canonical_team_id\s*,\s*m\.deprecated_team_id", body), (
        "the sources CTE must pair each canonical team with its deprecated ids"
    )


def test_a_game_between_two_ids_of_one_team_is_excluded_from_both_sides():
    """A merge can pull both endpoints onto one team; counting it scores W and L.

    Each clause is asserted whole, correlation included. Checking only that two
    NOT EXISTS survive and that each names an endpoint column leaves
    `o.canonical_id = s.canonical_id` deletable -- and without it the subquery
    matches any team in the page, so every game whose opponent happens to land in
    the same 2,000-row page is dropped. That is roughly 1.4% of games, silently,
    and a different 1.4% on every run.
    """
    body = _flat(_function_body(FUNCTION))

    assert body.count("NOT EXISTS") == 2, "both perspective joins need the exclusion"
    for opponent_column in ("g.away_team_master_id", "g.home_team_master_id"):
        clause = (
            "NOT EXISTS ( SELECT 1 FROM sources o "
            f"WHERE o.canonical_id = s.canonical_id AND o.source_id = {opponent_column} )"
        )
        assert clause in body, f"exclusion for {opponent_column} is not correlated to this team"


def test_the_perspective_columns_are_not_swapped():
    """`gf` is the team's own goals. Reversing the away pair inverts every away result."""
    body = _flat(_function_body(FUNCTION))

    assert "SELECT s.canonical_id, g.home_score AS gf, g.away_score AS ga" in body, "home perspective"
    assert "SELECT s.canonical_id, g.away_score, g.home_score" in body, "away perspective"


def test_a_win_is_scored_for_more_goals_than_conceded():
    """Swapping these two comparisons inverts every team's W and L site-wide."""
    body = _flat(_function_body(FUNCTION))

    assert "COUNT(*) FILTER (WHERE p.gf > p.ga)::integer AS total_wins" in body
    assert "COUNT(*) FILTER (WHERE p.gf < p.ga)::integer AS total_losses" in body
    assert "COUNT(*) FILTER (WHERE p.gf = p.ga)::integer AS total_draws" in body


def test_a_ranked_team_with_no_remaining_games_is_written_down_to_zero():
    """An inner join would leave it holding whatever it last had, forever."""
    body = _flat(_function_body(FUNCTION))

    assert "FROM batch b LEFT JOIN agg a ON a.canonical_id = b.team_id" in body
    for column in ("a.total_games", "a.total_wins", "a.total_losses", "a.total_draws"):
        assert f"COALESCE({column}, 0)" in body


def test_both_perspectives_drop_excluded_and_unscored_games():
    body = _flat(_function_body(FUNCTION))

    assert body.count("g.is_excluded = FALSE") == 2
    assert body.count("g.home_score IS NOT NULL") == 2
    assert body.count("g.away_score IS NOT NULL") == 2


def test_the_write_only_touches_rows_whose_values_moved():
    update = _update_statement()

    assert "IS DISTINCT FROM" in update, "an unguarded UPDATE rewrites every row every page"
    for column in ("total_games_played", "total_wins", "total_losses", "total_draws"):
        assert column in update, f"{column} left out of the guarded write"


def test_every_written_column_takes_its_value_from_the_recomputed_page():
    """Each SET must read the temp table, not the row it is updating.

    Reading the target back (`total_draws = r.total_draws`) is the mutation that
    survives a left-hand-side-only check: the column keeps its stale value, the
    IS DISTINCT FROM guard stays true forever, and every page rewrites the row
    while that column never converges.
    """
    update = _update_statement()
    set_clause = update[re.search(r"(?i)\bset\b", update).end() : re.search(r"(?i)\bfrom\b", update).start()]

    assignments = dict(
        re.findall(r"(total_(?:games_played|wins|losses|draws))\s*=\s*([A-Za-z_]+\.[A-Za-z_]+)", set_clause)
    )
    compared = set(re.findall(r"r\.(total_(?:games_played|wins|losses|draws))", update))

    assert set(assignments) == compared == {"total_games_played", "total_wins", "total_losses", "total_draws"}
    for column, source in assignments.items():
        assert source.startswith("t."), f"{column} is written from {source}, not the recomputed page"


def test_the_page_is_keyset_paged_by_the_caller():
    body = _flat(_function_body(FUNCTION))

    assert "p_after IS NULL OR r.team_id > p_after" in body, "the page must resume from p_after"
    assert "ORDER BY r.team_id LIMIT p_batch_size" in body


def test_the_page_reports_its_last_id_without_max_uuid():
    """PostgreSQL has no max(uuid); the error is a plan-time 42883 that CI cannot see."""
    body = _flat(_function_body(FUNCTION))

    assert re.search(r"(?i)ORDER BY t\.team_id DESC LIMIT 1", body)
    assert not re.search(r"(?i)\bmax\s*\(\s*t?\.?team_id", body)


def test_the_function_does_not_try_to_raise_its_own_timeout():
    """The inert pattern that froze these columns for months."""
    body = _flat(_function_body(FUNCTION))

    assert "statement_timeout" not in body


def test_a_dry_run_page_writes_nothing():
    body = _function_body(FUNCTION)
    dry_branch = body[body.index("IF p_dry_run THEN") : body.index("ELSE", body.index("IF p_dry_run THEN"))]

    assert "UPDATE" not in dry_branch.upper()


def test_the_writer_is_not_executable_by_public_clients():
    sql = _flat(_newest_file_defining(FUNCTION).read_text(encoding="utf-8"))

    revoke = f"REVOKE EXECUTE ON FUNCTION public.{FUNCTION}(uuid, integer, boolean) FROM PUBLIC, anon, authenticated"
    assert revoke in sql
    assert f"GRANT EXECUTE ON FUNCTION public.{FUNCTION}(uuid, integer, boolean) TO service_role" in sql


def test_the_function_is_security_definer_with_a_pinned_search_path():
    sql = _flat(_newest_file_defining(FUNCTION).read_text(encoding="utf-8"))
    header = sql[sql.index(f"CREATE OR REPLACE FUNCTION public.{FUNCTION}") : sql.index("$$")]

    assert "SECURITY DEFINER" in header
    assert "SET search_path = ''" in header


def test_the_ranking_run_calls_the_paged_function_and_not_the_superseded_one():
    """Matches RPC invocations only.

    The superseded name is both a prefix of the new one and the run's profiling
    section label, so a bare substring test reads either of those as a call.
    """
    caller = CALLER.read_text(encoding="utf-8")
    invoked = set(re.findall(r"\.rpc\(\s*[\"']([A-Za-z0-9_]+)[\"']", caller))

    assert FUNCTION in invoked
    assert SUPERSEDED not in invoked, "the whole-table call is cancelled on every run"
