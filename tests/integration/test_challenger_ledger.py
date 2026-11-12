"""Run the real private paired-forecast migration, including competing workers and role grants."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.predictions.challenger_capture import canonical_json
from src.predictions.form_policy import PINNED_MODEL_SIGNATURE, PINNED_REVISION
from tests.integration.test_prospective_ledger import database, forecast, freeze  # noqa: F401
from tests.challenger_fixtures import manifest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import sql
from psycopg2.extras import Json


def register(connection, definition):
    with connection.cursor() as cursor:
        cursor.execute("SELECT register_compare_challenger(%s)", (canonical_json(definition),))
        return cursor.fetchone()[0]


@pytest.fixture
def pair(database, forecast):
    connection, _ = database
    row, game_id, baseline = forecast
    signature = register(connection, manifest())
    with connection.cursor() as cursor:
        cursor.execute("SELECT confirmation_start FROM compare_challenger_manifests WHERE candidate_signature=%s",
                       (signature,))
        first = cursor.fetchone()[0]
        cursor.execute("UPDATE games SET game_date=%s WHERE id=%s", (first, game_id))
        cursor.execute("UPDATE prospective_match_predictions SET game_date=%s WHERE id=%s", (first, row))
        cursor.execute("SELECT home_team_master_id,away_team_master_id FROM games WHERE id=%s", (game_id,))
        home, away = [str(value) for value in cursor.fetchone()]
    prediction = {"winProbabilityA": .6, "drawProbability": .2, "winProbabilityB": .2,
                  "expectedMargin": 1., "expectedScore": {"teamA": 2, "teamB": 1},
                  "blowout4PlusProbability": .1, "predictedWinner": "team_a_win"}
    baseline["modelSignature"] = PINNED_MODEL_SIGNATURE
    baseline["shadowContext"].update(teamAInput={"team_id_master": home}, teamBInput={"team_id_master": away})
    assert freeze(connection, row, baseline)
    payload = {"frozen_inputs": {"baseline_prediction": baseline, "case": {
        "fixture": {"source_game_id": game_id, "game_date": first.isoformat()},
        "teamA": baseline["shadowContext"]["teamAInput"], "teamB": baseline["shadowContext"]["teamBInput"],
        "games": []}}, "prediction": prediction, "provenance": {"candidate_signature": signature,
            "research_sources": manifest()["research_sources"], "aa_parity": True, "predictor_revision": PINNED_REVISION}}
    return row, game_id, signature, payload


def capture(connection, pair, payload=None):
    row, _, signature, original = pair
    with connection.cursor() as cursor:
        cursor.execute("SELECT freeze_compare_challenger(%s,%s,%s)",
                       (row, signature, canonical_json(original if payload is None else payload)))
        return cursor.fetchone()[0]


def test_registration_dates_are_server_fixed_and_idempotent(database):
    connection, _ = database
    signature = register(connection, manifest())
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM compare_challenger_manifests WHERE candidate_signature=%s", (signature,))
        before = cursor.fetchone()
    assert register(connection, manifest()) == signature
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM compare_challenger_manifests WHERE candidate_signature=%s", (signature,))
        after = cursor.fetchone()
        assert before == after
        registered, start, end = after[2:]
        registered_day = registered.astimezone(timezone.utc).date()
        assert start == registered_day + timedelta(days=7 - registered_day.weekday())
        assert (end - start).days == 27


def test_capture_is_separate_immutable_and_has_server_time(database, pair):
    connection, _ = database
    row, _, signature, _ = pair
    assert capture(connection, pair) is True
    assert capture(connection, pair, {"changed": True}) is False
    with connection.cursor() as cursor:
        cursor.execute("SELECT captured_at FROM compare_challenger_forecasts WHERE baseline_forecast_id=%s", (row,))
        assert abs((datetime.now(timezone.utc) - cursor.fetchone()[0]).total_seconds()) < 10
        for table in ("compare_challenger_forecasts", "compare_challenger_manifests"):
            with pytest.raises(psycopg2.Error, match="immutable"):
                cursor.execute(sql.SQL("UPDATE {} SET candidate_signature=candidate_signature WHERE candidate_signature=%s")
                               .format(sql.Identifier(table)), (signature,))
            with pytest.raises(psycopg2.Error, match="immutable"):
                cursor.execute(sql.SQL("DELETE FROM {} WHERE candidate_signature=%s").format(sql.Identifier(table)),
                               (signature,))
        cursor.execute("SELECT heuristic_prediction FROM prospective_match_predictions WHERE id=%s", (row,))
        assert cursor.fetchone()[0] == pair[3]["frozen_inputs"]["baseline_prediction"]


@pytest.mark.parametrize("field,value", [
    ("home_score", 0), ("away_score", 0), ("is_excluded", True),
    ("game_date", "2030-01-01"), ("source_url", "https://example.test/changed"),
    ("provider_id", "00000000-0000-0000-0000-000000000001"),
    ("home_team_master_id", "00000000-0000-0000-0000-000000000002"),
    ("away_team_master_id", "00000000-0000-0000-0000-000000000003"),
])
def test_each_source_change_blocks_capture(database, pair, field, value):
    connection, _ = database
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("UPDATE games SET {}=%s WHERE id=%s").format(sql.Identifier(field)), (value, pair[1]))
    with pytest.raises(psycopg2.Error, match="Source fixture changed"):
        capture(connection, pair)


@pytest.mark.parametrize("change", ["inputs", "signature", "code", "parity", "risk", "probabilities"])
def test_incomplete_or_mismatched_payload_is_rejected(database, pair, change):
    connection, _ = database
    payload = deepcopy(pair[3])
    if change == "inputs": payload["frozen_inputs"]["case"]["games"] = [{"future": True}]
    if change == "signature": payload["provenance"]["candidate_signature"] = "f" * 64
    if change == "code": payload["provenance"]["research_sources"] = {}
    if change == "parity": payload["provenance"]["aa_parity"] = False
    if change == "risk": payload["prediction"].pop("blowout4PlusProbability")
    if change == "probabilities": payload["prediction"]["winProbabilityA"] = .9
    with pytest.raises(psycopg2.Error): capture(connection, pair, payload)


def test_competing_workers_cannot_replace_forecasts(database, pair):
    _, parameters = database
    def worker(_):
        with psycopg2.connect(**parameters) as connection:
            return capture(connection, pair)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, range(2))) == [False, True]


def test_roles_and_missing_pair_counts(database, pair):
    connection, _ = database
    with connection.cursor() as cursor:
        cursor.execute("SELECT missing_challenger_forecasts FROM compare_challenger_pair_coverage WHERE candidate_signature=%s",
                       (pair[2],))
        assert sum(row[0] for row in cursor.fetchall()) > 0
        for role in ("anon", "authenticated"):
            cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            try:
                for table in ("compare_challenger_manifests", "compare_challenger_forecasts", "compare_challenger_pair_coverage"):
                    with pytest.raises(psycopg2.Error, match="permission denied"):
                        cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table)))
                with pytest.raises(psycopg2.Error, match="permission denied"): capture(connection, pair)
                with pytest.raises(psycopg2.Error, match="permission denied"): register(connection, manifest())
            finally: cursor.execute("RESET ROLE")
        cursor.execute("SET ROLE service_role")
        try:
            assert capture(connection, pair)
            with pytest.raises(psycopg2.Error, match="permission denied"):
                cursor.execute("UPDATE compare_challenger_forecasts SET captured_at=clock_timestamp()")
        finally: cursor.execute("RESET ROLE")


def test_server_refuses_same_day_capture_even_with_previously_frozen_inputs(database, pair):
    connection, _ = database
    payload = deepcopy(pair[3])
    with connection.cursor() as cursor:
        cursor.execute("SELECT confirmation_start,confirmation_end FROM compare_challenger_manifests "
                       "WHERE candidate_signature=%s", (pair[2],))
        original_window = cursor.fetchone()
        cursor.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")
        today = cursor.fetchone()[0]
        # Seed an elapsed fixture locally; production roles cannot rewrite either immutable record.
        cursor.execute("ALTER TABLE prospective_match_predictions DISABLE TRIGGER guard_prospective_forecast")
        cursor.execute("ALTER TABLE compare_challenger_manifests DISABLE TRIGGER guard_compare_challenger_manifest")
        try:
            cursor.execute("UPDATE prospective_match_predictions SET game_date=%s,heuristic_predicted_at=%s WHERE id=%s",
                           (today, today - timedelta(days=1), pair[0]))
            cursor.execute("UPDATE games SET game_date=%s WHERE id=%s", (today, pair[1]))
            cursor.execute("UPDATE compare_challenger_manifests SET confirmation_start=%s,confirmation_end=%s "
                           "WHERE candidate_signature=%s", (today, today + timedelta(days=27), pair[2]))
        finally:
            cursor.execute("ALTER TABLE prospective_match_predictions ENABLE TRIGGER guard_prospective_forecast")
            cursor.execute("ALTER TABLE compare_challenger_manifests ENABLE TRIGGER guard_compare_challenger_manifest")
    payload["frozen_inputs"]["case"]["fixture"]["game_date"] = today.isoformat()
    try:
        with pytest.raises(psycopg2.Error, match="prematch paired capture"):
            capture(connection, pair, payload)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE compare_challenger_manifests DISABLE TRIGGER guard_compare_challenger_manifest")
            try:
                cursor.execute("UPDATE compare_challenger_manifests SET confirmation_start=%s,confirmation_end=%s "
                               "WHERE candidate_signature=%s", (*original_window, pair[2]))
            finally:
                cursor.execute("ALTER TABLE compare_challenger_manifests ENABLE TRIGGER guard_compare_challenger_manifest")


def test_migration_reapplication_preserves_completed_records(database, pair):
    connection, _ = database
    assert capture(connection, pair)
    migration = Path(__file__).resolve().parents[2] / "supabase/migrations/20261113000000_compare_challenger_forecasts.sql"
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_jsonb(c) FROM compare_challenger_forecasts c WHERE baseline_forecast_id=%s", (pair[0],))
        before = cursor.fetchone()[0]
        cursor.execute(migration.read_text(encoding="utf-8"))
        cursor.execute("SELECT to_jsonb(c) FROM compare_challenger_forecasts c WHERE baseline_forecast_id=%s", (pair[0],))
        assert cursor.fetchone()[0] == before
