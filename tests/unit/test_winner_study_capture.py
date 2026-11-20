"""Exercise preview, capture, failure recovery and released review through Python orchestration."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from src.predictions import winner_study as study
from tests.score_study_fixtures import baseline, parent_row
from tests.unit.test_winner_study import records
from tests.winner_study_fixtures import definition


class Client:
    def __init__(self):
        self.manifest, self.calls, self.saved = definition(), [], {}
        self.signature = study.digest(study.serialized(self.manifest).encode())
        self.rows = [parent_row()]
        self.rows[0]["baseline_forecast_id"] = "02"
        self.rows[0]["parent_payload"]["reference_time"] = "2026-11-20T01:00:00Z"
        self.rows[0]["parent_payload"]["receipt"] = {"aa_parity": True}
        self.rows[0]["parent_payload"]["context"]["teamAInput"]["games_played"] = 12
        self.rows[0]["parent_payload"]["context"]["teamBInput"]["games_played"] = 8
        self.bad_hash, self.released = False, None

    def rpc(self, name, args):
        return Query(self, name, args)

    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, client, name, args=None):
        self.client, self.name, self.args, self.filters = client, name, args, {}
        self.selected = None

    def select(self, fields):
        self.selected = fields
        return self

    def eq(self, key, value):
        columns = {
            "compare_winner_studies": {"signature"},
            "compare_winner_forecasts": {"study_signature", "baseline_forecast_id", "monitor_signature"},
        }
        assert key in columns[self.name], "Unknown filter column: " + key
        self.filters[key] = value
        return self

    def single(self):
        return self

    def execute(self):
        c, args, name = self.client, self.args, self.name
        json.dumps(args, allow_nan=False)
        c.calls.append((name, deepcopy(args)))
        if name == "compare_winner_studies":
            data = {
                "signature": c.signature,
                "manifest": c.manifest,
                "registered_at": "2026-11-20T01:00:00Z",
                **{
                    key: c.manifest[key]
                    for key in ("monitor_signature", "capture_start", "capture_end", "review_not_before")
                },
            }
        elif name == "register_compare_winner_study":
            data = c.signature
        elif name == "compare_winner_capture_queue":
            data = [
                r
                for r in c.rows
                if (args["p_after"] is None or r["baseline_forecast_id"] > args["p_after"])
                and r["baseline_forecast_id"] not in c.saved
            ][: args["p_limit"]]
        elif name == "freeze_compare_winner_forecast":
            c.saved[args["p_baseline"]] = args["p_payload"]
            data = True
        elif name == "compare_winner_forecasts":
            raw = c.saved.get(self.filters["baseline_forecast_id"])
            if raw is None:
                raise APIError(
                    {"code": "PGRST116", "message": "No matching row", "details": "The result contains 0 rows"}
                )
            data = {
                "study_signature": c.signature,
                "baseline_forecast_id": self.filters["baseline_forecast_id"],
                "monitor_signature": c.manifest["monitor_signature"],
                "payload": json.loads(raw),
                "payload_sha256": "0" * 64 if c.bad_hash else study.digest(raw.encode()),
                "captured_at": "2026-11-20T01:00:00Z",
            }
        elif name == "compare_winner_coverage":
            data = [{"baseline": 3, "paired": len(c.saved), "missing_current": 1, "missing_winner": 2 - len(c.saved)}]
        elif name == "compare_winner_review":
            data = c.released if c.released is not None else [{"open": False, "captured": len(c.saved)}]
        else:
            raise AssertionError("Unexpected private API: " + name)
        if self.filters and any(data[key] != value for key, value in self.filters.items()):
            raise APIError({"code": "PGRST116", "message": "No matching row", "details": "The result contains 0 rows"})
        if self.selected and self.selected != "*":
            data = {field: data[field] for field in self.selected.split(",")}
        return SimpleNamespace(data=data)


def setup(monkeypatch):
    c = Client()
    monkeypatch.setattr(
        study, "source_identity", lambda root: {k: c.manifest[k] for k in ("code_revision", "execution_hashes")}
    )

    def replay(rows, manifest, root):
        if rows[0].get("bad"):
            raise ValueError("bad synthetic context")
        return [{"prediction": baseline(), "receipt": {"aa_parity": True, "baseline_replay": True}}]

    monkeypatch.setattr(study, "replay", replay)
    return c


@pytest.mark.parametrize("dry_run", [True, False])
def test_collector_preview_and_capture_verify_readback_without_target_reads(monkeypatch, tmp_path, dry_run):
    c = setup(monkeypatch)
    result = study.capture_winners(c, c.signature, tmp_path, dry_run=dry_run, limit=1)
    assert result["errors"] == {} and result["validated"] == 1
    assert result["captured"] == (0 if dry_run else 1)
    assert len(c.saved) == (0 if dry_run else 1)
    assert not list(tmp_path.iterdir())
    assert not any(name in {"games", "prospective_match_predictions"} for name, _ in c.calls)


def test_bad_first_page_does_not_starve_later_capture(monkeypatch, tmp_path):
    c = setup(monkeypatch)
    c.rows.insert(0, {**deepcopy(c.rows[0]), "baseline_forecast_id": "01", "bad": True})
    result = study.capture_winners(c, c.signature, tmp_path, dry_run=False, limit=1)
    assert result["selected"] == 2 and result["captured"] == 1 and result["errors"] == {"ValueError": 1}
    assert set(c.saved) == {"02"}
    queues = [args for name, args in c.calls if name == "compare_winner_capture_queue"]
    assert queues[1]["p_after"] == "01"


def test_readback_hash_mismatch_never_reports_success(monkeypatch, tmp_path):
    c = setup(monkeypatch)
    c.bad_hash = True
    result = study.capture_winners(c, c.signature, tmp_path, dry_run=False, limit=1)
    assert result["captured"] == 0 and result["errors"] == {"ValueError": 1}


def test_registration_readback_and_wrong_analysis_identity(monkeypatch, tmp_path):
    c = setup(monkeypatch)
    assert study.register_study(c, c.manifest, tmp_path)["registered"] is False
    assert not any(name == "register_compare_winner_study" for name, _ in c.calls)
    assert study.register_study(c, c.manifest, tmp_path, dry_run=False)["registered"]
    monkeypatch.setattr(study, "source_identity", lambda root: {"code_revision": "f" * 40})
    with pytest.raises(ValueError, match="Review source differs"):
        study.review_winners(c, c.signature, tmp_path, dry_run=False)


def test_sealed_review_never_loads_result_auditor(monkeypatch, tmp_path):
    c = setup(monkeypatch)
    monkeypatch.setattr(study, "strict_resolver", lambda client: pytest.fail("sealed result read"))
    assert study.review_winners(c, c.signature, tmp_path, dry_run=False)["status"] == "coverage_only"


def test_released_review_includes_capture_gaps_and_audits_uncaptured_sources(monkeypatch, tmp_path):
    c = setup(monkeypatch)
    c.released = records(2)
    for row in c.released:
        row["open"] = True
        row["fixture_payload"]["source_snapshot"].update(home_team_master_id="a", away_team_master_id="b")
    monkeypatch.setattr(study, "strict_resolver", lambda client: object())
    monkeypatch.setattr(study, "settlement_aliases", lambda resolver: {})
    audited = []

    def audit(client, fixture, resolver, aliases):
        audited.append(fixture["source_game_id"])
        if fixture["source_game_id"] == "0":
            return None, False, "ambiguous_result"
        return (
            {"home_score": 2, "away_score": 1, "home_team_master_id": "a", "away_team_master_id": "b"},
            False,
            "source_game_id",
        )

    monkeypatch.setattr(study, "database_result", audit)
    result = study.review_winners(c, c.signature, tmp_path, dry_run=False)
    assert audited == ["0", "1"] and result["paired_matches"] == 1
    assert result["coverage"] == {"missing_or_changed_exact_source_result": 1}
    assert result["capture_coverage"][0]["missing_winner"] == 2
