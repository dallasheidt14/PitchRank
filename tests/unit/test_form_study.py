import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from src.predictions.form_policy import ResearchPolicy
from src.predictions.form_study import committed_research_sources, register_form_study, research_hashes
from src.predictions.form_study_contract import prospective_policy, study_definition, validate_study_definition
from src.rankings.archive_storage import verify_archive
from src.rankings.input_archive import utc_now

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("registered,start", [
    ("2026-11-11T23:59:59Z", "2026-11-16"), ("2026-11-16T00:00:00Z", "2026-11-23"),
    ("2026-11-16T00:30:00+02:00", "2026-11-16"),
])
def test_future_study_uses_next_complete_utc_week_and_keeps_historical_policy(registered, start):
    policy = prospective_policy(registered)
    assert policy.development_start == start
    assert policy.minimum_games == 1000 and policy.minimum_groups == 20
    assert ResearchPolicy().development_start == "2026-08-17"
    assert ResearchPolicy().evaluation_end == "2026-11-08"
    if start == "2026-11-16":
        assert policy.development_end == "2026-12-13"
        assert policy.evaluation_start == "2026-12-14" and policy.evaluation_end == "2027-01-10"


def test_study_definition_cannot_change_thresholds_candidates_or_sealed_evaluation():
    for change in ("minimum", "candidates", "sealed", "registered_late"):
        definition = study_definition("2026-11-12T00:00:00Z", {"src/predictions/example.py": "a" * 64})
        if change == "minimum":
            definition["policy"]["minimum_games"] = 999
        elif change == "candidates":
            definition["candidates"].pop()
        elif change == "sealed":
            definition["evaluation_sealed_until_end"] = False
        timestamp = "2026-11-17T00:00:00Z" if change == "registered_late" else "2026-11-12T00:00:00Z"
        with pytest.raises(ValueError, match="fixed prospective policy"):
            validate_study_definition(definition, registered_at=timestamp)


def test_definition_does_not_share_mutable_policy_or_caller_source_hashes():
    sources = {"src/predictions/example.py": "a" * 64}
    original = study_definition("2026-11-12T00:00:00Z", sources)
    sources["src/predictions/example.py"] = "b" * 64
    original["form_configuration"]["calendar_half_lives"].append(1)
    fresh = study_definition("2026-11-12T00:00:00Z", {"src/predictions/example.py": "a" * 64})
    assert fresh["form_configuration"]["calendar_half_lives"] == [30, 60]
    validate_study_definition(fresh, registered_at="2026-11-12T00:00:00Z")


def test_registered_form_configuration_preserves_the_declared_initial_experiment():
    definition = study_definition("2026-11-12T00:00:00Z", {"src/predictions/example.py": "a" * 64})
    assert definition["candidates"] == [
        "baseline", "form_off", "residual_sequence", "residual_30", "residual_60",
        "residual_30_capped", "residual_60_capped",
    ]
    assert definition["form_configuration"] == {
        "history_size": 8, "residual_clip": 4, "calendar_half_lives": [30, 60], "opponent_weight_cap": 1,
        "normalization_and_coefficient": "collecting_predictor_unchanged",
        "missing_expectations": "neutral_and_reduce_usable_sample",
        "capped_shrinkage": "distinct_usable_opponents", "ml_trend_ablation": "development_only",
    }


@pytest.fixture
def study_archive(tmp_path):
    output = tmp_path / "study"
    (output / "objects").mkdir(parents=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    entries = committed_research_sources(ROOT, revision)
    references = {}
    for name, raw in entries:
        sha = hashlib.sha256(raw).hexdigest()
        key = f"objects/{sha}.gz"
        (output / key).write_bytes(gzip.compress(raw, mtime=0))
        references[name] = {"object": key, "sha256": sha, "bytes": len(raw), "kind": "source"}
    started = utc_now()
    manifest = {
        "schema_version": 1, "status": "complete", "source_revision": revision, "started_at": started,
        "finished_at": utc_now(), "errors": [], "queries": [], "source_files": references,
        "configuration": {"capture_kind": "compare_form_study",
                          "study_definition": study_definition(started, research_hashes(entries))},
    }
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return output, manifest


def test_study_archive_requires_complete_committed_research_sources(study_archive):
    output, manifest = study_archive
    assert verify_archive(output)[0] == manifest
    name = "src/predictions/form_research.py"
    del manifest["source_files"][name]
    del manifest["configuration"]["study_definition"]["research_sources"][name]
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="complete registered Git revision"):
        verify_archive(output)


def test_study_cannot_hide_outcome_reads_or_replace_code_hashes(study_archive):
    output, manifest = study_archive
    manifest["queries"] = [{"table": "prospective_match_predictions", "operation": "select"}]
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot contain fixture or outcome"):
        verify_archive(output)
    manifest["queries"] = []
    manifest["configuration"]["study_definition"]["research_sources"]["src/predictions/form_research.py"] = "0" * 64
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="bound to its complete research source"):
        verify_archive(output)


def test_registration_preview_never_calls_a_remote_client_or_writes_files(tmp_path):
    class NoRemote:
        def __getattr__(self, name):
            raise AssertionError("Preview attempted a remote call")

    output = tmp_path / "untouched"
    result = register_form_study(NoRemote(), ROOT, output)
    assert result["dry_run"] and not result["registered"] and not output.exists()
    validate_study_definition(result["definition"])
