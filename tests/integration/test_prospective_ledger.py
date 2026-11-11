"""Execute the actual ledger migrations against an isolated local PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import sql
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def database(postgres_database):
    with postgres_database("compare_test_") as (connection, parameters):
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE public.teams (team_id_master UUID PRIMARY KEY);
                CREATE TABLE public.games (
                  id UUID PRIMARY KEY, game_date DATE, provider_id UUID,
                  home_team_master_id UUID, away_team_master_id UUID,
                  home_score INTEGER, away_score INTEGER, is_excluded BOOLEAN DEFAULT FALSE, source_url TEXT
                );
            """)
            cursor.execute((ROOT / "supabase/migrations/20260410000000_create_prospective_match_predictions.sql").read_text())
            # Execute every subsequent migration touching this ledger, so replacements stay covered.
            for migration in sorted((ROOT / "supabase/migrations").glob("*.sql")):
                if migration.name <= "20260410000000_create_prospective_match_predictions.sql":
                    continue
                content = migration.read_text(encoding="utf-8")
                if "prospective_match_predictions" in content:
                    cursor.execute(content)
        yield connection, parameters

@pytest.fixture
def forecast(database):
    connection, _ = database
    home, away, game_id, provider = [str(uuid4()) for _ in range(4)]
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO games VALUES (%s, (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::DATE + 1, %s, %s, %s, NULL, NULL, FALSE, NULL)",
                       (game_id, provider, home, away))
        cursor.execute("""
            INSERT INTO prospective_match_predictions (
              fixture_key, source_game_id, game_date, home_team_name, away_team_name,
              home_team_master_id, away_team_master_id, resolution_status, fixture_payload
            ) VALUES (%s,%s,(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::DATE+1,'A','B',%s,%s,'resolved',%s)
            RETURNING id
        """, ("database:" + game_id, game_id, home, away, Json({"source_snapshot": {
            "home_team_master_id": home, "away_team_master_id": away, "provider_id": provider}})))
        row_id = cursor.fetchone()[0]
    payload = {"modelVersion": "test-model", "modelSignature": str(uuid4()), "codeRevision": "test-revision",
               "shadowContext": {"predictorVersion": "test-model", "frozenEvidence": {"games": []}}}
    return row_id, game_id, payload


def freeze(connection, row_id, payload):
    with connection.cursor() as cursor:
        cursor.execute("SELECT freeze_prospective_forecast(%s,%s,%s)", (row_id, "test-model", Json(payload)))
        return cursor.fetchone()[0]


def test_freeze_is_once_only_and_does_not_accept_backdated_timestamp(database, forecast):
    connection, _ = database
    row, _, payload = forecast
    assert freeze(connection, row, payload) is True
    assert freeze(connection, row, {"changed": True}) is False
    with connection.cursor() as cursor:
        cursor.execute("SELECT heuristic_predicted_at > clock_timestamp() - interval '1 minute' FROM prospective_match_predictions WHERE id=%s", (row,))
        assert cursor.fetchone()[0] is True
        with pytest.raises(psycopg2.Error, match="immutable"):
            cursor.execute("UPDATE prospective_match_predictions SET heuristic_predicted_at='2020-01-01' WHERE id=%s", (row,))
        with pytest.raises(psycopg2.Error, match="immutable"):
            cursor.execute("UPDATE prospective_match_predictions SET game_date=game_date+1 WHERE id=%s", (row,))
        with pytest.raises(psycopg2.Error, match="cannot be deleted"):
            cursor.execute("DELETE FROM prospective_match_predictions WHERE id=%s", (row,))
        cursor.execute("UPDATE prospective_match_predictions SET actual_home_score=2, actual_away_score=1, evaluation_status='settled' WHERE id=%s", (row,))


@pytest.mark.parametrize("change", [
    "home_score=0", "away_score=0", "is_excluded=TRUE", "game_date=game_date+1",
    "home_team_master_id=gen_random_uuid()", "away_team_master_id=gen_random_uuid()",
    "provider_id=gen_random_uuid()",
    "source_url='https://example.com/games/456'",
])
def test_database_rechecks_each_source_field(database, forecast, change):
    connection, _ = database
    row, game, payload = forecast
    with connection.cursor() as cursor:
        cursor.execute("UPDATE games SET " + change + " WHERE id=%s", (game,))
    with pytest.raises(psycopg2.Error, match="Source fixture changed"):
        freeze(connection, row, payload)


def test_database_refuses_same_day_and_payload_version_conflict(database, forecast):
    connection, _ = database
    row, _, payload = forecast
    payload["modelVersion"] = "wrong"
    with pytest.raises(psycopg2.Error, match="inconsistent"):
        freeze(connection, row, payload)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE prospective_match_predictions SET game_date=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::DATE WHERE id=%s", (row,))
    payload["modelVersion"] = "test-model"
    assert freeze(connection, row, payload) is False


def test_two_workers_cannot_replace_each_others_forecast(database, forecast):
    _, parameters = database
    row, _, payload = forecast
    def worker(number):
        with psycopg2.connect(**parameters) as connection:
            return freeze(connection, row, {**payload, "worker": number})
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, [1, 2])) == [False, True]


def test_public_roles_cannot_freeze_or_read_ledger(database, forecast):
    connection, _ = database
    row, _, payload = forecast
    with connection.cursor() as cursor:
        for role in ("anon", "authenticated"):
            cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            try:
                with pytest.raises(psycopg2.Error, match="permission denied"):
                    freeze(connection, row, payload)
                with pytest.raises(psycopg2.Error, match="permission denied"):
                    cursor.execute("SELECT * FROM prospective_match_predictions")
            finally:
                cursor.execute("RESET ROLE")


def test_service_role_can_freeze_and_read_but_not_rewrite_evidence(database, forecast):
    connection, _ = database
    row, _, payload = forecast
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE service_role")
        try:
            assert freeze(connection, row, payload)
            cursor.execute("SELECT heuristic_prediction_status FROM prospective_match_predictions WHERE id=%s", (row,))
            assert cursor.fetchone()[0] == "completed"
            cursor.execute("SELECT model_version FROM compare_calibration_experiments WHERE model_signature=%s",
                           (payload["modelSignature"],))
            assert cursor.fetchone()[0] == "test-model"
            with pytest.raises(psycopg2.Error, match="immutable"):
                cursor.execute("UPDATE prospective_match_predictions SET heuristic_prediction='{}' WHERE id=%s", (row,))
            with pytest.raises(psycopg2.Error, match="permission denied"):
                cursor.execute("UPDATE compare_calibration_experiments SET test_end=test_end+7")
        finally:
            cursor.execute("RESET ROLE")


def test_experiment_is_registered_once_with_four_plus_four_weeks(database, forecast):
    connection, _ = database
    row, _, payload = forecast
    assert freeze(connection, row, payload)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT development_start > (created_at AT TIME ZONE 'UTC')::DATE,
                   extract(isodow FROM development_start), train_end-development_start,
                   test_start-development_start, test_end-development_start, policy
            FROM compare_calibration_experiments WHERE model_signature=%s
        """, (payload["modelSignature"],))
        future, weekday, train_days, test_start, test_end, policy = cursor.fetchone()
        assert (future, weekday, train_days, test_start, test_end) == (True, 1, 27, 28, 55)
        assert policy["minimum_games"] == 1000
        assert policy["minimum_events"] == 20
        assert policy["temperatures"] == [.5, .75, 1, 1.25, 1.5, 2]
        with pytest.raises(psycopg2.Error, match="immutable"):
            cursor.execute("UPDATE compare_calibration_experiments SET test_end=test_end+7")
