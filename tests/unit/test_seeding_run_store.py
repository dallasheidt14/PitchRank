"""Unit tests for ``src.tournaments.seeding_run_store``.

Pins the round trip a seeding run must survive: the parsed rows, what the
resolver decided, and the operator's hand-entered overrides. The override map
is keyed by row position, and JSON turns integer keys into strings, so the
reload path is tested for that specifically.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_run_store import (
    SeedingRun,
    list_runs,
    load_run,
    save_run,
    slugify,
)

PASTE = "Male U14\nClub\tTeam\tState\nBarcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX\nTyler FC\tTyler FC 15B*\tTX"


def _run(name: str = "STX Cup 2026") -> SeedingRun:
    parsed = parse_roster(PASTE)
    return SeedingRun(
        name=name,
        rows=parsed.rows,
        resolved=(
            ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="master-1", provider_team_id="534748"),
            ResolvedTeam(source_index=1, status="unresolved"),
        ),
        overrides={1: {"team_id_master": "master-2", "team_name": "Tyler FC 2015"}},
        warnings=parsed.warnings,
    )


# -------- slugify ---------------------------------------------------------


def test_slugify_makes_a_filesystem_safe_name():
    assert slugify("STX Cup 2026!") == "stx-cup-2026"


def test_slugify_collapses_runs_of_separators():
    assert slugify("  A   B / C  ") == "a-b-c"


def test_slugify_refuses_a_name_with_nothing_usable():
    with pytest.raises(ValueError):
        slugify("!!!")


# -------- round trip ------------------------------------------------------


def test_saved_run_reloads_with_its_rows_intact(tmp_path):
    save_run(_run(), base_dir=tmp_path)

    loaded = load_run("stx-cup-2026", base_dir=tmp_path)

    assert [row.team_name_raw for row in loaded.rows] == ["Barcelona SC 13B Aztecas", "Tyler FC 15B*"]
    assert loaded.rows[1].has_star_marker is True
    assert loaded.rows[0].section_age_group == "u14"


def test_saved_run_reloads_with_its_resolutions_intact(tmp_path):
    save_run(_run(), base_dir=tmp_path)

    loaded = load_run("stx-cup-2026", base_dir=tmp_path)

    assert [item.status for item in loaded.resolved] == ["gotsport_id", "unresolved"]
    assert loaded.resolved[0].team_id_master == "master-1"


def test_override_keys_survive_as_integers(tmp_path):
    """JSON object keys are strings; the override map is keyed by row position."""
    save_run(_run(), base_dir=tmp_path)

    loaded = load_run("stx-cup-2026", base_dir=tmp_path)

    assert set(loaded.overrides) == {1}
    assert loaded.overrides[1]["team_name"] == "Tyler FC 2015"


def test_saving_the_same_name_twice_overwrites_rather_than_duplicating(tmp_path):
    save_run(_run(), base_dir=tmp_path)
    save_run(_run(), base_dir=tmp_path)

    assert len(list_runs(base_dir=tmp_path)) == 1


def test_saved_at_is_stamped_on_save(tmp_path):
    save_run(_run(), base_dir=tmp_path)

    assert load_run("stx-cup-2026", base_dir=tmp_path).saved_at


# -------- listing ---------------------------------------------------------


def test_list_runs_is_empty_when_nothing_has_been_saved(tmp_path):
    assert list_runs(base_dir=tmp_path) == []


def test_list_runs_reports_name_slug_and_team_count(tmp_path):
    save_run(_run(), base_dir=tmp_path)

    entry = list_runs(base_dir=tmp_path)[0]

    assert entry.slug == "stx-cup-2026"
    assert entry.name == "STX Cup 2026"
    assert entry.team_count == 2


def test_list_runs_puts_the_most_recently_saved_first(tmp_path):
    """Names chosen so alphabetical order opposes save order.

    "alpha" sorts before "beta", so a listing that merely walked the directory
    would return alpha first and this assertion would catch it.
    """
    save_run(_run("Alpha Event"), base_dir=tmp_path)
    save_run(_run("Beta Event"), base_dir=tmp_path)

    assert [entry.slug for entry in list_runs(base_dir=tmp_path)] == ["beta-event", "alpha-event"]


def test_list_runs_ignores_a_directory_that_is_not_a_saved_run(tmp_path):
    save_run(_run(), base_dir=tmp_path)
    (tmp_path / "not-a-run").mkdir()

    assert [entry.slug for entry in list_runs(base_dir=tmp_path)] == ["stx-cup-2026"]


def test_list_runs_ignores_an_unreadable_run(tmp_path):
    save_run(_run(), base_dir=tmp_path)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "seeding_run.json").write_text("{not json", encoding="utf-8")

    assert [entry.slug for entry in list_runs(base_dir=tmp_path)] == ["stx-cup-2026"]


def test_loading_a_run_that_does_not_exist_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_run("nope", base_dir=tmp_path)


def test_saved_run_preserves_frozen_forecasts_selection_policy_and_operator_review(tmp_path):
    pack = {
        "schema_version": 1, "roster_fingerprint": "captured-roster", "selected_cohorts": ["u14|Male"],
        "generated_at": "2026-09-15T18:00:00Z", "ratings_as_of": "2026-09-14", "predictor_sha256": "a" * 64,
        "teams": {"u14|Male": {"0": {"power_score_final": 0.55}, "1": {"power_score_final": 0.53}}},
        "unavailable": {"u14|Male": {}}, "ratings": {},
        "predictions": {"u14|Male": [{"entrant_a": "0", "entrant_b": "1", "expected_margin": 4.1}]},
        "policy": {"max_expected_margin": 2.0, "max_blowout_probability": 0.3},
        "manual_groups": {"u14|Male": [["0", "1"]]},
        "operator_notes": {"u14|Male": "Director requested one flight; review the mismatch."},
    }
    save_run(replace(_run(), pack=pack), base_dir=tmp_path)
    loaded = load_run("stx-cup-2026", base_dir=tmp_path)
    assert loaded.pack == pack
    assert loaded.overrides[1]["team_id_master"] == "master-2"
    assert loaded.rows[1].has_star_marker


def test_legacy_saved_run_without_pack_remains_loadable(tmp_path):
    path = save_run(_run(), base_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["pack"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_run("stx-cup-2026", base_dir=tmp_path)
    assert loaded.pack is None
    assert loaded.rows == _run().rows
    assert loaded.overrides == _run().overrides


def test_failed_pack_serialization_preserves_the_previous_saved_run_bytes(tmp_path):
    path = save_run(replace(_run(), pack={"operator_notes": {"u14|Male": "Reviewed"}}), base_dir=tmp_path)
    original = path.read_bytes()
    with pytest.raises(TypeError, match="not JSON serializable"):
        save_run(replace(_run(), pack={"invalid": object()}), base_dir=tmp_path)
    assert path.read_bytes() == original
    assert load_run("stx-cup-2026", base_dir=tmp_path).pack == {"operator_notes": {"u14|Male": "Reviewed"}}
    assert not path.with_name(path.name + ".tmp").exists()
