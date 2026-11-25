"""Execute the scheduled-job check's SQL against PostgreSQL, exactly as the script sends it.

Each case runs in one transaction on one cursor and rolls back: PostgreSQL's now() is then the
same for the inserts and the query, so a row placed at exactly a window's edge tests which window
owns it, and a SET LOCAL override cannot outlive its case.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from scripts import check_scheduled_jobs as job

UTC = timezone.utc
START = "2026-11-23 12:30+00"
MONDAY = date(2026, 11, 23)


@pytest.fixture(scope="module")
def database(postgres_database):
    with postgres_database("scheduled_jobs_check_") as (connection, _):
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE public.rankings_full (team_id uuid, last_calculated timestamptz);
                CREATE TABLE public.ranking_history (team_id uuid, snapshot_date date);
                CREATE TABLE public.providers (id uuid PRIMARY KEY, code text);
                CREATE TABLE public.build_logs (provider_id uuid, started_at timestamptz, parameters jsonb);
                CREATE TABLE public.games (provider_id uuid, created_at timestamptz);
                CREATE TABLE public.scrape_requests (
                  status text, processed_at timestamptz, requested_at timestamptz, completed_at timestamptz
                );
            """)
        yield connection


def run_case(connection, setup, query, *, start=START):
    with connection.cursor() as cursor:
        cursor.execute("BEGIN")
        try:
            if start is not None:
                cursor.execute("SET LOCAL pitchrank.ranking_start = %s", (start,))
            setup(cursor)
            cursor.execute(query)
            names = [column.name for column in cursor.description]
            rows = cursor.fetchall()
        finally:
            cursor.execute("ROLLBACK")
    assert len(rows) == 1
    return dict(zip(names, rows[0]))


def published(cursor, count, at):
    cursor.execute(
        "INSERT INTO public.rankings_full SELECT gen_random_uuid(), %s FROM generate_series(1, %s)", (at, count)
    )


def snapshot(cursor, count, day):
    cursor.execute(
        "INSERT INTO public.ranking_history SELECT gen_random_uuid(), %s FROM generate_series(1, %s)", (day, count)
    )


FRESH = datetime(2026, 11, 24, 3, 56, tzinfo=UTC)


def publication(connection, setup, **kwargs):
    return run_case(connection, setup, job.PUBLICATION_SQL, **kwargs)


def test_a_fresh_publication_near_its_snapshot_is_complete(database):
    def setup(cursor):
        published(cursor, 997, FRESH)
        snapshot(cursor, 1000, MONDAY - timedelta(days=4))

    result = publication(database, setup)

    assert result["read_only"] == "off"
    assert result["complete"] is True
    assert (result["row_count"], result["stale_rows"], result["previous_snapshot_rows"]) == (997, 0, 1000)
    assert result["previous_snapshot_date"] == MONDAY - timedelta(days=4)


@pytest.mark.parametrize(
    "rows, stale",
    [([FRESH] * 9 + [datetime(2026, 11, 23, 12, 29, tzinfo=UTC)], 1), ([FRESH] * 9 + [None], 1)],
    ids=["refreshed before the start", "never refreshed"],
)
def test_a_row_the_run_did_not_refresh_is_not_complete(database, rows, stale):
    def setup(cursor):
        for at in rows:
            cursor.execute("INSERT INTO public.rankings_full VALUES (gen_random_uuid(), %s)", (at,))
        snapshot(cursor, 10, MONDAY - timedelta(days=4))

    result = publication(database, setup)

    assert (result["stale_rows"], result["complete"]) == (stale, False)


def test_an_empty_table_is_not_complete(database):
    result = publication(database, lambda cursor: snapshot(cursor, 10, MONDAY - timedelta(days=4)))

    assert (result["row_count"], result["complete"]) == (0, False)


def test_ninety_four_percent_of_the_snapshot_is_not_complete(database):
    def setup(cursor):
        published(cursor, 94, FRESH)
        snapshot(cursor, 100, MONDAY - timedelta(days=4))

    assert publication(database, setup)["complete"] is False


def test_a_run_that_crossed_midnight_is_compared_with_the_week_before(database):
    """The run's own snapshot is dated Monday, the day it started; its rows were published on
    Tuesday. Comparing with Monday's snapshot would pass a run that lost two fifths of its teams."""

    def setup(cursor):
        published(cursor, 90, datetime(2026, 11, 24, 3, 0, tzinfo=UTC))
        snapshot(cursor, 90, MONDAY)
        snapshot(cursor, 150, MONDAY - timedelta(days=7))

    result = publication(database, setup)

    assert result["previous_snapshot_date"] == MONDAY - timedelta(days=7)
    assert result["complete"] is False


def test_with_no_earlier_snapshot_nothing_is_complete(database):
    def setup(cursor):
        published(cursor, 10, FRESH)
        snapshot(cursor, 10, MONDAY)

    result = publication(database, setup)

    assert result["previous_snapshot_rows"] is None and result["complete"] is False


@pytest.mark.parametrize(
    "clock, start",
    [
        ("2026-11-23 06:41+00", datetime(2026, 11, 16, 12, 30, tzinfo=UTC)),
        ("2026-11-23 12:29:59+00", datetime(2026, 11, 16, 12, 30, tzinfo=UTC)),
        ("2026-11-23 12:30+00", datetime(2026, 11, 23, 12, 30, tzinfo=UTC)),
        ("2026-11-25 15:00+00", datetime(2026, 11, 23, 12, 30, tzinfo=UTC)),
    ],
    ids=["Monday morning", "a second before", "the start itself", "Wednesday"],
)
def test_the_default_start_is_the_latest_monday_half_past_noon_at_or_before_now(database, clock, start):
    """The clock is stopped by a `now()` that shadows the built-in: with pg_catalog listed after
    its schema on the search path, the query's unqualified `now()` resolves to it. Both are dropped
    with the transaction."""

    def setup(cursor):
        cursor.execute("CREATE SCHEMA test_clock")
        cursor.execute(
            "CREATE FUNCTION test_clock.now() RETURNS timestamptz LANGUAGE sql STABLE "
            f"AS $$ SELECT timestamptz '{clock}' $$"
        )
        cursor.execute("SET LOCAL search_path = test_clock, pg_catalog, public")

    assert publication(database, setup, start=None)["ranking_start"] == start


def provider(cursor, code):
    provider_id = str(uuid4())
    cursor.execute("INSERT INTO public.providers VALUES (%s, %s)", (provider_id, code))
    return provider_id


def test_a_dry_run_build_row_is_not_a_heartbeat(database):
    def setup(cursor):
        real, dry = provider(cursor, "real"), provider(cursor, "dry")
        cursor.execute(
            "INSERT INTO public.build_logs VALUES (%s, now() - interval '1 day', '{\"dry_run\": false}'),"
            " (%s, now() - interval '1 day', '{\"dry_run\": true}'), (%s, now() - interval '2 days', '{}')",
            (real, dry, dry),
        )

    result = run_case(database, setup, job.BUILD_HEARTBEAT_QUERY, start=None)

    beats = {r["code"]: r["last_logged"] for r in result["heartbeats"]}
    assert set(beats) == {"real", "dry"}
    assert beats["dry"] < beats["real"]


def test_new_games_fall_in_the_window_that_owns_each_edge(database):
    def setup(cursor):
        code = provider(cursor, "edges")
        for interval in ("7 days", "14 days", "42 days", "42 days 1 second"):
            cursor.execute(f"INSERT INTO public.games VALUES (%s, now() - interval '{interval}')", (code,))

    result = run_case(database, setup, job.GAME_WINDOWS_QUERY, start=None)

    (counts,) = result["game_windows"]
    assert counts == {"code": "edges", "last_week": 1, "week_before": 1, "baseline_4_weeks": 1}


def queue(database, *rows):
    def setup(cursor):
        for status, processed, requested, completed in rows:
            cursor.execute(
                "INSERT INTO public.scrape_requests VALUES (%s, now() - %s::interval, now() - %s::interval,"
                " now() - %s::interval)",
                (status, processed, requested, completed),
            )

    return run_case(database, setup, job.SCRAPE_QUEUE_QUERY, start=None)


def test_a_request_is_stuck_after_six_hours_in_processing(database):
    result = queue(
        database,
        ("processing", "6 hours 1 minute", "7 hours", "1 year"),
        ("processing", "30 hours", "31 hours", "1 year"),
        ("processing", "5 hours 59 minutes", "7 hours", "1 year"),
        ("completed", "40 hours", "41 hours", "8 hours"),
    )

    with database.cursor() as cursor:
        cursor.execute("SELECT now()")
        (now,) = cursor.fetchone()
    assert result["stuck_processing"] == 2
    assert now - timedelta(hours=31) < result["oldest_stuck_claimed"] < now - timedelta(hours=29)


def test_a_request_in_processing_under_six_hours_is_not_stuck(database):
    result = queue(database, ("processing", "5 hours 59 minutes", "7 hours", "1 year"))

    assert (result["stuck_processing"], result["oldest_stuck_claimed"]) == (0, None)


@pytest.mark.parametrize(
    "status, completed, recent",
    [
        ("completed", "5 hours 59 minutes", True),
        ("completed", "6 hours 1 minute", False),
        ("failed", "1 minute", False),
    ],
)
def test_only_a_recent_completed_request_is_progress(database, status, completed, recent):
    assert queue(database, (status, "7 hours", "8 hours", completed))["completed_recently"] is recent


def test_the_oldest_pending_request_is_reported(database):
    result = queue(
        database,
        ("pending", "1 hour", "3 hours", "1 year"),
        ("pending", "1 hour", "5 hours", "1 year"),
        ("completed", "9 hours", "10 hours", "8 hours"),
    )

    with database.cursor() as cursor:
        cursor.execute("SELECT now()")
        (now,) = cursor.fetchone()
    assert now - timedelta(hours=6) < result["oldest_pending_requested"] < now - timedelta(hours=4)
