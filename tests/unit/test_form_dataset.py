import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.predictions import form_dataset as dataset
from src.predictions.archive_inputs import authenticate_archive
from src.predictions.forecast_archive import FORECAST_FIELDS
from src.predictions.form_policy import PINNED_MODEL_SIGNATURE
from src.predictions.form_research import timestamp
from src.predictions.form_study_contract import study_definition, validate_study_definition
from src.rankings import input_archive
from src.rankings.archive_storage import INDEX, publish_archive
from src.rankings.input_archive import FORECAST_TABLE, InputArchive
from tests.unit.test_form_archive_sources import forecast
from tests.unit.test_form_study import study_archive
from tests.unit.test_ranking_archive_storage import FakeServer

ROOT = Path(__file__).resolve().parents[2]
CHECKOUT_GUARD = dataset.assert_registered_checkout


class DatasetServer(FakeServer):
    def __init__(self):
        super().__init__()
        self.ledger, self.games, self.outcome_reads = {}, {}, []

    def table(self, name):
        if name == INDEX:
            return super().table(name)
        assert name in {FORECAST_TABLE, "games"}
        server = self

        class Query:
            def select(self, fields):
                self.fields = fields.split(",")
                return self

            def in_(self, key, ids):
                assert key == "id" and len(ids) <= 100
                self.ids = ids
                return self

            def order(self, key):
                assert key == "id"
                return self

            def range(self, first, last):
                assert (first, last) == (0, 999)
                return self

            def execute(self):
                server.outcome_reads.append((name, self.ids))
                rows = server.ledger if name == FORECAST_TABLE else server.games
                return SimpleNamespace(data=[{key: rows[id].get(key) for key in self.fields}
                                             for id in sorted(self.ids) if id in rows])

        return Query()


@pytest.fixture
def registered_study(tmp_path, monkeypatch):
    directory, manifest = study_archive.__wrapped__(tmp_path)
    manifest.update(started_at="2026-11-12T00:00:00Z", finished_at="2026-11-12T00:00:00Z")
    manifest["configuration"]["study_definition"] = study_definition(
        manifest["started_at"], manifest["configuration"]["study_definition"]["research_sources"],
    )
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    server = DatasetServer()
    server.recorded_at = "2026-11-12T01:00:00Z"
    publish_archive(server, directory, dry_run=False)
    # Code cleanliness and real JS verification have their own integration gates. This layer tests assembly.
    monkeypatch.setattr(dataset, "assert_registered_checkout", lambda study: validate_study_definition(
        study.manifest["configuration"]["study_definition"], registered_at=study.recorded_at,
    ))
    monkeypatch.setattr("src.predictions.form_archive_sources._source_checks", lambda rows, root: [
        {"verified": True, "id": row["id"], "model_signature": PINNED_MODEL_SIGNATURE,
         "reference_time": timestamp(row["heuristic_predicted_at"]).isoformat(timespec="milliseconds")}
        for row in rows
    ])
    day = {"server_time": "2027-01-11T00:00:00Z"}
    monkeypatch.setattr(dataset, "registered_inventory", lambda *args: {
        "as_of": day["server_time"], "archives": sorted(server.rows.values(), key=lambda row: row["manifest_sha256"]),
    })
    history = {"id": "h", "game_date": "2026-11-17", "home_team_master_id": "a", "away_team_master_id": "b",
               "home_score": 2, "away_score": 0}
    for position, (source, match_day, frozen) in enumerate([
        ("h", "2026-11-17", "2026-11-16"), ("d", "2026-11-20", "2026-11-19"),
        ("e", "2026-12-20", "2026-12-19"),
    ]):
        row = {key: None for key in FORECAST_FIELDS.split(",")}
        row.update(forecast(source, match_day, frozen + "T12:00:00Z", 4, [history] if source != "h" else []))
        snapshot = {"game_date": match_day, "home_team_master_id": "a", "away_team_master_id": "b",
                    "provider_id": "provider", "source_url": f"https://x/events/{position + 100}/matches/{position}"}
        row.update(provider_code="gotsport", source_event_id=str(position + 100), evaluation_group_kind="event",
                   evaluation_group_key=f"gotsport:{position + 100}", fixture_payload={"source_snapshot": snapshot})
        moment = frozen + "T13:00:00Z"
        monkeypatch.setattr(input_archive, "utc_now", lambda moment=moment: moment)
        archive = InputArchive(tmp_path / ("capture-" + source), ROOT, {"capture_kind": "frozen_compare_forecasts"})
        archive.query(FORECAST_TABLE, [["select", [FORECAST_FIELDS], {}]],
                      SimpleNamespace(data=[row]), moment, "select")
        archive.finish(True)
        server.recorded_at = moment
        publish_archive(server, archive.directory, dry_run=False)
        server.ledger[row["id"]] = {**deepcopy(row), "evaluation_status": "settled", "actual_game_id": source,
                                    "actual_home_score": 2, "actual_away_score": 0, "actual_outcome": "team_a"}
        server.games[source] = {**snapshot, "id": source, "home_score": 2, "away_score": 0, "is_excluded": False}
    return server, directory, day


def test_preview_and_open_window_export_never_read_outcomes(registered_study, tmp_path):
    server, study, day = registered_study
    day["server_time"] = "2026-12-20T23:00:00Z"
    output = tmp_path / "preview"
    report = dataset.assemble_dataset(server, "url", "token", study, output)
    assert report["evaluation_closed"] is False and report["forecast_archives"] == 3
    assert not output.exists() and not server.outcome_reads
    report = dataset.assemble_dataset(server, "url", "token", study, output, dry_run=False)
    manifest = json.loads((output / "dataset.json").read_text())
    cases = list(dataset.dataset_cases(output, manifest))
    assert report["cases"] == 3 and all("home_score" not in case["fixture"] for case in cases)
    assert not server.outcome_reads
    report, verified = dataset.verified_dataset(server, "url", "token", output)
    assert report["status"] == "evaluation_sealed" and verified is None and not server.outcome_reads


def test_closed_export_reauthenticates_all_sources_inputs_and_exact_settlements(registered_study, tmp_path):
    server, study, _ = registered_study
    output = tmp_path / "dataset"
    report = dataset.assemble_dataset(server, "url", "token", study, output, dry_run=False)
    assert report["cases"] == 3 and report["evaluation"] == "not_performed"
    report, verified = dataset.verified_dataset(server, "url", "token", output)
    assert report["status"] == "insufficient_data" and report["production_promotion"] is False
    assert report["audit"]["periods"] == {
        "development": {"games": 2, "groups": 2}, "evaluation": {"games": 1, "groups": 1},
    }
    manifest, policy, sources, eligible = verified
    assert policy.minimum_games == 1000 and policy.minimum_groups == 20
    assert len(eligible) == 3 and all("games" not in case for case in eligible)
    cases = list(dataset.dataset_cases(output, manifest))
    assert cases[1]["expectations"]["h"]["expected_home_margin"] == 4
    assert sources.valid_expectation(cases[1]["expectations"]["h"], cases[1]["games"][0])


@pytest.mark.parametrize("change", ["omit_case", "score", "source_list", "changed_settlement", "bad_part", "part_hash"])
def test_self_consistent_local_edits_cannot_cherry_pick_or_relabel_the_study(registered_study, tmp_path, change):
    server, study, _ = registered_study
    output = tmp_path / "dataset"
    dataset.assemble_dataset(server, "url", "token", study, output, dry_run=False)
    manifest = json.loads((output / "dataset.json").read_text())
    part = output / manifest["parts"][0]["file"]
    cases = [json.loads(line) for line in part.read_text().splitlines()]
    if change == "omit_case":
        cases.pop()
    elif change == "score":
        cases[0]["fixture"]["home_score"] = 99
    elif change == "source_list":
        manifest["archives"].pop()
    elif change == "changed_settlement":
        server.ledger["forecast-d"]["actual_home_score"] = 9
    elif change == "bad_part":
        manifest["parts"][0]["file"] = "cases/part-../../other.jsonl"
    if change in {"omit_case", "score", "part_hash"}:
        part.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8")
        if change != "part_hash":
            manifest["parts"][0].update(sha256=hashlib.sha256(part.read_bytes()).hexdigest(), cases=len(cases))
    (output / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        dataset.verified_dataset(server, "url", "token", output)


@pytest.mark.parametrize("change,reason", [
    ("unsettled", "unsettled_result"), ("source", "result_source_identity_changed"),
    ("excluded", "excluded_result"), ("fraction", "invalid_or_changed_actual_scores"),
    ("outcome", "conflicting_actual_outcome"), ("freeze", "completed_forecast_changed"),
])
def test_result_exclusions_are_explicit(registered_study, tmp_path, change, reason):
    server, study, _ = registered_study
    if change == "unsettled":
        server.ledger["forecast-d"]["evaluation_status"] = "pending"
    elif change == "source":
        server.games["d"]["source_url"] += "changed"
    elif change == "excluded":
        server.games["d"]["is_excluded"] = True
    elif change == "fraction":
        server.ledger["forecast-d"]["actual_home_score"] = 1.5
    elif change == "outcome":
        server.ledger["forecast-d"]["actual_outcome"] = "draw"
    else:
        server.ledger["forecast-d"]["heuristic_prediction"]["response"]["prediction"]["expectedMargin"] = 99
    report = dataset.assemble_dataset(server, "url", "token", study, tmp_path / "dataset", dry_run=False)
    assert report["exclusions"][reason] == 1 and report["cases"] == 2


def member(source, *, day="2026-11-20", event="100", home="a", away="b", match="1"):
    return {"source_game_id": source, "game_date": day, "team_a_ids": [home], "team_b_ids": [away],
            "home_team_master_id": home, "away_team_master_id": away, "provider_code": "gotsport",
            "source_event_id": event, "evaluation_group_kind": "event", "evaluation_group_key": "gotsport:" + event,
            "heuristic_predicted_at": "2026-11-19T12:00:00Z", "fixture_payload": {"source_snapshot": {
                "provider_id": "p", "source_url": f"https://x/events/{event}/matches/{match}"}}}


def test_duplicate_or_reversed_fixtures_share_groups_without_later_day_alias_leakage():
    original = member("one")
    reverse = member("two", home="b", away="a")
    other_match = member("three", match="2")
    later = member("four", day="2026-12-20", event="200", home="a", away="c")
    later["team_b_ids"].append("b")
    kept, exclusions, _ = dataset.grouped_members([original, reverse, other_match, later])
    assert [meta["source_game_id"] for meta in kept] == ["one", "three", "four"]
    assert kept[0]["event_group"] == kept[1]["event_group"] != kept[2]["event_group"]
    assert kept[0]["_normalised_home"] == "a" and kept[0]["_normalised_away"] == "b"
    assert exclusions == Counter(duplicate_physical_fixture=1)
    assert {entry["home_first"] for entry in kept[0]["duplicate_sources"]} == {True, False}


def test_inferred_groups_are_labelled_and_unverified_events_are_excluded():
    inferred = member("one")
    inferred.update(evaluation_group_kind="inferred_competition_week", source_event_id=None,
                    evaluation_group_key="gotsport:unknown:2026-W47")
    inferred["fixture_payload"]["source_snapshot"]["source_url"] = "https://x/matches/1"
    bad = member("two")
    bad["source_event_id"] = "999"
    kept, exclusions, reasons = dataset.grouped_members([inferred, bad])
    assert kept[0]["group_kind"] == "inferred_competition_week" and len(kept) == 1
    assert exclusions["unverified_evaluation_group"] == 1 and reasons["two"] == "unverified_evaluation_group"


@pytest.mark.parametrize("conflict", [None, "two", "three"])
def test_duplicate_scores_are_normalized_and_every_copy_is_checked(monkeypatch, conflict):
    all_members = [member("one"), member("two", home="b", away="a"), member("three")]
    rows, ledger, games = {}, {}, {}
    for meta in all_members:
        source = meta["source_game_id"]
        meta.update(id="forecast-" + source, binding={"source": source},
                    coverage={"provider": "gotsport", "cohort": "13|Male", "history_band": "8+"})
        raw = {key: None for key in FORECAST_FIELDS.split(",")}
        raw.update({key: meta[key] for key in (
            "id", "source_game_id", "game_date", "home_team_master_id", "away_team_master_id", "fixture_payload",
        )})
        raw["fixture_payload"]["source_snapshot"].update({key: meta[key] for key in (
            "game_date", "home_team_master_id", "away_team_master_id",
        )})
        scores = [0, 2] if source == "two" else [2, 0]
        if source == conflict:
            scores = [3, 0]
        outcome = "team_a" if scores[0] > scores[1] else "team_b"
        rows[source] = raw
        ledger[meta["id"]] = {**deepcopy(raw), "evaluation_status": "settled", "actual_game_id": source,
                               "actual_home_score": scores[0], "actual_away_score": scores[1],
                               "actual_outcome": outcome}
        games[source] = {**raw["fixture_payload"]["source_snapshot"], "id": source,
                         "home_score": scores[0], "away_score": scores[1], "is_excluded": False}
    sources = SimpleNamespace(record=lambda binding: rows[binding["source"]], case_inputs=lambda binding: {})
    # Exercise actual settlement/normalization logic independently of the already-covered frozen-input gate.
    monkeypatch.setattr(dataset, "prediction_input_error", lambda *args: None)
    members, exclusions, _ = dataset.grouped_members(all_members)
    cases = list(dataset.paired_cases(sources, all_members, members, ledger, games, True, exclusions, Counter()))
    assert len(cases) == (1 if conflict is None else 0)
    assert exclusions["conflicting_duplicate_result"] == (0 if conflict is None else 1)


def test_registered_checkout_rejects_dirty_or_different_code(registered_study, monkeypatch):
    # Restore the real guard deliberately stubbed by this fixture, then exercise each independent condition.
    server, study, _ = registered_study
    archive = authenticate_archive(server, study)
    monkeypatch.setattr(dataset.subprocess, "check_output", lambda command, **kwargs: "dirty" if command[1] == "status"
                        else archive.manifest["source_revision"])
    with pytest.raises(ValueError, match="clean checkout"):
        CHECKOUT_GUARD(archive)
    monkeypatch.setattr(dataset.subprocess, "check_output", lambda command, **kwargs: "" if command[1] == "status"
                        else archive.manifest["source_revision"])
    monkeypatch.setattr(dataset, "source_file_names", lambda root: [])
    monkeypatch.setattr(dataset, "research_hashes", lambda entries: {"wrong": "hash"})
    with pytest.raises(ValueError, match="differs"):
        CHECKOUT_GUARD(archive)
