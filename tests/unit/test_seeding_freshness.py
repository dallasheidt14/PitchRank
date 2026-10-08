from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.tournaments.seeding_freshness import (
    acknowledge_freshness, check_freshness, freshness_note, freshness_ready, snapshot_identity,
)


def pack():
    return {"selected_cohorts": ["u14|Male"], "predictor_sha256": "a" * 64,
            "input_digests": {"u14|Male": "b" * 64}, "generated_at": "2026-09-28T00:00:00Z"}


def test_check_does_not_change_snapshot_and_reopening_is_not_a_fresh_check():
    saved = pack()
    before = deepcopy(saved)
    check = check_freshness(saved, SimpleNamespace(input_digests=saved["input_digests"], predictor_sha256="a"*64))
    assert saved == before
    saved["freshness_check"] = check
    assert check["status"] == "verified_current"
    assert freshness_ready(saved, snapshot_identity(saved))
    assert not freshness_ready(saved)
    assert "Not checked in this session" in freshness_note(saved)


@pytest.mark.parametrize("changed", ["history", "model"])
def test_changed_inputs_report_newer_data(changed):
    saved = pack()
    batch = SimpleNamespace(input_digests={"u14|Male": "c"*64 if changed == "history" else "b"*64},
                            predictor_sha256="c"*64 if changed == "model" else "a"*64)
    assert check_freshness(saved, batch)["status"] == "newer_inputs_available"


def test_legacy_snapshot_cannot_claim_verified_freshness():
    saved = pack()
    saved.pop("input_digests")
    batch = SimpleNamespace(input_digests={"u14|Male": "b"*64}, predictor_sha256="a"*64)
    assert check_freshness(saved, batch)["status"] == "not_checked"


def test_acknowledgment_requires_reason_survives_restart_and_expires_on_changes():
    saved = pack()
    with pytest.raises(ValueError):
        acknowledge_freshness(saved, " ")
    saved["freshness_acknowledgment"] = acknowledge_freshness(saved, "Reviewed with the director")
    assert freshness_ready(deepcopy(saved))
    assert "Reviewed with the director" in freshness_note(saved)
    saved["manual_seed_orders"] = {"u14|Male": {"seeded": ["2", "1"], "held": []}}
    assert not freshness_ready(saved)
