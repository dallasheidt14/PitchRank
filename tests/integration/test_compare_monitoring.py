"""Execute monitoring guards, server clocks, immutability and source checks in PostgreSQL."""

import json
from copy import deepcopy

import pytest

from tests.integration.test_prospective_ledger import database, forecast, freeze  # noqa: F401

psycopg2 = pytest.importorskip("psycopg2")


@pytest.fixture
def monitor(database, forecast):
    connection, _ = database
    row, game, baseline = forecast
    assert freeze(connection, row, baseline)
    definition = {
        "kind": "compare_live_sos_monitoring",
        "schema_version": 1,
        "model_version": "live-test",
        "model_signature": "a" * 64,
        "algorithm_hash": "b" * 64,
        "research_hash": "c" * 64,
        "code_revision": "d" * 40,
        "multipliers": [0, 0.5, 1, 1.5],
        "production_promotion": False,
    }
    with connection.cursor() as cursor:
        cursor.execute("SELECT register_compare_monitor(%s)", (json.dumps(definition),))
        signature = cursor.fetchone()[0]
        cursor.execute("SELECT home_team_master_id,away_team_master_id FROM games WHERE id=%s", (game,))
        home, away = map(str, cursor.fetchone())
        cursor.execute("SELECT compare_monitor_clock()")
        clock = cursor.fetchone()[0]
    prediction = {
        "winProbabilityA": 0.6,
        "drawProbability": 0.2,
        "winProbabilityB": 0.2,
        "blowout4PlusProbability": 0.1,
        "expectedMargin": 1.0,
        "expectedScore": {"teamA": 2, "teamB": 1},
    }
    payload = {
        "model_signature": "a" * 64,
        "code_revision": "d" * 40,
        "reference_time": clock,
        "receipt": {"algorithm_hash": "b" * 64, "research_source_sha256": "c" * 64, "aa_parity": True},
        "context": {
            "predictorVersion": "live-test",
            "teamAInput": {"team_id_master": home},
            "teamBInput": {"team_id_master": away},
            "frozenEvidence": {"games": []},
            "calibration": {key: {} for key in ("ageGroups", "probability", "margin", "outcome", "confidence")},
        },
        "prediction": prediction,
        "variants": {str(a): deepcopy(prediction) for a in (0, 0.5, 1, 1.5)},
    }
    return connection, row, game, signature, payload


def capture(monitor, payload=None):
    connection, row, _, signature, original = monitor
    with connection.cursor() as cursor:
        cursor.execute("SELECT freeze_compare_monitor(%s,%s,%s)", (row, signature, json.dumps(payload or original)))
        return cursor.fetchone()[0]


def test_monitor_capture_is_immutable_and_retry_is_harmless(monitor):
    assert capture(monitor)
    assert capture(monitor, {"changed": True}) is False
    connection, row, _, signature, _ = monitor
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT captured_at <= clock_timestamp() FROM compare_monitoring_forecasts WHERE baseline_forecast_id=%s",
            (row,),
        )
        assert cursor.fetchone()[0]
        with pytest.raises(psycopg2.Error, match="immutable"):
            cursor.execute("DELETE FROM compare_monitoring_forecasts WHERE baseline_forecast_id=%s", (row,))
        cursor.execute("SELECT compare_monitor_review(%s)", (signature,))
        result = cursor.fetchone()[0]
        assert result["open"] is False
        assert result["payload"] is None and result["fixture"] is None


@pytest.mark.parametrize(
    "change",
    [
        "home_score=0",
        "away_score=0",
        "is_excluded=TRUE",
        "game_date=game_date+1",
        "source_url='https://changed.test'",
        "home_team_master_id=gen_random_uuid()",
        "provider_id=gen_random_uuid()",
    ],
)
def test_each_source_change_prevents_freeze(monitor, change):
    with monitor[0].cursor() as cursor:
        cursor.execute("UPDATE games SET " + change + " WHERE id=%s", (monitor[2],))
    with pytest.raises(psycopg2.Error, match="Source fixture changed"):
        capture(monitor)


@pytest.mark.parametrize("arm", ["0", "0.5", "1", "1.5"])
def test_missing_arm_risk_rejected(monitor, arm):
    payload = deepcopy(monitor[4])
    payload["variants"][arm].pop("blowout4PlusProbability")
    with pytest.raises(psycopg2.Error):
        capture(monitor, payload)


def test_public_roles_and_unqualified_selection_are_refused(monitor):
    connection, _, _, signature, _ = monitor
    with connection.cursor() as cursor:
        for role in ("anon", "authenticated"):
            cursor.execute("SET ROLE " + role)
            try:
                with pytest.raises(psycopg2.Error, match="permission denied"):
                    cursor.execute("SELECT compare_monitor_review(%s)", (signature,))
                with pytest.raises(psycopg2.Error, match="permission denied"):
                    cursor.execute("SELECT * FROM compare_monitoring_forecasts")
            finally:
                cursor.execute("RESET ROLE")
        with pytest.raises(psycopg2.Error, match="Insufficient or sealed"):
            cursor.execute("SELECT register_compare_sos_selection(%s,.5,'{}')", (signature,))


def test_form_challenger_confirmation_seals_other_model_results(database):
    connection, _ = database
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT day::date FROM generate_series(
                (now() AT TIME ZONE 'UTC')::date-1,(now() AT TIME ZONE 'UTC')::date-26,
                interval '-1 day') AS day WHERE compare_monitor_results_open(day::date) LIMIT 1""")
            day = cursor.fetchone()[0]
            cursor.execute(
                """INSERT INTO compare_challenger_manifests VALUES (
                %s,'{}',clock_timestamp(),%s,%s+27)""",
                ("e" * 64, day, day),
            )
            cursor.execute("SELECT compare_monitor_results_open(%s)", (day,))
            assert cursor.fetchone()[0] is False
    finally:
        connection.rollback()
        connection.autocommit = True


@pytest.mark.parametrize(
    "change",
    [
        "game_date=game_date+1",
        "home_team_master_id=gen_random_uuid()",
        "away_team_master_id=gen_random_uuid()",
        "provider_id=gen_random_uuid()",
        "source_url='https://changed.test'",
    ],
)
def test_audit_rechecks_each_identity_field_under_lock(monitor, change):
    assert capture(monitor)
    connection, row, game, signature, _ = monitor
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            # Override only in this rolled-back transaction to exercise a mature forecast.
            cursor.execute("""CREATE OR REPLACE FUNCTION compare_monitor_results_open(p_day date)
                RETURNS boolean LANGUAGE sql AS 'SELECT true'""")
            cursor.execute("SELECT to_jsonb(g) FROM games g WHERE id=%s", (game,))
            original = cursor.fetchone()[0]
            cursor.execute("UPDATE games SET " + change + " WHERE id=%s", (game,))
            with pytest.raises(psycopg2.Error, match="Result changed during review"):
                cursor.execute(
                    "SELECT audit_compare_monitor_result(%s,%s,'source_game_id',%s)",
                    (row, signature, json.dumps(original)),
                )
    finally:
        connection.rollback()
        connection.autocommit = True


def test_preview_masks_open_fixture_payloads_at_the_server(monitor):
    assert capture(monitor)
    connection, _, _, signature, _ = monitor
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("""CREATE OR REPLACE FUNCTION compare_monitor_results_open(p_day date)
                RETURNS boolean LANGUAGE sql AS 'SELECT true'""")
            cursor.execute("SELECT compare_monitor_review(%s,0,true)", (signature,))
            preview = cursor.fetchone()[0]
            assert preview["open"] is True
            assert preview["fixture"] is None and preview["payload"] is None
            cursor.execute("SELECT compare_monitor_review(%s,0,false)", (signature,))
            assert cursor.fetchone()[0]["payload"] is not None
    finally:
        connection.rollback()
        connection.autocommit = True
