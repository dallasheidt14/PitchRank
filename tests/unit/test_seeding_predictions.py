from __future__ import annotations

import copy
import json
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from src.tournaments import seeding_predictions as bridge

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"
COHORTS = {"u14:Male": {"6": A, "7": B}, "u12:Female": {"8": A}}


def _result():
    forward = {
        "entrant_a": "6",
        "entrant_b": "7",
        "predicted_winner": "team_a",
        "win_probability_a": 0.85,
        "win_probability_b": 0.1,
        "draw_probability": 0.05,
        "expected_score": {"teamA": 4, "teamB": 0},
        "expected_margin": 3.8,
        "expected_absolute_goal_difference": 3.9,
        "blowout_4plus_probability": 0.6,
        "confidence": "medium",
        "confidence_score": 0.6,
    }
    reverse = {
        **forward,
        "entrant_a": "7",
        "entrant_b": "6",
        "predicted_winner": "team_b",
        "win_probability_a": 0.1,
        "win_probability_b": 0.85,
        "expected_score": {"teamA": 0, "teamB": 4},
        "expected_margin": -3.8,
    }
    return {
        "schema_version": 1,
        "generated_at": "2026-09-15T12:00:00Z",
        "ratings_as_of": "2026-09-14T01:00:00Z",
        "cohorts": {
            "u14:Male": {
                "teams": {
                    "6": {"team_id_master": A, "prediction_game_count": 20, "ratings_as_of": "2026-09-14T01:00:00Z"},
                    "7": {"team_id_master": B, "prediction_game_count": 20, "ratings_as_of": "2026-09-14T01:00:00Z"},
                },
                "unavailable": {},
                "predictions": [forward, reverse],
            },
            "u12:Female": {
                "teams": {},
                "unavailable": {"8": "No published rank"},
                "predictions": [],
            },
        },
    }


def _runtime(monkeypatch, tmp_path, result=None, returncode=0):
    cli = tmp_path / "tsx.mjs"
    cli.touch()
    monkeypatch.setattr(bridge, "_TSX_CLI", cli)
    monkeypatch.setattr(bridge.shutil, "which", lambda _: "node")
    calls = []

    def run(command, **kwargs):
        payload = Path(command[-2]).read_text(encoding="utf-8")
        calls.append((command, kwargs, payload))
        Path(command[-1]).write_text(json.dumps(_result() if result is None else result), encoding="utf-8")
        return SimpleNamespace(returncode=returncode, stdout="", stderr="private-secret https://private-db.example")

    monkeypatch.setattr(bridge.subprocess, "run", run)
    return calls


def test_loads_both_orientations_and_keeps_credentials_out_of_files_commands_and_errors(monkeypatch, tmp_path):
    calls = _runtime(monkeypatch, tmp_path)
    batch = bridge.load_seeding_predictions(
        COHORTS, supabase_url="https://private-db.example", supabase_key="private-secret"
    )

    assert batch.predictions["u14:Male"][("6", "7")].expected_margin == 3.8
    assert batch.predictions["u14:Male"][("7", "6")].expected_margin == -3.8
    assert batch.predictions["u14:Male"][("6", "7")].confidence == "medium"
    assert batch.unavailable["u12:Female"] == {"8": "No published rank"}
    assert batch.teams["u14:Male"]["6"]["prediction_game_count"] == 20
    assert len(batch.predictor_sha256) == 64
    command, kwargs, payload = calls[0]
    assert "private-secret" not in " ".join(command) + payload + repr(batch)
    assert "https://private-db.example" not in " ".join(command) + payload
    assert kwargs["env"]["SUPABASE_KEY"] == "private-secret"
    assert kwargs["env"]["SUPABASE_URL"] == "https://private-db.example"
    assert command[2:4] == ["-r", str(bridge._SHIM)]
    assert kwargs["cwd"] == bridge._FRONTEND_DIR
    assert kwargs["timeout"] == 300


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda result: result["cohorts"].pop("u12:Female"), "cohort coverage"),
        (lambda result: result["cohorts"]["u14:Male"]["teams"].pop("6"), "entrant coverage"),
        (lambda result: result["cohorts"]["u14:Male"]["predictions"].pop(), "matchup coverage"),
        (
            lambda result: result["cohorts"]["u14:Male"]["predictions"].append(
                copy.deepcopy(result["cohorts"]["u14:Male"]["predictions"][0])
            ),
            "duplicate",
        ),
        (
            lambda result: result["cohorts"]["u14:Male"]["predictions"][0].update(
                expected_margin=float("nan")
            ),
            "non-finite",
        ),
        (
            lambda result: result["cohorts"]["u14:Male"]["predictions"][0].update(
                blowout_4plus_probability=1.1
            ),
            "invalid",
        ),
        (lambda result: result["cohorts"]["u14:Male"]["predictions"][0].update(win_probability_a=0.7), "probabilities"),
        (lambda result: result["cohorts"]["u14:Male"]["predictions"][1].update(expected_margin=3.8), "orientations"),
        (
            lambda result: result["cohorts"]["u14:Male"]["predictions"][0].update(
                expected_score={"teamA": 2.4, "teamB": 0}
            ),
            "score",
        ),
        (lambda result: result["cohorts"]["u14:Male"]["teams"]["6"].update(prediction_game_count=-1), "game count"),
    ],
)
def test_rejects_incomplete_or_invalid_predictor_output(mutate, match):
    result = _result()
    mutate(result)
    with pytest.raises(ValueError, match=match):
        bridge._parse_batch(result, COHORTS, "digest")


def test_zero_recent_games_is_valid_seeding_evidence():
    result = _result()
    result["cohorts"]["u14:Male"]["teams"]["6"]["prediction_game_count"] = 0

    batch = bridge._parse_batch(result, COHORTS, "digest")

    assert batch.teams["u14:Male"]["6"]["prediction_game_count"] == 0


def test_runtime_failure_never_returns_an_approximate_prediction_or_sensitive_details(monkeypatch, tmp_path):
    _runtime(monkeypatch, tmp_path, returncode=1)
    with pytest.raises(RuntimeError, match="prediction failed") as failure:
        bridge.load_seeding_predictions(
            COHORTS, supabase_url="https://private-db.example", supabase_key="private-secret"
        )
    assert "private-secret" not in str(failure.value)
    assert "private-db.example" not in str(failure.value)


def test_timeout_fails_the_batch(monkeypatch, tmp_path):
    _runtime(monkeypatch, tmp_path)

    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(bridge.subprocess, "run", timed_out)
    with pytest.raises(RuntimeError, match="timed out"):
        bridge.load_seeding_predictions(COHORTS, supabase_url="https://db.example", supabase_key="key")


def test_unresolved_ids_do_not_reach_database_queries(monkeypatch):
    monkeypatch.setattr(bridge.subprocess, "run", lambda *args, **kwargs: pytest.fail("must validate before running"))
    with pytest.raises(ValueError, match="UUIDs"):
        bridge.load_seeding_predictions({"u14:Male": {"6": "not-a-uuid"}}, supabase_url="url", supabase_key="key")


def test_requires_installed_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "_TSX_CLI", tmp_path / "missing.mjs")
    with pytest.raises(RuntimeError, match="npm ci"):
        bridge.load_seeding_predictions(COHORTS, supabase_url="url", supabase_key="key")


@pytest.mark.skipif(not bridge._TSX_CLI.is_file(), reason="Installed frontend runtime is required")
def test_real_cli_uses_the_shared_compare_service_against_local_read_only_http_fixture():
    """Exercise Python -> tsx/shim -> actual Supabase client -> Compare -> parser."""
    today = datetime.now(timezone.utc).date().isoformat()
    tables = {
        "teams": [
            {"team_id_master": team_id, "team_name": name, "age_group": "u14", "gender": "Male", "state": "AZ"}
            for team_id, name in [(A, "Synthetic Alpha"), (B, "Synthetic Beta")]
        ],
        "rankings_full": [
            {
                "team_id": team_id,
                "age_group": "u14",
                "gender": "Male",
                "rank_in_cohort_final": 6 + index,
                "power_score_final": 0.55 - index * 0.02,
                "glicko_rating": 1800 - index * 450,
                "glicko_rd": 40,
                "sos_norm": 0.6,
                "off_norm": 0.8 - index * 0.4,
                "def_norm": 0.8 - index * 0.4,
                "games_played": 20,
                "wins": 14,
                "draws": 2,
                "losses": 4,
                "last_calculated": f"{today}T01:00:00Z",
                "status": "Active",
            }
            for index, team_id in enumerate([A, B])
        ],
        "games": [
            {
                "id": f"synthetic-game-{index}",
                "game_date": today,
                "home_team_master_id": A,
                "away_team_master_id": B,
                "home_score": 5,
                "away_score": 0,
                "is_excluded": False,
            }
            for index in range(3)
        ],
    }
    reads = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            table = parsed.path.removeprefix("/rest/v1/")
            query = parse_qs(parsed.query)
            reads.append((table, query))
            rows = copy.deepcopy(tables.get(table, []))
            for field, expressions in query.items():
                expression = expressions[0]
                if expression.startswith("eq."):
                    value = expression[3:]
                    rows = [row for row in rows if str(row.get(field)).lower() == value.lower()]
                elif expression == "not.is.null":
                    rows = [row for row in rows if row.get(field) is not None]
                elif expression.startswith("gte."):
                    rows = [row for row in rows if str(row.get(field, "")) >= expression[4:]]
                elif field == "or":
                    # Both fixture teams are requested. Refuse an unrelated or absent ID list.
                    assert A in expression and B in expression
                elif field not in {"select", "order", "offset", "limit"}:
                    raise AssertionError(f"Unsupported fixture filter: {field}")
            for clause in reversed(query.get("order", [""])[0].split(",")):
                if clause:
                    field, direction, *_ = clause.split(".")
                    rows.sort(key=lambda row: str(row.get(field, "")), reverse=direction == "desc")
            offset = int(query.get("offset", ["0"])[0])
            maximum = int(query.get("limit", ["1000"])[0])
            rows = rows[offset : offset + maximum]
            body = json.dumps(rows).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class FixtureServer(ThreadingHTTPServer):
        request_queue_size = 32

    server = FixtureServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        batch = bridge.load_seeding_predictions(
            {"u14|Male": {"6": A, "7": B}},
            supabase_url=f"http://127.0.0.1:{server.server_port}",
            supabase_key="synthetic-test-key",
            timeout_seconds=30,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    forward = batch.predictions["u14|Male"][("6", "7")]
    reverse = batch.predictions["u14|Male"][("7", "6")]
    assert forward.expected_margin > 2
    assert forward.blowout_4plus_probability > 0.2
    assert reverse.expected_margin == -forward.expected_margin
    assert batch.teams["u14|Male"]["6"]["prediction_game_count"] == 3
    assert batch.teams["u14|Male"]["6"]["ratings_as_of"] == f"{today}T01:00:00Z"
    assert len([item for item in reads if item[0] == "teams"]) == 2
    assert len([item for item in reads if item[0] == "games"]) == 1
