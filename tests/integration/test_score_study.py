"""Run score-study deadlines, roles, invariants and sealed-result behavior in PostgreSQL."""

from copy import deepcopy
from datetime import timedelta

import pytest

from src.predictions.score_study import score_payload, serialized
from tests.integration.test_compare_monitoring import capture, monitor  # noqa: F401
from tests.integration.test_prospective_ledger import database, forecast  # noqa: F401
from tests.score_study_fixtures import baseline, definition, sample_artifact

psycopg2 = pytest.importorskip("psycopg2")


@pytest.fixture
def score_pair(database, forecast, request):
    connection, _ = database
    row, game, _ = forecast
    with connection.cursor() as cursor:
        cursor.execute("SELECT (date_trunc('week',clock_timestamp() AT TIME ZONE 'UTC')+interval '1 week')::date")
        start = cursor.fetchone()[0]
        cursor.execute("UPDATE games SET game_date=%s WHERE id=%s", (start, game))
        cursor.execute("UPDATE prospective_match_predictions SET game_date=%s WHERE id=%s", (start, row))
    parent = request.getfixturevalue("monitor")
    payload = parent[4]
    prediction = baseline()
    payload["prediction"] = prediction
    payload["variants"] = {str(a): deepcopy(prediction) for a in (0, 0.5, 1, 1.5)}
    for team in ("teamAInput", "teamBInput"):
        payload["context"][team].update(age=12, gender="M")
    fit, _, _ = sample_artifact()
    payload["context"]["frozenEvidence"]["aliases"] = {
        payload["context"]["teamAInput"]["team_id_master"]: "a",
        payload["context"]["teamBInput"]["team_id_master"]: "b"}
    assert capture(parent, payload)
    manifest = definition(start, parent[3], "a"*64)
    with connection.cursor() as cursor:
        cursor.execute("SELECT register_compare_score_study(%s)", (serialized(manifest),))
        signature = cursor.fetchone()[0]
        cursor.execute("SELECT compare_score_capture_queue(%s)", (signature,))
        queued = [r[0] for r in cursor.fetchall()]
    queued = next(r for r in queued if r["baseline_forecast_id"] == str(row))
    p = score_payload(queued, manifest, fit, signature)
    return connection, signature, row, game, manifest, p


def freeze(pair, payload=None):
    connection, signature, row, _, _, original = pair
    with connection.cursor() as cursor:
        cursor.execute("SELECT freeze_compare_score_forecast(%s,%s,%s)",
                       (signature, row, serialized(original if payload is None else payload)))
        return cursor.fetchone()[0]


def test_real_pair_is_immutable_repeat_capture_is_safe_and_review_is_sealed(score_pair):
    assert freeze(score_pair)
    assert freeze(score_pair, {"changed": True}) is False
    connection, signature, row, _, _, payload = score_pair
    with connection.cursor() as cursor:
        cursor.execute("SELECT payload,captured_at<=clock_timestamp() FROM compare_score_forecasts WHERE study_signature=%s AND baseline_forecast_id=%s", (signature, row))
        saved, timestamp_valid = cursor.fetchone()
        assert saved == payload and timestamp_valid
        with pytest.raises(psycopg2.Error, match="immutable"):
            cursor.execute("DELETE FROM compare_score_forecasts WHERE study_signature=%s", (signature,))
        cursor.execute("SELECT compare_score_review(%s,NULL,500,false)", (signature,))
        result = cursor.fetchone()[0]
        assert result["open"] is False
        assert "result" not in result and "payload" not in result
        cursor.execute("SELECT compare_score_capture_queue(%s)", (signature,))
        assert not any(r[0]["baseline_forecast_id"] == str(row) for r in cursor.fetchall())


@pytest.mark.parametrize("change", ["home_score=0", "away_score=0", "is_excluded=true", "game_date=game_date+1",
                                    "provider_id=gen_random_uuid()", "source_url='https://changed.test'",
                                    "home_team_master_id=gen_random_uuid()", "away_team_master_id=gen_random_uuid()"])
def test_each_source_change_independently_prevents_score_capture(score_pair, change):
    with score_pair[0].cursor() as cursor:
        cursor.execute("UPDATE games SET " + change + " WHERE id=%s", (score_pair[3],))
    with pytest.raises(psycopg2.Error, match="Source fixture changed"):
        freeze(score_pair)


@pytest.mark.parametrize("field", ["winProbabilityA", "drawProbability", "winProbabilityB", "predictedWinner",
                                   "blowout4PlusProbability"])
def test_score_changes_cannot_change_outcomes_or_protected_risk(score_pair, field):
    p = deepcopy(score_pair[5])
    arm = p["candidates"]["tail_guard_full"]["prediction"]
    arm[field] = "team_b" if field == "predictedWinner" else arm[field] + 0.01
    with pytest.raises(psycopg2.Error):
        freeze(score_pair, p)


def test_unqualified_roles_cannot_write_or_read_private_studies(score_pair):
    with score_pair[0].cursor() as cursor:
        for role in ("anon", "authenticated"):
            cursor.execute("SET ROLE " + role)
            try:
                with pytest.raises(psycopg2.Error, match="permission denied"):
                    cursor.execute("SELECT compare_score_review(%s)", (score_pair[1],))
                with pytest.raises(psycopg2.Error, match="permission denied"):
                    cursor.execute("SELECT * FROM compare_score_forecasts")
            finally:
                cursor.execute("RESET ROLE")
        cursor.execute("SET ROLE service_role")
        try:
            with pytest.raises(psycopg2.Error, match="permission denied"):
                cursor.execute("DELETE FROM compare_score_studies")
        finally:
            cursor.execute("RESET ROLE")


@pytest.mark.parametrize("change", ["minimum", "window", "review", "training", "baseline"])
def test_server_refuses_changed_registration_rules(score_pair, change):
    m = deepcopy(score_pair[4])
    if change == "minimum":
        m["policy"]["minimum_pairs"] = 20
    elif change == "window":
        m["capture_end"] = (date_from(m["capture_end"]) + timedelta(days=1)).isoformat()
    elif change == "review":
        m["review_not_before"] = m["capture_end"]
    elif change == "training":
        m["fit_receipt"]["latest_training_game"] = m["capture_start"]
    else:
        m["baseline_model_signature"] = "f"*64
    with score_pair[0].cursor() as cursor, pytest.raises(psycopg2.Error):
        cursor.execute("SELECT register_compare_score_study(%s)", (serialized(m),))


def test_sealed_review_does_not_even_require_access_to_games(score_pair):
    assert freeze(score_pair)
    connection = score_pair[0]
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE games RENAME TO temporarily_hidden_games")
            cursor.execute("SELECT compare_score_review(%s,NULL,500,false)", (score_pair[1],))
            assert cursor.fetchone()[0]["open"] is False
    finally:
        connection.rollback()
        connection.autocommit = True


def test_released_preview_hides_results_and_corrected_source_day_never_leaks(score_pair):
    assert freeze(score_pair)
    connection = score_pair[0]
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("""CREATE OR REPLACE FUNCTION public.compare_score_review_open(p_signature text)
                RETURNS boolean LANGUAGE sql AS 'SELECT true'""")
            cursor.execute("SELECT compare_score_review(%s,NULL,500,true)", (score_pair[1],))
            preview = cursor.fetchone()[0]
            assert preview["open"] and "result" not in preview and "payload" not in preview
            cursor.execute("UPDATE games SET game_date=game_date+1,home_score=3,away_score=2 WHERE id=%s",
                           (score_pair[3],))
            cursor.execute("SELECT compare_score_review(%s,NULL,500,false)", (score_pair[1],))
            rows = [row[0] for row in cursor.fetchall()]
            assert next(row for row in rows if row["baseline_forecast_id"] == str(score_pair[2]))["result"] is None
    finally:
        connection.rollback()
        connection.autocommit = True


@pytest.mark.parametrize("change", ["parent_hash", "model", "source", "missing_risk", "missing_goals", "fallback"])
def test_provenance_and_complete_outputs_are_required_by_server(score_pair, change):
    p = deepcopy(score_pair[5])
    if change == "parent_hash":
        p["baseline_payload_sha256"] = "f"*64
    elif change == "model":
        p["model_sha256"] = "f"*64
    elif change == "source":
        p["code_revision"] = "f"*40
    elif change == "missing_risk":
        p["candidates"]["blend_25"]["prediction"].pop("blowout4PlusProbability")
    elif change == "missing_goals":
        p["candidates"]["blend_25"]["prediction"].pop("expectedGoals")
    else:
        p["eligibility"] = "unseen_team_fallback"
        p["learned_rates"] = None
    with pytest.raises(psycopg2.Error):
        freeze(score_pair, p)


def date_from(value):
    from datetime import date
    return date.fromisoformat(value)


def test_final_server_clock_recheck_rejects_crossing_into_match_day(score_pair):
    connection = score_pair[0]
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT game_date::text FROM games WHERE id=%s", (score_pair[3],))
            midnight = cursor.fetchone()[0]+"T00:00:00+00:00"
            cursor.execute("CREATE TEMP SEQUENCE score_clock_calls")
            cursor.execute("""CREATE FUNCTION pg_temp.score_clock() RETURNS timestamptz LANGUAGE sql VOLATILE AS $$
                SELECT CASE WHEN nextval('pg_temp.score_clock_calls')=1
                  THEN %s::timestamptz-interval '1 second' ELSE %s::timestamptz END $$""", (midnight, midnight))
            cursor.execute("SELECT pg_get_functiondef('public.freeze_compare_score_forecast(text,uuid,text)'::regprocedure)")
            actual_definition = cursor.fetchone()[0]
            # Change only the clock source in this rolled-back test, leaving the production guard body intact.
            cursor.execute(actual_definition.replace("clock_timestamp()", "pg_temp.score_clock()"))
            cursor.execute("SAVEPOINT before_late_capture")
            with pytest.raises(psycopg2.Error, match="Match day began"):
                freeze(score_pair)
            cursor.execute("ROLLBACK TO SAVEPOINT before_late_capture")
            cursor.execute("SELECT count(*) FROM compare_score_forecasts WHERE study_signature=%s AND baseline_forecast_id=%s",
                           (score_pair[1], score_pair[2]))
            assert cursor.fetchone()[0] == 0
    finally:
        connection.rollback()
        connection.autocommit = True
