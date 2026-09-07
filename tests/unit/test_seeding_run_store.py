"""Unit tests for ``src.tournaments.seeding_run_store``.

Pins the round trip a seeding run must survive: the parsed rows, what the
resolver decided, and the operator's hand-entered overrides. The override map
is keyed by row position, and JSON turns integer keys into strings, so the
reload path is tested for that specifically.
"""

from __future__ import annotations

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
