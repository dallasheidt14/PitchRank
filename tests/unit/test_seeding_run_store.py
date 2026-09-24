"""Unit tests for ``src.tournaments.seeding_run_store``.

Pins the round trip a seeding run must survive: the parsed rows, what the
resolver decided, and the operator's hand-entered overrides. The override map
is keyed by row position, and JSON turns integer keys into strings, so the
reload path is tested for that specifically.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import src.tournaments.seeding_run_store as seeding_run_store
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


def _linked_worktree(tmp_path: Path, *, relative_gitdir: bool = False) -> tuple[Path, Path]:
    primary = tmp_path / "primary"
    common_git = primary / ".git"
    git_dir = common_git / "worktrees" / "preview"
    git_dir.mkdir(parents=True)
    (git_dir / "commondir").write_text("../..\n", encoding="utf-8")

    linked = tmp_path / "preview"
    linked.mkdir()
    target = git_dir
    if relative_gitdir:
        target = Path("..") / "primary" / ".git" / "worktrees" / "preview"
    (linked / ".git").write_text(f"gitdir: {target}\n", encoding="utf-8")
    return primary, linked


# -------- default location ------------------------------------------------


def test_default_base_dir_uses_the_primary_checkout_from_a_linked_worktree(
    tmp_path, monkeypatch
):
    primary, linked = _linked_worktree(tmp_path)
    monkeypatch.setattr(seeding_run_store, "_PROJECT_ROOT", linked)
    monkeypatch.delenv("MATCHBALANCE_SEEDING_DIR", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert seeding_run_store.default_base_dir() == primary / "reports" / "seeding"


def test_default_base_dir_uses_a_normal_checkout_with_a_git_directory(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.setattr(seeding_run_store, "_PROJECT_ROOT", checkout)
    monkeypatch.delenv("MATCHBALANCE_SEEDING_DIR", raising=False)

    assert seeding_run_store.default_base_dir() == checkout / "reports" / "seeding"


def test_default_base_dir_accepts_a_relative_linked_worktree_gitdir(tmp_path, monkeypatch):
    primary, linked = _linked_worktree(tmp_path, relative_gitdir=True)
    monkeypatch.setattr(seeding_run_store, "_PROJECT_ROOT", linked)
    monkeypatch.delenv("MATCHBALANCE_SEEDING_DIR", raising=False)

    assert seeding_run_store.default_base_dir() == primary / "reports" / "seeding"


def test_default_base_dir_uses_the_checkout_when_git_metadata_is_absent(tmp_path, monkeypatch):
    checkout = tmp_path / "unpacked"
    checkout.mkdir()
    monkeypatch.setattr(seeding_run_store, "_PROJECT_ROOT", checkout)
    monkeypatch.delenv("MATCHBALANCE_SEEDING_DIR", raising=False)

    assert seeding_run_store.default_base_dir() == checkout / "reports" / "seeding"


def test_default_base_dir_ignores_git_metadata_that_points_outside_the_common_repo(
    tmp_path, monkeypatch
):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    outside_git_dir = tmp_path / "outside" / "linked-metadata"
    outside_git_dir.mkdir(parents=True)
    rogue_common = tmp_path / "rogue" / ".git"
    rogue_common.mkdir(parents=True)
    (outside_git_dir / "commondir").write_text(str(rogue_common), encoding="utf-8")
    (checkout / ".git").write_text(f"gitdir: {outside_git_dir}\n", encoding="utf-8")
    monkeypatch.setattr(seeding_run_store, "_PROJECT_ROOT", checkout)
    monkeypatch.delenv("MATCHBALANCE_SEEDING_DIR", raising=False)

    assert seeding_run_store.default_base_dir() == checkout / "reports" / "seeding"


def test_default_base_dir_honors_an_absolute_operator_override(tmp_path, monkeypatch):
    configured = tmp_path / "durable" / "seeding"
    monkeypatch.setenv("MATCHBALANCE_SEEDING_DIR", str(configured))

    assert seeding_run_store.default_base_dir() == configured


def test_relative_operator_override_is_anchored_to_the_shared_checkout(tmp_path, monkeypatch):
    primary, linked = _linked_worktree(tmp_path)
    monkeypatch.setattr(seeding_run_store, "_PROJECT_ROOT", linked)
    monkeypatch.setenv("MATCHBALANCE_SEEDING_DIR", "operator-data/seeding")

    assert seeding_run_store.default_base_dir() == primary / "operator-data" / "seeding"


def test_blank_operator_override_keeps_the_shared_default(tmp_path, monkeypatch):
    primary, linked = _linked_worktree(tmp_path)
    monkeypatch.setattr(seeding_run_store, "_PROJECT_ROOT", linked)
    monkeypatch.setenv("MATCHBALANCE_SEEDING_DIR", "   ")

    assert seeding_run_store.default_base_dir() == primary / "reports" / "seeding"


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
    run = _run()
    run = replace(
        run,
        rows=(
            replace(run.rows[0], requested_flight="Gold"),
            replace(run.rows[1], listed_division="U14 Boys Silver"),
        ),
    )
    save_run(run, base_dir=tmp_path)

    loaded = load_run("stx-cup-2026", base_dir=tmp_path)

    assert [row.team_name_raw for row in loaded.rows] == ["Barcelona SC 13B Aztecas", "Tyler FC 15B*"]
    assert loaded.rows[1].has_star_marker is True
    assert loaded.rows[0].section_age_group == "u14"
    assert loaded.rows[0].requested_flight == "Gold"
    assert loaded.rows[1].listed_division == "U14 Boys Silver"


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


def test_saved_run_retains_the_source_event_url(tmp_path):
    run = replace(_run(), source_url="https://system.gotsport.com/org_event/events/55368")
    save_run(run, base_dir=tmp_path)

    assert load_run("stx-cup-2026", base_dir=tmp_path).source_url.endswith("/55368")


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


def test_legacy_saved_rows_without_flight_fields_use_blank_defaults(tmp_path):
    path = save_run(_run(), base_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload["rows"]:
        row.pop("requested_flight", None)
        row.pop("listed_division", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_run("stx-cup-2026", base_dir=tmp_path)

    assert all(row.requested_flight == "" for row in loaded.rows)
    assert all(row.listed_division == "" for row in loaded.rows)


def test_failed_pack_serialization_preserves_the_previous_saved_run_bytes(tmp_path):
    path = save_run(replace(_run(), pack={"operator_notes": {"u14|Male": "Reviewed"}}), base_dir=tmp_path)
    original = path.read_bytes()
    with pytest.raises(TypeError, match="not JSON serializable"):
        save_run(replace(_run(), pack={"invalid": object()}), base_dir=tmp_path)
    assert path.read_bytes() == original
    assert load_run("stx-cup-2026", base_dir=tmp_path).pack == {"operator_notes": {"u14|Male": "Reviewed"}}
    assert not path.with_name(path.name + ".tmp").exists()


@pytest.mark.parametrize("damaged", [b'{"rows": [', b'\xff\xfe\x00', b''])
def test_save_recovers_from_damaged_previous_file_and_preserves_its_bytes(tmp_path, damaged):
    path = save_run(_run(), base_dir=tmp_path)
    path.write_bytes(damaged)

    updated = replace(_run(), pack={"operator_notes": {"u14|Male": "Reviewed"}})
    save_run(updated, base_dir=tmp_path)

    recovered = load_run("stx-cup-2026", base_dir=tmp_path)
    assert recovered.rows == updated.rows
    assert recovered.overrides == updated.overrides
    assert recovered.pack == updated.pack
    archives = list((path.parent / "history").glob("*.json"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == damaged


def test_archive_failure_preserves_previous_save(tmp_path):
    path = save_run(_run(), base_dir=tmp_path)
    original = path.read_bytes()
    (path.parent / "history").write_text("Cannot create an archive directory here", encoding="utf-8")

    with pytest.raises(OSError):
        save_run(replace(_run(), rows=()), base_dir=tmp_path)

    assert path.read_bytes() == original


# -------- a save never replaces a different run ---------------------------

EVENT_111 = "https://system.gotsport.com/org_event/events/111"
EVENT_222 = "https://system.gotsport.com/org_event/events/222"


def _event_run(url: str, coverage: str = "complete", name: str = "STX Cup 2026") -> SeedingRun:
    return replace(_run(name), source_url=url, assessment={"coverage": coverage})


def test_a_name_that_slugifies_onto_another_run_is_refused_naming_it(tmp_path):
    first = save_run(_run("STX Cup (Boys)"), base_dir=tmp_path)
    before = first.read_bytes()

    with pytest.raises(seeding_run_store.RunNameTaken) as refused:
        save_run(_run("STX Cup - Boys"), base_dir=tmp_path)

    assert refused.value.existing == "STX Cup (Boys)"
    assert first.read_bytes() == before
    assert not (first.parent / "history").exists()


def test_a_damaged_save_can_still_be_replaced_under_any_spelling(tmp_path):
    target = tmp_path / slugify("STX Cup (Boys)")
    target.mkdir()
    (target / seeding_run_store.RUN_FILENAME).write_text("{not json", encoding="utf-8")

    save_run(_run("STX Cup - Boys"), base_dir=tmp_path)

    assert load_run(target.name, base_dir=tmp_path).name == "STX Cup - Boys"


def test_another_event_is_refused_under_a_saved_events_name(tmp_path):
    first = save_run(_event_run(EVENT_111), base_dir=tmp_path)
    before = first.read_bytes()

    with pytest.raises(seeding_run_store.RunSourceChanged) as refused:
        save_run(_event_run(EVENT_222), base_dir=tmp_path)

    assert refused.value.existing == "STX Cup 2026"
    assert first.read_bytes() == before


def test_the_event_id_in_the_assessment_counts_as_the_source(tmp_path):
    save_run(replace(_run(), assessment={"event_id": "111", "coverage": "complete"}), base_dir=tmp_path)

    with pytest.raises(seeding_run_store.RunSourceChanged):
        save_run(replace(_run(), assessment={"event_id": "222", "coverage": "complete"}), base_dir=tmp_path)


def test_rewalking_the_same_event_replaces_it(tmp_path):
    save_run(_event_run(EVENT_111), base_dir=tmp_path)

    save_run(_event_run(EVENT_111), base_dir=tmp_path)

    assert len(list((tmp_path / "stx-cup-2026" / "history").glob("*.json"))) == 1


def test_a_partial_walk_never_replaces_a_complete_one(tmp_path):
    save_run(_event_run(EVENT_111), base_dir=tmp_path)

    with pytest.raises(seeding_run_store.RunSourceChanged):
        save_run(_event_run(EVENT_111, coverage="probe"), base_dir=tmp_path)


def test_a_complete_walk_replaces_a_partial_one(tmp_path):
    save_run(_event_run(EVENT_111, coverage="probe"), base_dir=tmp_path)

    save_run(_event_run(EVENT_111), base_dir=tmp_path)

    assert load_run("stx-cup-2026", base_dir=tmp_path).assessment["coverage"] == "complete"


def test_a_corrected_paste_replaces_the_pasted_run(tmp_path):
    save_run(_run(), base_dir=tmp_path)
    edited = parse_roster(PASTE + "\nTyler FC\tTyler FC 15B White\tTX")

    save_run(replace(_run(), rows=edited.rows), base_dir=tmp_path)

    assert len(load_run("stx-cup-2026", base_dir=tmp_path).rows) == 3


def test_an_older_save_named_for_its_event_counts_as_that_event(tmp_path):
    save_run(_run("GotSport Event 111 · U10 Probe"), base_dir=tmp_path)

    save_run(_event_run(EVENT_111, coverage="probe", name="GotSport Event 111 · U10 Probe"), base_dir=tmp_path)
    with pytest.raises(seeding_run_store.RunSourceChanged):
        save_run(_run("GotSport Event 111 · U10 Probe"), base_dir=tmp_path)


def test_a_paste_named_like_an_event_is_still_a_paste(tmp_path):
    pasted = replace(_run("GotSport Event 111 · Pasted"), assessment={"source_kind": "Paste team list"})
    save_run(pasted, base_dir=tmp_path)

    save_run(replace(pasted, rows=parse_roster(PASTE + "\nTyler FC\tTyler FC 15B White\tTX").rows), base_dir=tmp_path)

    assert len(load_run("gotsport-event-111-pasted", base_dir=tmp_path).rows) == 3


def test_a_save_with_a_damaged_assessment_still_compares_by_its_url(tmp_path):
    path = save_run(_event_run(EVENT_111), base_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**payload, "assessment": ["bad"]}), encoding="utf-8")

    save_run(_event_run(EVENT_111, coverage="probe"), base_dir=tmp_path)
    with pytest.raises(seeding_run_store.RunSourceChanged):
        save_run(_event_run(EVENT_222), base_dir=tmp_path)


def test_a_partial_walk_is_refused_as_less_complete_not_as_another_roster(tmp_path):
    save_run(_event_run(EVENT_111), base_dir=tmp_path)

    with pytest.raises(seeding_run_store.RunSourceChanged) as partial:
        save_run(_event_run(EVENT_111, coverage="partial"), base_dir=tmp_path)
    with pytest.raises(seeding_run_store.RunSourceChanged) as other:
        save_run(_event_run(EVENT_222), base_dir=tmp_path)

    assert partial.value.less_complete is True
    assert other.value.less_complete is False


@pytest.mark.parametrize(
    ("saved_url", "new_url"),
    [("", EVENT_111), (EVENT_111, "")],
    ids=["event over paste", "paste over event"],
)
def test_a_paste_and_an_event_are_different_runs(tmp_path, saved_url, new_url):
    save_run(_event_run(saved_url), base_dir=tmp_path)

    with pytest.raises(seeding_run_store.RunSourceChanged):
        save_run(_event_run(new_url), base_dir=tmp_path)
