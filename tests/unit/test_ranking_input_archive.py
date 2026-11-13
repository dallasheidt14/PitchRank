import asyncio
import gzip
import hashlib
import io
import json
import pickle
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pandas as pd
import pytest
from postgrest import SyncPostgrestClient
from postgrest.exceptions import APIError

from src.rankings.input_archive import ACTIVE_ARCHIVE, InputArchive

ROOT = Path(__file__).resolve().parents[2]
STATEMENT_TIMEOUT = {
    "code": "57014",
    "message": "canceling statement due to statement timeout",
    "details": None,
    "hint": None,
}


@pytest.fixture
def archive(tmp_path):
    return InputArchive(tmp_path / "capture", ROOT, {"database_writes_enabled": False})


def read_object(archive, reference):
    data = gzip.decompress((archive.directory / reference["object"]).read_bytes())
    assert hashlib.sha256(data).hexdigest() == reference["sha256"]
    return data


def explainability_row(game: str) -> dict:
    row = dict(id=game, game_id="provider-" + game, team_id="a", opp_id="b", game_date="2026-11-01", gf=2, ga=1)
    row.update({name: 0.5 for name in (
        "team_mu", "team_sigma", "opp_mu", "opp_sigma", "expected_outcome", "actual_outcome",
        "outcome_surprise", "g_factor", "recency_weight", "rating_contribution", "off_residual", "def_residual",
    )})
    return row


def test_actual_postgrest_requests_and_responses_are_frozen_only_when_executed(archive):
    requests = []

    def respond(request):
        requests.append((request.method, dict(request.url.params), request.content))
        rows = [{"id": "old", "home_score": 2}, {"id": "new", "home_score": 3}]
        if request.method == "GET":
            assert request.url.params["select"] == "id,home_score"
            rows = rows[int(request.url.params.get("offset", 0)) :][:1]
        else:
            rows = json.loads(request.content)
        return httpx.Response(200, json=rows, headers={"content-range": "0-0/2"})

    http = httpx.Client(transport=httpx.MockTransport(respond), headers={"apikey": "SECRET-TEST-KEY"})
    client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
    wrapped = archive.wrap(SimpleNamespace(table=client.from_))
    query = wrapped.table("games").select("id,home_score").order("id")
    assert not archive.manifest["queries"] and not requests
    first = query.range(0, 0).execute()
    second = wrapped.table("games").select("id,home_score").order("id").range(1, 1).execute()
    assert first.data == [{"id": "old", "home_score": 2}]
    assert second.data == [{"id": "new", "home_score": 3}]
    written = (
        wrapped.table("prediction_feature_history")
        .upsert(
            [{"team_id": "a", "power_score_final": 0.7}], on_conflict="team_id,snapshot_date", ignore_duplicates=True
        )
        .execute()
    )
    assert written.data == [{"team_id": "a", "power_score_final": 0.7}]
    assert len(requests) == len(archive.manifest["queries"]) == 3
    assert archive.manifest["queries"][2]["operation"] == "upsert"
    assert json.loads(read_object(archive, archive.manifest["queries"][0]["response"])) == first.data
    assert json.loads(read_object(archive, archive.manifest["queries"][1]["response"])) == second.data
    assert all(
        b"SECRET-TEST-KEY" not in gzip.decompress(p.read_bytes()) for p in (archive.directory / "objects").iterdir()
    )
    archive.finish(True)
    assert json.loads((archive.directory / "manifest.json").read_text())["status"] == "complete"
    http.close()


def test_archive_failure_does_not_change_a_database_read_and_cannot_be_published_as_complete(archive, monkeypatch):
    response = SimpleNamespace(data=[{"id": "a"}])
    query = SimpleNamespace(execute=lambda: response)
    client = archive.wrap(SimpleNamespace(table=lambda name: query))
    monkeypatch.setattr(archive, "blob", lambda *args: (_ for _ in ()).throw(OSError("full disk")))
    assert client.table("games").execute() is response
    with pytest.raises(RuntimeError, match="input archive failed"):
        archive.finish(True)
    assert json.loads((archive.directory / "manifest.json").read_text())["status"] == "failed"


def test_failed_later_merge_page_cannot_leave_a_publishable_partial_archive(archive):
    from src.rankings.archive_storage import verify_archive
    from src.utils.merge_resolver import MergeResolver

    def respond(request):
        if request.url.params.get("offset", "0") == "0":
            return httpx.Response(200, json=[
                {"deprecated_team_id": str(i), "canonical_team_id": "canonical"} for i in range(1000)
            ])
        return httpx.Response(500, json={"code": "XX000", "message": "fixture failure"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        resolver = MergeResolver(archive.wrap(SimpleNamespace(table=client.from_)))
        resolver.load_merge_map()
    assert resolver.version == "error" and not resolver.has_merges
    failed = archive.manifest["failed_queries"]
    assert len(archive.manifest["queries"]) == 1 and [query["error_type"] for query in failed] == ["APIError"]
    assert ["range", [1000, 1999], {}] in json.loads(read_object(archive, failed[0]["request"]))
    with pytest.raises(RuntimeError, match="query_execution:APIError"):
        archive.finish(True)
    with pytest.raises(ValueError, match="complete, error-free"):
        verify_archive(archive.directory)


def test_games_page_retried_after_a_statement_timeout_leaves_a_complete_archive(archive):
    from src.rankings.data_adapter import retry_supabase_query

    offsets = []

    def respond(request):
        offsets.append(request.url.params["offset"])
        if len(offsets) <= 2:
            return httpx.Response(500, json=STATEMENT_TIMEOUT)
        return httpx.Response(200, json=[{"id": "game"}])

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        wrapped = archive.wrap(SimpleNamespace(table=client.from_))
        page = retry_supabase_query(
            lambda: wrapped.table("games").select("id").order("id").range(1000, 1999).execute(), initial_delay=0
        )
    assert page.data == [{"id": "game"}] and offsets == ["1000", "1000", "1000"]
    recovered = archive.manifest["recovered_queries"]
    assert [(query["table"], query["error_type"]) for query in recovered] == [("games", "APIError")] * 2
    assert ["range", [1000, 1999], {}] in json.loads(read_object(archive, recovered[0]["request"]))
    assert [query["table"] for query in archive.manifest["queries"]] == ["games"]
    archive.finish(True)
    assert json.loads((archive.directory / "manifest.json").read_text())["status"] == "complete"


def test_skipped_lookup_stays_failed_when_a_later_caller_repeats_it(archive):
    teams = []

    def respond(request):
        teams.append(request.url.params["team_id_master"])
        if len(teams) == 1:
            return httpx.Response(500, json=STATEMENT_TIMEOUT)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        wrapped = archive.wrap(SimpleNamespace(table=client.from_))

        def deprecated(batch):
            query = wrapped.table("teams").select("team_id_master").in_("team_id_master", batch)
            return query.eq("is_deprecated", True).execute()

        with pytest.raises(APIError):
            deprecated(["a"])
        deprecated(["b"])
        deprecated(["a"])
    assert teams == ["in.(a)", "in.(b)", "in.(a)"]
    assert [query["table"] for query in archive.manifest["failed_queries"]] == ["teams"]
    assert archive.manifest["recovered_queries"] == []
    with pytest.raises(RuntimeError, match="query_execution:APIError"):
        archive.finish(True)


def test_retry_retires_only_its_own_request_after_an_abandoned_failure(archive):
    teams = []

    def respond(request):
        teams.append(request.url.params["team_id_master"])
        if len(teams) <= 2:
            return httpx.Response(500, json=STATEMENT_TIMEOUT)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        wrapped = archive.wrap(SimpleNamespace(table=client.from_))

        def lookup(batch):
            return wrapped.table("teams").select("team_id_master").in_("team_id_master", batch).execute()

        with pytest.raises(APIError):
            lookup(["a"])
        with pytest.raises(APIError):
            lookup(["b"])
        lookup(["b"])
    assert teams == ["in.(a)", "in.(b)", "in.(b)"]
    pending = archive.manifest["failed_queries"]
    assert len(pending) == 1 and len(archive.manifest["recovered_queries"]) == 1
    assert ["in_", ["team_id_master", ["a"]], {}] in json.loads(read_object(archive, pending[0]["request"]))


def test_identical_read_of_another_table_does_not_retire_a_failure(archive):
    def respond(request):
        if request.url.path.endswith("/rankings_full"):
            return httpx.Response(500, json=STATEMENT_TIMEOUT)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        wrapped = archive.wrap(SimpleNamespace(table=client.from_))
        with pytest.raises(APIError):
            wrapped.table("rankings_full").select("team_id").range(0, 999).execute()
        wrapped.table("current_rankings").select("team_id").range(0, 999).execute()
    pending, answered = archive.manifest["failed_queries"], archive.manifest["queries"]
    assert pending[0]["request"]["sha256"] == answered[0]["request"]["sha256"]
    assert [query["table"] for query in pending] == ["rankings_full"]


def test_failed_query_that_cannot_be_recorded_still_raises_the_database_error(archive, monkeypatch):
    def respond(request):
        return httpx.Response(500, json=STATEMENT_TIMEOUT)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        wrapped = archive.wrap(SimpleNamespace(table=client.from_))
        monkeypatch.setattr(archive, "blob", lambda *args: (_ for _ in ()).throw(OSError("full disk")))
        with pytest.raises(APIError, match="statement timeout"):
            wrapped.table("games").select("id").execute()
    with pytest.raises(RuntimeError, match="input archive failed"):
        archive.finish(True)
    assert archive.errors == ["query_failure:OSError", "query_execution:APIError"]


@pytest.mark.asyncio
async def test_cohort_retrying_while_another_cohort_saves_still_retires_its_failure(archive):
    from src.rankings.calculator import _persist_game_explainability

    sent = []

    def respond(request):
        sent.append(json.loads(request.content)["rows"][0]["game_uuid"])
        if sent == ["first"]:
            return httpx.Response(500, json=STATEMENT_TIMEOUT)
        return httpx.Response(200, json=1)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        wrapped = archive.wrap(SimpleNamespace(table=client.from_, rpc=client.rpc))
        saved = await asyncio.gather(
            _persist_game_explainability(wrapped, pd.DataFrame([explainability_row("first")])),
            _persist_game_explainability(wrapped, pd.DataFrame([explainability_row("second")])),
        )
    assert saved == [(1, 0), (1, 0)] and sent == ["first", "second", "first"]
    recovered = archive.manifest["recovered_queries"]
    assert [query["table"] for query in recovered] == ["rpc:batch_upsert_game_explainability"]
    archive.finish(True)
    assert json.loads((archive.directory / "manifest.json").read_text())["status"] == "complete"


@pytest.mark.asyncio
async def test_rankings_full_saved_without_missing_columns_retires_rankings_full_upserts_only(archive, monkeypatch):
    import scripts.calculate_rankings as command

    team = {"team_id": "team-1", "age_group": "u12", "gender": "Male", "state_code": "AZ"}
    published = dict(team, power_score_true=0.75, power_score_final=0.63, exp_margin=0.7, exp_goals_against=0.9)
    monkeypatch.setattr(command, "v53e_to_rankings_full_format", lambda *_args, **_kwargs: pd.DataFrame([published]))

    def respond(request):
        table = request.url.path.rsplit("/", 1)[-1]
        if request.method == "POST":
            rows = json.loads(request.content)
            missing = [column for column in ("exp_margin", "exp_goals_against") if column in rows[0]]
            if table == "current_rankings" or missing:
                column = (missing or ["rank"])[0]
                message = f"Could not find the '{column}' column of '{table}' in the schema cache"
                return httpx.Response(400, json={"code": "PGRST204", "message": message, "details": None, "hint": None})
            return httpx.Response(201, json=rows)
        if table == "teams":
            deprecated = "is_deprecated" in request.url.params
            return httpx.Response(200, json=[] if deprecated else [dict(team, team_id_master="team-1")])
        if request.url.params["select"] == "power_score_final":
            return httpx.Response(500, json={"code": "XX000", "message": "fixture failure"})
        return httpx.Response(200, json=[{"team_id": "team-1"}])

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        wrapped = archive.wrap(SimpleNamespace(table=client.from_))
        with pytest.raises(APIError):
            wrapped.table("rankings_full").select("power_score_final").execute()
        with pytest.raises(APIError):
            wrapped.table("current_rankings").upsert([{"team_id": "team-1"}]).execute()
        token = ACTIVE_ARCHIVE.set(archive)
        try:
            saved = await command.save_rankings_to_supabase(
                wrapped, pd.DataFrame([team]), use_rankings_full=True, maintain_backward_compat=False
            )
        finally:
            ACTIVE_ARCHIVE.reset(token)
    assert saved == 1
    retired = [(query["table"], query["operation"]) for query in archive.manifest["recovered_queries"]]
    assert retired == [("rankings_full", "upsert"), ("rankings_full", "upsert")]
    unanswered = [(query["table"], query["operation"]) for query in archive.manifest["failed_queries"]]
    assert unanswered == [("rankings_full", "select"), ("current_rankings", "upsert")]
    with pytest.raises(RuntimeError, match="input archive failed"):
        archive.finish(True)
    assert archive.errors == ["query_execution:APIError", "query_execution:APIError"]


@pytest.mark.asyncio
async def test_actual_output_persistence_rpcs_record_requests_and_responses(archive):
    from src.rankings.calculator import _persist_game_explainability, _persist_game_residuals

    requests = []

    def respond(request):
        requests.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        return httpx.Response(200, json=1)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = SyncPostgrestClient("https://example.test/rest/v1", http_client=http)
        wrapped = archive.wrap(SimpleNamespace(table=client.from_, rpc=client.rpc))
        assert await _persist_game_explainability(wrapped, pd.DataFrame([explainability_row("game")])) == (1, 0)
        residuals = pd.DataFrame([{"game_id": "game", "ml_overperformance": -0.2}])
        assert await _persist_game_residuals(wrapped, residuals) == (1, 0)
    assert [name for name, _ in requests] == ["batch_upsert_game_explainability", "batch_update_ml_overperformance"]
    queries = archive.manifest["queries"]
    assert len(queries) == 2
    for query, (name, payload) in zip(queries, requests):
        assert query["table"] == "rpc:" + name and query["operation"] == "rpc"
        assert json.loads(read_object(archive, query["request"])) == [["rpc", [payload], {}]]
        assert json.loads(read_object(archive, query["response"])) == 1
    archive.finish(True)


@pytest.mark.asyncio
async def test_non_ml_v53e_captures_actual_configuration_without_changing_results(archive):
    from dataclasses import asdict

    from src.etl.v53e import V53EConfig
    from src.rankings.calculator import compute_rankings_v53e_only

    games = pd.DataFrame([
        dict(game_id=str(i), team_id=team, opp_id=opp, gf=gf, ga=ga, date=pd.Timestamp("2026-11-01"),
             age="14", gender="Male", opp_age="14", opp_gender="Male")
        for i in range(4) for team, opp, gf, ga in [("a", "b", 2, 1), ("b", "a", 1, 2)]
    ])
    cfg = V53EConfig()
    kwargs = dict(supabase_client=None, games_df=games, today=pd.Timestamp("2026-11-11"),
                  v53_cfg=cfg, fetch_from_supabase=False)
    baseline = await compute_rankings_v53e_only(**kwargs)
    token = ACTIVE_ARCHIVE.set(archive)
    try:
        observed = await compute_rankings_v53e_only(**kwargs)
    finally:
        ACTIVE_ARCHIVE.reset(token)
    for key, frame in baseline.items():
        if isinstance(frame, pd.DataFrame):
            # v53e stamps its wall-clock completion independently of the as-of date.
            pd.testing.assert_frame_equal(
                frame.drop(columns="last_calculated", errors="ignore"),
                observed[key].drop(columns="last_calculated", errors="ignore"),
                check_exact=True,
            )
    configurations = archive.manifest["engine_configurations"]
    assert len(configurations) == 1
    assert json.loads(read_object(archive, configurations[0]["configuration"])) == asdict(cfg)
    archive.finish(True)


def test_existing_archive_is_never_reused_or_overwritten(archive):
    archive.finish(True)
    before = (archive.directory / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        InputArchive(archive.directory, ROOT, {})
    with pytest.raises(FileExistsError):
        archive.finish(True)
    assert (archive.directory / "manifest.json").read_bytes() == before


def test_unrelated_tables_and_rpcs_are_not_copied_into_the_archive(archive):
    table = SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"email": "private@example.test"}]))
    wrapped = archive.wrap(SimpleNamespace(table=lambda name: table, rpc=lambda name, params: table))
    assert wrapped.table("user_profiles") is table
    assert wrapped.rpc("billing", {}) is table
    assert not archive.manifest["queries"]


def test_source_change_invalidates_the_archive_without_touching_shared_sources(archive, tmp_path):
    source = tmp_path / "owned_source"
    source.mkdir()
    (source / "calculation.py").write_bytes(b"original")
    archive.source_root = source
    archive.manifest["source_files"] = {"calculation.py": archive.blob(b"original", "source")}
    (source / "calculation.py").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="source_integrity"):
        archive.finish(True)
    assert json.loads((archive.directory / "manifest.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("outcome", ["success", "empty", "error", "cancelled"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_actual_cli_archive_lifecycle_restores_context_and_marks_completion(monkeypatch, tmp_path, outcome, dry_run):
    import asyncio
    import sys

    from scripts import calculate_rankings as command

    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-only")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "calculate_rankings.py",
            *(["--dry-run"] if dry_run else []),
            "--ranking-profile",
            "legacy",
            "--provenance-dir",
            str(tmp_path / "capture"),
        ],
    )

    class Metadata:
        def table(self, name):
            assert name == "teams"
            return self

        def select(self, *args):
            return self

        def in_(self, *args):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    monkeypatch.setattr(command, "create_client", lambda *args: Metadata())
    monkeypatch.setattr(
        command,
        "MergeResolver",
        lambda *args: SimpleNamespace(
            load_merge_map=lambda: None,
            has_merges=False,
            version="fixture",
        ),
    )

    async def compute(**kwargs):
        assert (ACTIVE_ARCHIVE.get() is None) is dry_run
        assert kwargs["supabase_client"] is not None
        assert kwargs["save_snapshot"] is (not dry_run)
        if outcome == "error":
            raise ValueError("calculation failed")
        if outcome == "cancelled":
            raise KeyboardInterrupt()
        teams = (
            pd.DataFrame()
            if outcome == "empty"
            else pd.DataFrame(
                [
                    {
                        "team_id": "a",
                        "age": 14,
                        "gender": "Male",
                        "status": "Active",
                        "powerscore_ml": 0.7,
                    }
                ]
            )
        )
        return {"teams": teams}

    monkeypatch.setattr(command, "compute_all_cohorts", compute)
    saved = []

    async def save(client, teams, **kwargs):
        saved.append(teams.copy())
        return len(teams)

    monkeypatch.setattr(command, "save_rankings_to_supabase", save)
    monkeypatch.setattr(command, "_backfill_total_game_stats", lambda *args: 1)
    if outcome in {"error", "cancelled"}:
        with pytest.raises(SystemExit if outcome == "error" else KeyboardInterrupt):
            asyncio.run(command.main())
    else:
        asyncio.run(command.main())
    assert ACTIVE_ARCHIVE.get() is None
    assert len(saved) == int(not dry_run and outcome == "success")
    if dry_run:
        assert not (tmp_path / "capture").exists()
        return
    manifest = json.loads((tmp_path / "capture/manifest.json").read_text())
    assert manifest["status"] == ("complete" if outcome == "success" else "failed")


@pytest.mark.parametrize("failure", ["source_read", "object_write", "directory", "existing_directory"])
@pytest.mark.parametrize("outcome", ["success", "empty", "error", "cancelled"])
def test_cli_initialization_failures_preserve_ranking_work_and_original_errors(monkeypatch, tmp_path, failure, outcome):
    import asyncio
    import sys

    from scripts import calculate_rankings as command
    from src.rankings.archive_storage import verify_archive

    directory = tmp_path / "capture"
    if failure == "existing_directory":
        directory.mkdir()
        (directory / "manifest.json").write_text("preserve existing evidence")
    before = {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-only")
    monkeypatch.setattr(sys, "argv", ["calculate_rankings.py", "--ranking-profile", "legacy",
                                    "--provenance-dir", str(directory)])
    calls = []

    class Metadata:
        def table(self, name):
            assert name == "teams"
            return self

        def select(self, *args):
            return self

        def in_(self, *args):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    client = Metadata()
    monkeypatch.setattr(command, "create_client", lambda *args: client)
    monkeypatch.setattr(command, "MergeResolver", lambda *args: SimpleNamespace(
        load_merge_map=lambda: None, has_merges=False, version="fixture"))
    if failure == "source_read":
        read_bytes = Path.read_bytes

        def fail_read(path):
            if path == ROOT / "config/__init__.py":
                raise OSError("fixture source unavailable")
            return read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", fail_read)
    elif failure == "object_write":
        monkeypatch.setattr(InputArchive, "blob", lambda *args: (_ for _ in ()).throw(OSError("full disk")))
    elif failure == "directory":
        mkdir = Path.mkdir

        def fail_mkdir(path, *args, **kwargs):
            if path == directory:
                raise PermissionError("fixture directory denied")
            return mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    async def compute(**kwargs):
        assert ACTIVE_ARCHIVE.get() is None
        assert kwargs["supabase_client"] is client
        assert kwargs["save_snapshot"] is True
        calls.append("compute")
        if outcome == "error":
            raise ValueError("original calculation failure")
        if outcome == "cancelled":
            raise KeyboardInterrupt("original cancellation")
        if outcome == "empty":
            return {"teams": pd.DataFrame()}
        return {"teams": pd.DataFrame([dict(team_id="a", age=14, gender="Male", status="Active",
                                           powerscore_ml=.7)])}

    async def save(actual_client, teams, **kwargs):
        assert actual_client is client and teams.iloc[0]["powerscore_ml"] == .7
        calls.append("save")
        return 1

    def backfill(*args):
        calls.append("backfill")
        return 1

    monkeypatch.setattr(command, "compute_all_cohorts", compute)
    monkeypatch.setattr(command, "save_rankings_to_supabase", save)
    monkeypatch.setattr(command, "_backfill_total_game_stats", backfill)
    expected = "FileExistsError" if failure == "existing_directory" else (
        "PermissionError" if failure == "directory" else "OSError")
    if outcome == "error":
        error_type, error_match = SystemExit, None
    elif outcome == "cancelled":
        error_type, error_match = KeyboardInterrupt, "original cancellation"
    else:
        error_type = RuntimeError
        error_match = "Ranking completed, but its input archive failed: initialization:" + expected
    with pytest.raises(error_type, match=error_match) as raised:
        asyncio.run(command.main())
    if outcome == "error":
        assert raised.value.code == 1
    assert calls == (["compute", "save", "backfill"] if outcome == "success" else ["compute"])
    assert ACTIVE_ARCHIVE.get() is None
    if failure == "existing_directory":
        assert {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()} == before
    else:
        assert not (directory / "manifest.json").exists()
        with pytest.raises(FileNotFoundError):
            verify_archive(directory)


def test_ml_recording_preserves_outputs_and_retains_actual_training_cutoffs_and_models(archive):
    from src.rankings.layer13_predictive_adjustment import FEATURE_NAMES, Layer13Config, _fit_and_residualize

    rng = np.random.default_rng(42)
    features = pd.DataFrame(rng.normal(size=(80, 5)), columns=FEATURE_NAMES)
    features["date"] = pd.date_range("2026-06-01", periods=80)
    features["goal_margin"] = rng.normal(size=80)
    features["id"] = [f"game-{i}" for i in range(80)]
    train = features.iloc[:60].copy()
    cfg = Layer13Config()
    cfg.min_training_rows, cfg.walk_forward_folds, cfg.walk_forward_enabled = 10, 2, True
    cfg.xgb_params = {"n_estimators": 3, "max_depth": 2, "n_jobs": 1, "random_state": 42}
    cfg.rf_params = {"n_estimators": 3, "max_depth": 2, "n_jobs": 1, "random_state": 42}
    baseline = _fit_and_residualize(features, train, cfg)
    token = ACTIVE_ARCHIVE.set(archive)
    try:
        observed = _fit_and_residualize(features, train, cfg)
    finally:
        ACTIVE_ARCHIVE.reset(token)
    pd.testing.assert_frame_equal(observed, baseline, check_exact=True)
    fits = archive.manifest["model_fits"]
    assert len(fits) >= 2
    assert fits[0]["training_cutoff"] == "2026-07-30"
    for fit in fits:
        frozen = pd.read_parquet(io.BytesIO(read_object(archive, fit["training_inputs"])))
        assert frozen.date.max().date().isoformat() == fit["training_cutoff"]
    restored = pickle.loads(read_object(archive, fits[0]["model"]))
    np.testing.assert_array_equal(restored.predict(features[FEATURE_NAMES].to_numpy()), observed.pred_margin.to_numpy())
    assert archive.manifest["model_outputs"][0]["fit_ids"] == [fit["fit_id"] for fit in fits]
    saved = pd.read_parquet(io.BytesIO(read_object(archive, archive.manifest["model_outputs"][0]["values"])))
    pd.testing.assert_frame_equal(saved, baseline, check_exact=True)
    archive.finish(True)
