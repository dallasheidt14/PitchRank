"""Execute winner-study migration, immutable pregame pairing and sealed review in PostgreSQL."""

from copy import deepcopy
from pathlib import Path

import pytest

from src.predictions.score_study import serialized
from src.predictions.winner_study import winner_payload
from tests.integration.test_compare_monitoring import capture, monitor  # noqa: F401
from tests.integration.test_prospective_ledger import database, forecast  # noqa: F401
from tests.score_study_fixtures import baseline
from tests.winner_study_fixtures import definition

psycopg2 = pytest.importorskip("psycopg2")


@pytest.fixture
def winner_pair(database, forecast, request):
    connection, _ = database
    row, game, _ = forecast
    with connection.cursor() as cursor:
        cursor.execute("SELECT (date_trunc('week',clock_timestamp() AT TIME ZONE 'UTC')+interval '1 week')::date")
        start = cursor.fetchone()[0]
        cursor.execute("UPDATE games SET game_date=%s WHERE id=%s", (start, game))
        cursor.execute("UPDATE prospective_match_predictions SET game_date=%s WHERE id=%s", (start, row))
    parent = request.getfixturevalue("monitor")
    p = parent[4]
    p["prediction"] = baseline()
    p["variants"] = {str(v): deepcopy(p["prediction"]) for v in (0, 0.5, 1, 1.5)}
    p["receipt"]["source_hashes"] = {"matchPredictor.ts": "a" * 64}
    for key in ("teamAInput", "teamBInput"):
        p["context"][key].update(age=12, gender="M", games_played=8)
    assert capture(parent, p)
    m = definition(start, parent[3], "a" * 64)
    with connection.cursor() as cursor:
        cursor.execute("SELECT register_compare_winner_study(%s)", (serialized(m),))
        sig = cursor.fetchone()[0]
        cursor.execute("SELECT compare_winner_capture_queue(%s)", (sig,))
        queued = next(r[0] for r in cursor.fetchall() if r[0]["baseline_forecast_id"] == str(row))
    output = {
        "prediction": baseline(),
        "receipt": {
            "aa_parity": True,
            "baseline_replay": True,
            "reference_time": p["reference_time"],
            "source_hashes": p["receipt"]["source_hashes"],
            "generated_source_sha256": "b" * 64,
        },
    }
    return connection, sig, row, game, m, winner_payload(queued, m, output, sig)


def freeze(pair, payload=None):
    with pair[0].cursor() as cursor:
        cursor.execute(
            "SELECT freeze_compare_winner_forecast(%s,%s,%s)",
            (pair[1], pair[2], serialized(pair[5] if payload is None else payload)),
        )
        return cursor.fetchone()[0]


def test_immutable_pregame_pair_retry_and_sealed_review(winner_pair):
    assert freeze(winner_pair)
    assert freeze(winner_pair, {"changed": True}) is False
    with winner_pair[0].cursor() as cursor:
        cursor.execute(
            "SELECT payload,captured_at<=clock_timestamp() FROM compare_winner_forecasts WHERE study_signature=%s AND baseline_forecast_id=%s",
            (winner_pair[1], winner_pair[2]),
        )
        payload, timestamp_valid = cursor.fetchone()
        assert payload == winner_pair[5] and timestamp_valid
        with pytest.raises(psycopg2.Error, match="immutable"):
            cursor.execute("DELETE FROM compare_winner_forecasts WHERE study_signature=%s", (winner_pair[1],))
        cursor.execute("SELECT compare_winner_review(%s,NULL,500,false)", (winner_pair[1],))
        sealed = cursor.fetchone()[0]
        assert sealed["open"] is False and "result" not in sealed and "payload" not in sealed
        cursor.execute("SELECT compare_winner_capture_queue(%s)", (winner_pair[1],))
        assert not any(r[0]["baseline_forecast_id"] == str(winner_pair[2]) for r in cursor.fetchall())


@pytest.mark.parametrize(
    "change",
    [
        "home_score=0",
        "away_score=0",
        "is_excluded=true",
        "game_date=game_date+1",
        "provider_id=gen_random_uuid()",
        "source_url='https://changed.test'",
        "home_team_master_id=gen_random_uuid()",
        "away_team_master_id=gen_random_uuid()",
    ],
)
def test_source_changes_reject_capture(winner_pair, change):
    with winner_pair[0].cursor() as cursor:
        cursor.execute("UPDATE games SET " + change + " WHERE id=%s", (winner_pair[3],))
    with pytest.raises(psycopg2.Error, match="Source fixture changed"):
        freeze(winner_pair)


@pytest.mark.parametrize(
    "field",
    [
        "weights",
        "execution_hashes",
        "baseline_payload_sha256",
        "reference_time",
        "source_hashes",
        "aa_parity",
        "baseline_replay",
        "risk",
        "probability",
        "score",
    ],
)
def test_wrong_provenance_or_incomplete_output_is_rejected(winner_pair, field):
    p = deepcopy(winner_pair[5])
    if field in ("weights", "execution_hashes"):
        p[field] = {}
    elif field == "baseline_payload_sha256":
        p[field] = "f" * 64
    elif field in ("reference_time", "source_hashes", "aa_parity", "baseline_replay"):
        p["receipt"].pop(field)
    else:
        prediction = p["candidates"]["weighted"]["prediction"]
        prediction.pop(
            {"risk": "blowout4PlusProbability", "probability": "drawProbability", "score": "expectedScore"}[field]
        )
    with pytest.raises(psycopg2.Error):
        freeze(winner_pair, p)


def test_roles_and_date_protection(winner_pair):
    with winner_pair[0].cursor() as cursor:
        cursor.execute("SELECT compare_monitor_results_open(%s)", (winner_pair[4]["capture_start"],))
        assert cursor.fetchone()[0] is False
        for role in ("anon", "authenticated", "service_role"):
            cursor.execute("SET ROLE " + role)
            try:
                with pytest.raises(psycopg2.Error, match="permission denied"):
                    cursor.execute("DELETE FROM compare_winner_studies")
                if role != "service_role":
                    with pytest.raises(psycopg2.Error, match="permission denied"):
                        cursor.execute("SELECT compare_winner_review(%s)", (winner_pair[1],))
            finally:
                cursor.execute("RESET ROLE")


@pytest.mark.parametrize("change", ["minimum", "window", "review", "training", "baseline", "weights"])
def test_server_rejects_changed_registration(winner_pair, change):
    m = deepcopy(winner_pair[4])
    if change == "minimum":
        m["policy"]["minimum_pairs"] = 20
    elif change == "window":
        m["capture_end"] = m["capture_start"]
    elif change == "review":
        m["review_not_before"] = m["capture_end"]
    elif change == "training":
        m["latest_training_game"] = m["capture_start"]
    elif change == "baseline":
        m["baseline_model_signature"] = "f" * 64
    else:
        m["weights"]["schedule"] = -1
    with winner_pair[0].cursor() as cursor, pytest.raises(psycopg2.Error):
        cursor.execute("SELECT register_compare_winner_study(%s)", (serialized(m),))


def test_sealed_branch_never_reads_target_games(winner_pair):
    assert freeze(winner_pair)
    c = winner_pair[0]
    c.autocommit = False
    try:
        with c.cursor() as cursor:
            cursor.execute("ALTER TABLE games RENAME TO hidden_target_games")
            cursor.execute("SELECT compare_winner_review(%s,NULL,500,false)", (winner_pair[1],))
            assert cursor.fetchone()[0]["open"] is False
    finally:
        c.rollback()
        c.autocommit = True


def test_released_review_retains_exact_source_date(winner_pair):
    assert freeze(winner_pair)
    c = winner_pair[0]
    c.autocommit = False
    try:
        with c.cursor() as cursor:
            cursor.execute(
                "CREATE OR REPLACE FUNCTION compare_winner_review_open(p_signature text) RETURNS boolean LANGUAGE sql AS 'SELECT true'"
            )
            cursor.execute(
                "UPDATE games SET game_date=game_date+1,home_score=3,away_score=1 WHERE id=%s", (winner_pair[3],)
            )
            cursor.execute("SELECT compare_winner_review(%s,NULL,500,false)", (winner_pair[1],))
            row = next(r[0] for r in cursor.fetchall() if r[0]["baseline_forecast_id"] == str(winner_pair[2]))
            assert row["result"] is None
    finally:
        c.rollback()
        c.autocommit = True


def test_migration_reapplication_preserves_frozen_pairs(winner_pair):
    assert freeze(winner_pair)
    migration = Path(__file__).resolve().parents[2] / "supabase/migrations/20261120000000_compare_winner_study.sql"
    with winner_pair[0].cursor() as cursor:
        cursor.execute(
            "SELECT payload_sha256,captured_at FROM compare_winner_forecasts WHERE study_signature=%s AND baseline_forecast_id=%s",
            (winner_pair[1], winner_pair[2]),
        )
        before = cursor.fetchone()
        cursor.execute(migration.read_text())
        cursor.execute(
            "SELECT payload_sha256,captured_at FROM compare_winner_forecasts WHERE study_signature=%s AND baseline_forecast_id=%s",
            (winner_pair[1], winner_pair[2]),
        )
        assert cursor.fetchone() == before


def test_winner_hold_blocks_a_past_day_without_other_experiment_holds(winner_pair):
    c = winner_pair[0]
    c.autocommit = False
    try:
        with c.cursor() as cursor:
            cursor.execute("SELECT pg_get_functiondef('public.compare_monitor_results_open(date)'::regprocedure)")
            definition = cursor.fetchone()[0]
            cursor.execute(definition.replace("statement_timestamp()", "'2030-01-08T12:00:00Z'::timestamptz"))
            cursor.execute("ALTER TABLE compare_winner_studies DISABLE TRIGGER immutable_compare_winner_studies")
            cursor.execute(
                "UPDATE compare_winner_studies SET capture_start='2030-01-07',capture_end='2030-02-03',review_not_before='2030-02-04' WHERE signature=%s",
                (winner_pair[1],),
            )
            cursor.execute("SELECT compare_monitor_results_open('2030-01-07')")
            assert cursor.fetchone()[0] is False
            cursor.execute(
                "UPDATE compare_winner_studies SET capture_start='2040-01-01',capture_end='2040-01-28',review_not_before='2040-01-29' WHERE signature=%s",
                (winner_pair[1],),
            )
            cursor.execute("SELECT compare_monitor_results_open('2030-01-07')")
            assert cursor.fetchone()[0] is True
    finally:
        c.rollback()
        c.autocommit = True


def test_final_server_clock_recheck_rejects_crossing_into_match_day(winner_pair):
    connection = winner_pair[0]
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT game_date::text FROM games WHERE id=%s", (winner_pair[3],))
            midnight = cursor.fetchone()[0] + "T00:00:00+00:00"
            cursor.execute("CREATE TEMP SEQUENCE winner_clock_calls")
            cursor.execute(
                """CREATE FUNCTION pg_temp.winner_clock() RETURNS timestamptz LANGUAGE sql VOLATILE AS $$
                SELECT CASE WHEN nextval('pg_temp.winner_clock_calls')=1
                  THEN %s::timestamptz-interval '1 second' ELSE %s::timestamptz END $$""",
                (midnight, midnight),
            )
            cursor.execute(
                "SELECT pg_get_functiondef('public.freeze_compare_winner_forecast(text,uuid,text)'::regprocedure)"
            )
            actual_definition = cursor.fetchone()[0]
            # Change only the clock source in this rolled-back test, leaving the production guard body intact.
            cursor.execute(actual_definition.replace("clock_timestamp()", "pg_temp.winner_clock()"))
            cursor.execute("SAVEPOINT before_late_capture")
            with pytest.raises(psycopg2.Error, match="Match day began"):
                freeze(winner_pair)
            cursor.execute("ROLLBACK TO SAVEPOINT before_late_capture")
            cursor.execute(
                "SELECT count(*) FROM compare_winner_forecasts WHERE study_signature=%s AND baseline_forecast_id=%s",
                (winner_pair[1], winner_pair[2]),
            )
            assert cursor.fetchone()[0] == 0
    finally:
        connection.rollback()
        connection.autocommit = True
