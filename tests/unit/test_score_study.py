"""Verify source-bound score candidates, fixed windows and the real capture composition."""

import json
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from src.predictions import score_study_capture as capture
from src.predictions.score_study import (
    learned_rates, score_payload, serialized, validate_definition, verified_fit,
)
from tests.score_study_fixtures import definition, parent_row, sample_artifact


def test_existing_private_bundle_is_verified_without_extracting():
    fit, bundle, _ = sample_artifact()
    assert verified_fit(bundle, definition()) == fit
    with pytest.raises(ValueError, match="backup identity"):
        verified_fit(bundle + b"changed", definition())
    manifest = definition()
    manifest["fit_receipt"]["games"] = 2
    with pytest.raises(ValueError, match="receipt"):
        verified_fit(bundle, manifest)


@pytest.mark.parametrize("change", ["start", "end", "review", "threshold", "weight", "cutoff", "live"])
def test_fixed_trial_rules_cannot_drift(change):
    m = definition()
    if change == "start":
        m["capture_start"] = "2026-11-24"
    elif change == "end":
        m["capture_end"] = "2026-12-21"
    elif change == "review":
        m["review_not_before"] = "2026-12-21"
    elif change == "threshold":
        m["policy"]["minimum_pairs"] = 20
    elif change == "weight":
        m["candidates"]["blend_25"]["challenger_weight"] = 0.5
    elif change == "cutoff":
        m["fit_receipt"]["latest_training_game"] = "2026-11-24"
    else:
        m["production_promotion"] = True
    with pytest.raises(ValueError):
        validate_definition(m)


def test_registration_must_precede_target_day():
    validate_definition(definition(), registered_at="2026-11-16T18:00:00Z")
    with pytest.raises(ValueError, match="before its first"):
        validate_definition(definition(), registered_at="2026-11-23T00:00:00Z")


def test_parameters_generate_rates_and_swap_symmetrically():
    fit, _, _ = sample_artifact()
    row = parent_row()
    rates, reason = learned_rates(row["parent_payload"]["context"], fit)
    assert reason == "eligible"
    assert rates == pytest.approx([np.exp(1.1), np.exp(0.2)])
    context = deepcopy(row["parent_payload"]["context"])
    context["teamAInput"], context["teamBInput"] = context["teamBInput"], context["teamAInput"]
    assert learned_rates(context, fit)[0] == pytest.approx(rates[::-1])
    payload = score_payload(row, definition(), fit, "f"*64)
    for arm in payload["candidates"].values():
        assert [arm["prediction"][k] for k in ("winProbabilityA", "drawProbability", "winProbabilityB", "predictedWinner")] == [0.55, 0.2, 0.25, "team_a"]
    assert payload["candidates"]["tail_guard_full"]["prediction"]["blowout4PlusProbability"] == 0.1
    assert score_payload(row, definition(), fit, "f"*64) == payload


@pytest.mark.parametrize("reason", ["cross_cohort_fallback", "unseen_team_fallback", "unseen_cohort_fallback"])
def test_missing_model_evidence_preserves_baseline_and_counts_fallback(reason):
    row, m = parent_row(), definition()
    fit, _, _ = sample_artifact()
    context = row["parent_payload"]["context"]
    if reason == "cross_cohort_fallback":
        context["teamBInput"]["age"] = 13
    elif reason == "unseen_team_fallback":
        context["teamBInput"]["team_id_master"] = "unseen"
    else:
        context["teamAInput"]["age"] = context["teamBInput"]["age"] = 13
    payload = score_payload(row, m, fit, "f"*64)
    assert payload["eligibility"] == reason and payload["learned_rates"] is None
    for candidate in payload["candidates"].values():
        assert candidate["prediction"] == row["parent_payload"]["prediction"]


def test_frozen_aliases_are_used_and_cycles_refused():
    fit, _, _ = sample_artifact()
    context = parent_row()["parent_payload"]["context"]
    context["teamAInput"]["team_id_master"] = "old"
    context["frozenEvidence"]["aliases"] = {"old": "a"}
    assert learned_rates(context, fit)[1] == "eligible"
    context["frozenEvidence"]["aliases"] = {"old": "a", "a": "old"}
    with pytest.raises(ValueError, match="Cycle"):
        learned_rates(context, fit)


class Client:
    def __init__(self, manifest, bundle):
        self.manifest, self.bundle, self.calls, self.saved = manifest, bundle, [], None
        self.baseline_signature = manifest["baseline_model_signature"]
        self.registration_answer = None
        self.signature = capture.digest(serialized(manifest).encode())
        self.storage = SimpleNamespace(from_=lambda bucket: SimpleNamespace(download=lambda name: self.bundle))

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, arguments):
        return Query(self, name, arguments)


class Query:
    def __init__(self, client, name, arguments=None):
        self.client, self.name, self.arguments = client, name, arguments
        self.selected = None

    def select(self, fields):
        self.selected = fields
        return self

    def eq(self, key, value):
        return self

    def single(self):
        return self

    def execute(self):
        c = self.client
        json.dumps(self.arguments)
        c.calls.append((self.name, self.arguments))
        if self.name == "compare_score_studies":
            data = {"manifest": c.manifest, "registered_at": "2026-11-16T18:00:00Z"}
        elif self.name == "compare_score_capture_queue":
            data = [parent_row()]
        elif self.name == "freeze_compare_score_forecast":
            c.saved = self.arguments["p_payload"]
            data = True
        elif self.name == "compare_score_forecasts":
            data = {"payload": json.loads(c.saved), "payload_sha256": capture.digest(c.saved.encode()),
                    "captured_at": "2026-11-16T18:01:00Z"}
        elif self.name == "compare_score_coverage":
            data = [{"baseline": 1, "paired": int(c.saved is not None)}]
        elif self.name == "compare_monitoring_models":
            data = {"manifest": {"model_signature": c.baseline_signature}}
        elif self.name == "register_compare_score_study":
            data = c.registration_answer or c.signature
        else:
            raise AssertionError("Unexpected query: " + self.name)
        if self.selected and self.selected != "*":
            data = {key: data[key] for key in self.selected.split(",") if key in data}
        return SimpleNamespace(data=data)


@pytest.mark.parametrize("dry_run", [True, False])
def test_capture_drives_real_composition_and_only_executes_writes_with_authorization(monkeypatch, tmp_path, dry_run):
    m = definition()
    _, bundle, _ = sample_artifact()
    client = Client(m, bundle)
    monkeypatch.setattr(capture, "source_identity", lambda root: {k: m[k] for k in ("code_revision", "execution_hashes")})
    result = capture.capture_scores(client, client.signature, tmp_path, dry_run=dry_run)
    assert result["errors"] == {} and result["eligibility"] == {"eligible": 1}
    assert result["captured"] == (0 if dry_run else 1)
    assert len([call for call in client.calls if call[0] == "freeze_compare_score_forecast"]) == (0 if dry_run else 1)
    assert not list(tmp_path.iterdir())
    assert not any(name in {"games", "prospective_match_predictions"} for name, _ in client.calls)


@pytest.mark.parametrize("dry_run", [True, False])
def test_registration_composition_preserves_dry_run_and_verifies_readback(monkeypatch, tmp_path, dry_run):
    m = definition()
    _, bundle, _ = sample_artifact()
    client = Client(m, bundle)
    monkeypatch.setattr(capture, "source_identity", lambda root: {k: m[k] for k in ("code_revision", "execution_hashes")})
    result = capture.register_study(client, m, tmp_path, dry_run=dry_run)
    assert result["registered"] is not dry_run and result["study_signature"] == client.signature
    assert sum(name == "register_compare_score_study" for name, _ in client.calls) == (0 if dry_run else 1)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mismatch", ["source", "baseline", "receipt"])
def test_registration_rejects_wrong_committed_source_baseline_or_receipt(monkeypatch, tmp_path, mismatch):
    m = definition()
    _, bundle, _ = sample_artifact()
    client = Client(m, bundle)
    identity = {key: m[key] for key in ("code_revision", "execution_hashes")}
    if mismatch == "source":
        identity["code_revision"] = "f"*40
    elif mismatch == "baseline":
        client.baseline_signature = "f"*64
    else:
        client.registration_answer = "f"*64
    monkeypatch.setattr(capture, "source_identity", lambda root: identity)
    with pytest.raises(ValueError):
        capture.register_study(client, m, tmp_path, dry_run=False)
    if mismatch != "receipt":
        assert not any(name == "register_compare_score_study" for name, _ in client.calls)


def test_explicit_dependency_graph_includes_imports_inside_executed_cli(tmp_path):
    from src.predictions.challenger_sources import candidate_execution_paths
    (tmp_path/"scripts").mkdir()
    (tmp_path/"src/predictions").mkdir(parents=True)
    (tmp_path/"requirements.lock").write_text("locked")
    (tmp_path/"src/predictions/runtime.py").write_text("RATE = 0.25\n")
    (tmp_path/"scripts/capture.py").write_text("def main():\n    from src.predictions.runtime import RATE\n")
    assert candidate_execution_paths(tmp_path, entrypoints=["scripts/capture.py"]) == {
        "scripts/capture.py", "src/predictions/runtime.py", "requirements.lock"}
