"""Pin the canonical scrape-eligibility predicate and the migrations around it.

ci.yml applies no migrations, so nothing in CI ever executes this SQL. These text
assertions stand in for execution: they catch a copy of the predicate drifting away
from the other two, an OFFSET clause quietly going missing, the branches being joined
by something other than OR, or the filter reaching one of the two producers that must
never carry it.

Everything here resolves functions by NAME across every migration and reads the newest
definition of each. Pinning to specific migration filenames looks equivalent and is not:
functions in this repo are superseded by new files rather than edited in place, so a
path-pinned guard silently stops covering its function the moment anyone redefines it —
which is exactly the change it exists to catch.
"""

import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

# The three functions that must carry the rule, and the two that must never.
# find_recently_active_teams and find_yesterday_null_score_teams are the only
# automated producers that can re-enqueue a team that has started playing again;
# filtering either is what would make this a one-way door.
GATED_FUNCTIONS = ("find_stale_teams", "find_discovery_teams", "find_topup_teams")
REVIVAL_FUNCTIONS = ("find_recently_active_teams", "find_yesterday_null_score_teams")

REFRESH_FUNCTION = "refresh_team_scrape_activity"
COLUMNS_MIGRATION = MIGRATIONS / "20260827100000_add_teams_scrape_activity_columns.sql"

ANCHOR = "-- canonical-eligibility-v1"
# The anchor opens the block, so match it there rather than anywhere it is named —
# migration headers explain the convention and mention it in prose too.
ANCHORED_OPEN = re.compile(r"AND\s*\(\s*" + re.escape(ANCHOR))


def _sql(path: Path) -> str:
    """Read a migration with /* */ comments stripped.

    Line comments are deliberately kept: the anchor the extraction depends on is one.
    """
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def _function_bodies(sql: str, name: str) -> list[str]:
    """Every dollar-quoted body defined for `name` in this SQL text."""
    bodies = []
    pattern = rf"(?is)create\s+or\s+replace\s+function\s+(?:public\.)?{re.escape(name)}\s*\("
    for match in re.finditer(pattern, sql):
        start = sql.index("$$", match.end())
        end = sql.index("$$", start + 2)
        bodies.append(sql[start : end + 2])
    return bodies


def _newest_definition(name: str) -> tuple[Path, str]:
    """The migration that most recently defines `name`, and that body.

    Filenames are timestamp-prefixed, so sorting them is chronological order.
    """
    hits = [p for p in sorted(MIGRATIONS.glob("*.sql")) if _function_bodies(_sql(p), name)]
    assert hits, f"no migration defines {name}"
    return hits[-1], _function_bodies(_sql(hits[-1]), name)[-1]


def _predicate_blocks(sql: str) -> list[str]:
    """Every anchored predicate in `sql`, each extracted to its matching paren.

    A first-closing-paren regex cannot do this: the block nests parens in the EXISTS
    subquery, the COALESCE calls and the INTERVAL expressions.
    """
    blocks = []
    for anchor in ANCHORED_OPEN.finditer(sql):
        open_idx = sql.index("(", anchor.start())
        depth = 0
        i = open_idx
        while i < len(sql):
            char = sql[i]
            if char == "'":
                i = sql.index("'", i + 1) + 1
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(sql[open_idx : i + 1])
                    break
            i += 1
        else:
            raise AssertionError("unbalanced parentheses after the canonical-eligibility anchor")
    return blocks


def _normalize(block: str) -> str:
    return "\n".join(line.rstrip() for line in block.splitlines())


def _flat(block: str) -> str:
    return re.sub(r"\s+", " ", block)


def _bare(block: str) -> str:
    """Flattened, with the -- commentary removed, so structure can be matched."""
    stripped = re.sub(r"--[^\n]*", "", block)
    return re.sub(r"\s+", " ", stripped).strip()


def _live_copies() -> list[str]:
    """The one predicate copy inside each gated function's newest definition."""
    copies = []
    for name in GATED_FUNCTIONS:
        _, body = _newest_definition(name)
        blocks = _predicate_blocks(body)
        assert len(blocks) == 1, f"{name} carries {len(blocks)} copies of the predicate, expected 1"
        copies.append(blocks[0])
    return copies


# --------------------------------------------------------------------------- #
# The predicate itself
# --------------------------------------------------------------------------- #


def test_every_gated_function_carries_exactly_one_copy():
    assert len(_live_copies()) == len(GATED_FUNCTIONS)


def test_no_other_function_carries_a_copy():
    """A fourth copy anywhere in the migration tree is drift the identity test
    below cannot see, because it only compares the copies it knows about."""
    total = sum(len(_predicate_blocks(_sql(p))) for p in sorted(MIGRATIONS.glob("*.sql")))
    assert total == len(GATED_FUNCTIONS), f"expected {len(GATED_FUNCTIONS)} copies tree-wide, found {total}"


def test_all_live_copies_are_identical():
    normalized = {_normalize(block) for block in _live_copies()}
    assert len(normalized) == 1, "the canonical eligibility predicate has drifted between copies"


def test_the_branches_are_joined_by_or():
    """Load-bearing, and not implied by the branch tests below: flipping the four
    top-level ORs to ANDs uniformly leaves every branch assertion passing while
    making the predicate unsatisfiable for every row, so all three functions
    return nothing and production scraping stops with no failing check anywhere.
    """
    shape = re.compile(
        r"^\( "
        r"\(t\.last_fixture_at IS NOT NULL AND t\.last_fixture_at >= CURRENT_DATE - 30\) "
        r"OR EXISTS \(SELECT 1 FROM public\.ranking_history h "
        r"WHERE h\.team_id = t\.team_id_master AND h\.snapshot_date >= CURRENT_DATE - 30\) "
        r"OR \(t\.last_played_at IS NOT NULL AND t\.last_played_at > CURRENT_DATE - INTERVAL '12 months'\) "
        r"OR \(COALESCE\(t\.game_row_count, 0\) = 0 AND COALESCE\(t\.scrape_attempts, 0\) < 10\) "
        r"OR \(t\.last_scraped_at IS NULL OR t\.last_scraped_at < NOW\(\) - INTERVAL '6 months'\) "
        r"\)$"
    )
    for block in _live_copies():
        assert shape.match(_bare(block)), f"predicate shape changed:\n{_bare(block)}"


def test_every_copy_has_the_fixture_grace_branch():
    for block in _live_copies():
        assert re.search(
            r"t\.last_fixture_at IS NOT NULL AND t\.last_fixture_at >= CURRENT_DATE - 30",
            _flat(block),
        )


def test_every_copy_has_the_recently_ranked_branch():
    for block in _live_copies():
        assert re.search(
            r"EXISTS \(\s?SELECT 1 FROM public\.ranking_history h "
            r"WHERE h\.team_id = t\.team_id_master "
            r"AND h\.snapshot_date >= CURRENT_DATE - 30\s?\)",
            _flat(block),
        )


def test_every_copy_has_the_twelve_month_dormancy_branch():
    """Strictly greater-than, so the boundary day itself is dormant in all three."""
    for block in _live_copies():
        assert re.search(
            r"t\.last_played_at IS NOT NULL AND t\.last_played_at > CURRENT_DATE - INTERVAL '12 months'",
            _flat(block),
        )


def test_every_copy_has_the_never_productive_branch():
    """game_row_count, not last_played_at IS NULL: the latter would also capture
    the teams whose only rows are unscored or in the future."""
    for block in _live_copies():
        assert re.search(
            r"COALESCE\(t\.game_row_count, 0\) = 0 AND COALESCE\(t\.scrape_attempts, 0\) < 10",
            _flat(block),
        )


def test_every_copy_has_the_six_month_reprobe_branch():
    """Includes IS NULL deliberately: a never-scraped team with game rows would
    otherwise match no branch and be excluded permanently."""
    for block in _live_copies():
        assert re.search(
            r"t\.last_scraped_at IS NULL OR t\.last_scraped_at < NOW\(\) - INTERVAL '6 months'",
            _flat(block),
        )


def test_the_revival_producers_do_not_carry_the_predicate():
    for name in REVIVAL_FUNCTIONS:
        path, body = _newest_definition(name)
        assert ANCHOR not in body, f"{name}, newest definition in {path.name}, carries the eligibility predicate"


# --------------------------------------------------------------------------- #
# find_topup_teams
# --------------------------------------------------------------------------- #


def test_topup_signature_takes_an_absolute_cutoff_and_an_offset():
    path, _ = _newest_definition("find_topup_teams")
    sql = _flat(_sql(path))
    assert "p_cutoff timestamptz" in sql
    assert "p_row_limit integer DEFAULT 1000" in sql
    assert "p_offset integer DEFAULT 0" in sql


def test_topup_applies_its_offset():
    """PostgreSQL accepts a declared-but-unused parameter and CI applies no
    migrations, so an omitted OFFSET clause would pass every other test here
    while returning page 0 forever and hanging the caller's paging loop."""
    _, body = _newest_definition("find_topup_teams")
    assert "OFFSET find_topup_teams.p_offset" in body


def test_topup_orders_by_a_unique_tiebreaker():
    """last_scraped_at is stamped per run, so tie groups span thousands of rows.
    Without a unique secondary key, OFFSET paging can repeat or skip rows."""
    _, body = _newest_definition("find_topup_teams")
    assert "ORDER BY t.last_scraped_at DESC, t.team_id_master" in _flat(body)


def test_topup_returns_exactly_the_columns_the_scrape_path_reads():
    from scripts.drain_queue import _TEAM_KEYS

    path, _ = _newest_definition("find_topup_teams")
    returns = re.search(r"RETURNS TABLE\((.*?)\)\s*LANGUAGE", _flat(_sql(path))).group(1)
    columns = [part.strip().split()[0] for part in returns.split(",")]
    assert columns == list(_TEAM_KEYS)


def test_topup_is_locked_down_to_service_role():
    path, _ = _newest_definition("find_topup_teams")
    sql = _sql(path)
    assert "REVOKE EXECUTE ON FUNCTION public.find_topup_teams" in sql
    assert "FROM PUBLIC, anon, authenticated" in sql
    assert "GRANT EXECUTE ON FUNCTION public.find_topup_teams" in sql
    assert "TO service_role" in sql


# --------------------------------------------------------------------------- #
# The columns and the refresh
# --------------------------------------------------------------------------- #


def test_all_four_columns_are_added_idempotently():
    sql = _sql(COLUMNS_MIGRATION)
    for column, type_name in (
        ("last_played_at", "DATE"),
        ("last_fixture_at", "DATE"),
        ("game_row_count", "INTEGER"),
        ("scrape_attempts", "INTEGER"),
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column} {type_name}" in sql
        assert f"COMMENT ON COLUMN teams.{column}" in sql


def _refresh_body() -> str:
    _, body = _newest_definition(REFRESH_FUNCTION)
    return body


def _refresh_update_statement() -> str:
    """The batch UPDATE alone, so assertions about it cannot be satisfied by prose."""
    body = _refresh_body()
    start = body.index("UPDATE public.teams t")
    return body[start : body.index(";", start) + 1]


def test_refresh_pages_by_keyset_rather_than_running_whole_table():
    """A function cannot raise its own statement_timeout — PostgreSQL arms that
    timer once per top-level command — and a service-role PostgREST request
    inherits an 8s budget, so a single whole-table call is cancelled every run."""
    body = _refresh_body()
    assert "p_after" in body and "LIMIT p_batch_size" in body
    assert "SET LOCAL statement_timeout" not in body, (
        "SET LOCAL cannot extend the timer already armed for this call; it reads as a "
        "guard while providing none"
    )


def test_refresh_returns_the_pages_last_id_so_the_caller_can_advance():
    path, body = _newest_definition(REFRESH_FUNCTION)
    assert "RETURNS TABLE (rows_changed integer, last_team_id uuid)" in _sql(path)
    # MAX over the page, not over the rows that changed: a page where nothing
    # moved must still carry the walk forward or the caller loops forever.
    assert re.search(r"SELECT MAX\(b\.team_id_master\) INTO v_last", body)


def test_refresh_keys_the_batch_off_teams():
    """A games-driven key set cannot emit a row for a zero-game team, which is
    exactly the cohort the never-productive branch exists to describe."""
    body = _flat(_refresh_body())
    assert "FROM batch b LEFT JOIN game_agg g ON g.canonical_id = b.team_id_master" in body
    assert "LEFT JOIN log_agg l ON l.canonical_id = b.team_id_master" in body


def test_refresh_materialises_counts_as_zero_not_null():
    body = _flat(_refresh_body())
    assert "COALESCE(g.game_row_count, 0)::integer" in body
    assert "COALESCE(l.non_error_attempts, 0)::integer" in body


def test_refresh_gathers_merged_away_ids_before_aggregating():
    """A merge repoints neither games nor team_scrape_log, so a page that reads
    only its canonical ids undercounts every team that has absorbed one."""
    body = _flat(_refresh_body())
    assert "FROM public.team_merge_map m JOIN batch b ON b.team_id_master = m.canonical_team_id" in body
    assert "JOIN public.games g ON g.home_team_master_id = s.source_id" in body
    assert "JOIN public.games g ON g.away_team_master_id = s.source_id" in body
    assert "JOIN public.team_scrape_log l ON l.team_id = s.source_id" in body


def test_refresh_separates_played_from_scheduled():
    """last_played_at is scored games only and last_fixture_at is every row; that
    difference is what separates the 12-month dormancy branch from the 30-day
    grace. Dropping the FILTER makes dormancy match any recent fixture and the
    whole rule no-ops; adding one to last_fixture_at kills the grace branch."""
    body = _flat(_refresh_body())
    assert (
        "MAX(gr.game_date) FILTER ( WHERE gr.home_score IS NOT NULL AND gr.away_score IS NOT NULL ) "
        "AS last_played_at" in body
    )
    assert "MAX(gr.game_date) AS last_fixture_at" in body


def test_refresh_excludes_error_rows_from_the_attempt_count():
    """Bulk consumers persist WAF blocks and 404s as status='error'; counting them
    would let transient failures retire a live team as never-productive."""
    assert "WHERE l.status <> 'error'" in _flat(_refresh_body())


def test_refresh_only_writes_rows_whose_values_moved():
    """Asserted against the UPDATE statement itself. A file-wide substring check
    is satisfied by the migration's own header comment and cannot fail."""
    update = _flat(_refresh_update_statement())
    assert "IS DISTINCT FROM" in update
    assert "(t.last_played_at, t.last_fixture_at, t.game_row_count, t.scrape_attempts)" in update


def test_refresh_dry_run_counts_without_writing():
    body = _refresh_body()
    dry_branch = body[body.index("IF p_dry_run THEN") : body.index("ELSE")]
    assert "SELECT COUNT(*) INTO v_changed" in dry_branch
    assert "IS DISTINCT FROM" in _flat(dry_branch)
    assert "UPDATE" not in dry_branch.upper()


def test_refresh_is_locked_down_to_service_role():
    path, _ = _newest_definition(REFRESH_FUNCTION)
    sql = _flat(_sql(path))
    assert (
        "REVOKE EXECUTE ON FUNCTION public.refresh_team_scrape_activity(uuid, integer, boolean) "
        "FROM PUBLIC, anon, authenticated" in sql
    )
    assert (
        "GRANT EXECUTE ON FUNCTION public.refresh_team_scrape_activity(uuid, integer, boolean) "
        "TO service_role" in sql
    )
