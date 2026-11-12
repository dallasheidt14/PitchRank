import json
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.predictions import challenger_capture as capture
from src.predictions.form_policy import PINNED_MODEL_SIGNATURE, PINNED_REVISION
from src.predictions.form_study_contract import FORM_CONFIGURATION
from tests.challenger_fixtures import manifest, qualification_report


class Query:
    def __init__(self, client, table):
        self.client, self.table = client, table
        self.filters, self.fields, self.start, self.end, self.is_single = [], [], 0, 999, False

    def select(self, fields): self.fields = fields.split(","); return self
    def eq(self, key, value): self.filters.append(lambda row: row[key] == value); return self
    def gte(self, key, value): self.filters.append(lambda row: row[key] >= value); return self
    def lte(self, key, value): self.filters.append(lambda row: row[key] <= value); return self
    def order(self, key): return self
    def single(self): self.is_single = True; return self
    def range(self, start, end): self.start, self.end = start, end; return self

    def execute(self):
        rows = [deepcopy(row) for row in self.client.rows[self.table] if all(test(row) for test in self.filters)]
        rows = rows[self.start:self.end + 1]
        if self.fields != ["*"]: rows = [{key: row[key] for key in self.fields} for row in rows]
        if self.is_single: assert len(rows) == 1
        return SimpleNamespace(data=rows[0] if self.is_single else rows)


class Client:
    def __init__(self, rows): self.rows, self.writes = rows, []
    def table(self, table): return Query(self, table)
    def rpc(self, name, params):
        json.dumps(params, allow_nan=False)
        def execute():
            self.writes.append((name, deepcopy(params)))
            return SimpleNamespace(data=True)
        return SimpleNamespace(execute=execute)


class Sources:
    def __init__(self, row, case): self.row, self.case = row, case
    def preferred_members(self):
        return [{"id": self.row["id"], "binding": {"ledger_id": self.row["id"]}, **self.case["fixture"]}]
    def record(self, binding): return deepcopy(self.row)
    def case_inputs(self, binding): return deepcopy(self.case)
    def prediction_input_error(self, case, day): return None


@pytest.fixture
def ready(monkeypatch):
    class FixedDate(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2026, 11, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(capture, "datetime", FixedDate)
    definition = manifest()
    signature = capture.digest(definition)
    monkeypatch.setattr(capture, "source_identity", lambda root: (
        definition["research_revision"], definition["research_sources"],
    ))
    case = {"reference_time": "2026-11-12T12:00:00Z", "predictor_revision": PINNED_REVISION,
            "source_witness": {"ledger_id": "f1"}, "fixture": {"source_game_id": "g1", "game_date": "2026-11-16",
                "home_team_master_id": "a", "away_team_master_id": "b"},
            "teamA": {"team_id_master": "a"}, "teamB": {"team_id_master": "b"}, "games": [],
            "expectations": {}, "calibrations": {}}
    row = {"id": "f1", "source_game_id": "g1", "game_date": "2026-11-16", "provider_code": "gotsport",
           "heuristic_prediction": {"modelSignature": PINNED_MODEL_SIGNATURE},
           "heuristic_prediction_status": "completed"}
    client = Client({capture.MANIFESTS: [{"candidate_signature": signature, "manifest": definition,
                      "confirmation_start": "2026-11-16", "confirmation_end": "2026-12-13"}],
                     capture.FORECASTS: [], "prospective_match_predictions": [row]})
    return client, signature, Sources(row, case)


def runner(bundle, folder):
    case = bundle["cases"][0]
    assert case["formOverrides"] == {"residual_sequence": {"a": 0., "b": 0.}}
    assert case["games"] == []
    return {"aa_parity": True, "model_signature": PINNED_MODEL_SIGNATURE, "cases": 1,
            "predictor_revision": PINNED_REVISION, "outputs": {"residual_sequence": [{"id": "g1", "prediction": {
                "winProbabilityA": .5, "drawProbability": .2, "winProbabilityB": .3,
                "expectedMargin": .5, "expectedScore": {"teamA": 2, "teamB": 1},
                "blowout4PlusProbability": .1}}]}}


def test_preview_writes_nothing_and_execute_records_exact_baseline_inputs(ready, monkeypatch):
    client, signature, sources = ready
    def forbidden(*args, **kwargs): raise AssertionError("Preview wrote temporary files or ran the predictor")
    with monkeypatch.context() as patch:
        patch.setattr(capture, "TemporaryDirectory", forbidden)
        report = capture.capture_candidate(client, signature, sources, forbidden)
    assert report["eligible"] == 1 and report["captured"] == 0 and client.writes == []
    result = capture.capture_candidate(client, signature, sources, runner, dry_run=False)
    assert result["captured"] == 1 and not result["errors"]
    name, params = client.writes[0]
    assert name == "freeze_compare_challenger" and params["p_baseline_forecast_id"] == "f1"
    payload = json.loads(params["p_payload"])
    assert payload["frozen_inputs"]["baseline_prediction"] == sources.row["heuristic_prediction"]
    assert payload["frozen_inputs"]["case"]["games"] == []
    assert payload["frozen_inputs"]["form_diagnostics"]["a"]["usable"] == 0
    assert payload["provenance"]["training_provenance"]["trained"] is False


@pytest.mark.parametrize("invalid", ["parity", "risk", "identity", "signature"])
def test_invalid_runner_output_never_reaches_writer(ready, invalid):
    client, signature, sources = ready
    def invalid_runner(bundle, folder):
        result = runner(bundle, folder)
        if invalid == "parity": result["aa_parity"] = False
        if invalid == "risk": result["outputs"]["residual_sequence"][0]["prediction"].pop("blowout4PlusProbability")
        if invalid == "identity": result["outputs"]["residual_sequence"][0]["id"] = "different"
        if invalid == "signature": result["model_signature"] = "other"
        return result
    result = capture.capture_candidate(client, signature, sources, invalid_runner, dry_run=False)
    assert result["errors"] == {"ValueError": 1} and client.writes == []


def test_missing_inputs_late_capture_and_existing_capture_are_explicit(ready):
    client, signature, sources = ready
    client.rows[capture.FORECASTS] = [{"baseline_forecast_id": "f1", "candidate_signature": signature}]
    report = capture.capture_candidate(client, signature, sources, runner)
    assert report["already_captured"] == 1
    client.rows[capture.FORECASTS] = []
    report = capture.capture_candidate(client, signature, sources, runner, now=datetime(2026, 11, 16, tzinfo=timezone.utc))
    assert report["skipped"] == {"prematch_deadline_passed": 1}
    sources.preferred_members = lambda: []
    report = capture.capture_candidate(client, signature, sources, runner)
    assert report["skipped"] == {"missing_or_conflicting_authenticated_baseline": 1}
    assert client.writes == []


def test_registration_requires_qualified_closed_sufficient_reviewed_report():
    report = qualification_report()
    args = ("a" * 40, {"source": "b" * 64})
    with pytest.raises(ValueError, match="separately reviewed"): capture.candidate_definition(report, *args)
    for mutate in (
        lambda r: r.update(status="insufficient_data"),
        lambda r: r["audit"]["periods"]["evaluation"].update(games=999),
        lambda r: r.update(server_observed_at="2026-01-01T01:00:00Z"),
        lambda r: r.update(log_loss_delta_95=[-.1, 0]),
    ):
        invalid = deepcopy(report)
        mutate(invalid)
        with pytest.raises(ValueError): capture.candidate_definition(invalid, *args, reviewed=True)
    definition = capture.candidate_definition(report, *args, reviewed=True, qualified_sources={"source": "b" * 64})
    assert definition["form_configuration"] == FORM_CONFIGURATION
    assert definition["confirmation_policy"]["minimum_paired_settled"] == 1000


def test_capture_rejects_changed_registered_source(ready, monkeypatch):
    client, signature, sources = ready
    monkeypatch.setattr(capture, "source_identity", lambda root: ("c" * 40, {}))
    with pytest.raises(ValueError, match="exact registered"): capture.capture_candidate(client, signature, sources, runner)
    assert client.writes == []


@pytest.mark.parametrize("changed_path", [
    "src/predictions/form_research.py", "src/predictions/form_archive_sources.py",
    "src/predictions/archive_inputs.py", "frontend/scripts/verify-compare-source.ts",
])
def test_qualification_binds_candidate_math_to_the_authoritative_study(ready, monkeypatch, changed_path):
    from src.predictions.form_study_contract import study_definition
    client, _, _ = ready
    names = capture.candidate_execution_paths(capture.ROOT)
    sources = {name: "b" * 64 for name in names}
    definition = study_definition("2026-11-12T00:00:00Z", sources)
    report = qualification_report()
    report.update(policy=definition["policy"], server_observed_at="2027-01-11T00:00:00Z")
    monkeypatch.setattr(capture, "source_identity", lambda root: ("a" * 40, deepcopy(sources)))
    monkeypatch.setattr(capture, "qualified_execution_sources", lambda *args: deepcopy(sources))
    monkeypatch.setattr(capture, "_registered_manifest", lambda *args: (
        {"recorded_at": "2026-11-12T00:00:00Z"},
        {"configuration": {"capture_kind": "compare_form_study", "study_definition": definition},
         "source_revision": "f" * 40}, b"manifest",
    ))
    result = capture.register_candidate(client, report, reviewed=True)
    assert result["definition"]["qualified_execution_sources"] == sources
    assert client.writes == []
    changed = {**sources, changed_path: "c" * 64}
    monkeypatch.setattr(capture, "source_identity", lambda root: ("c" * 40, changed))
    with pytest.raises(ValueError, match="execution sources differ"):
        capture.register_candidate(client, report, reviewed=True, dry_run=False)
    assert client.writes == []


def test_preflight_reports_closed_and_already_captured_without_any_archive_reads(ready):
    client, signature, _ = ready
    report = capture.capture_preflight(client, signature, now=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert report["status"] == "confirmation_window_closed" and report["eligible_prematch"] == 0
    assert report["missing_challenger_forecasts"] == 1
    client.rows[capture.FORECASTS] = [{"baseline_forecast_id": "f1", "candidate_signature": signature}]
    report = capture.capture_preflight(client, signature)
    assert report["status"] == "no_pending_prematch_forecasts" and report["already_captured"] == 1
    assert client.writes == []


@pytest.mark.parametrize("eligible", [0, 1])
def test_download_preview_never_creates_files_or_runs_capture(ready, monkeypatch, tmp_path, capsys, eligible):
    from scripts import capture_compare_challenger as cli
    client, signature, _ = ready
    target = tmp_path / "must-not-exist"
    monkeypatch.setattr(cli, "_supabase_client", lambda: client)
    monkeypatch.setattr(cli, "capture_preflight", lambda *args: {
        "eligible_prematch": eligible, "status": "ready" if eligible else "confirmation_window_closed",
    })
    monkeypatch.setattr(cli, "forecast_archive_headers", lambda client: [{"manifest_sha256": "a" * 64}])
    def forbidden(*args, **kwargs): raise AssertionError("Preview wrote or ran capture")
    monkeypatch.setattr(cli, "download_archive", forbidden)
    monkeypatch.setattr(cli, "capture_candidate", forbidden)
    monkeypatch.setattr("sys.argv", ["capture", signature, "--download-archives", str(target)])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True and not target.exists() and client.writes == []
