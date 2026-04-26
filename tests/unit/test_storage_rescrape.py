"""Unit tests for ``src.tournaments.storage.rescrape.merge_rescrape``."""

from __future__ import annotations

from src.tournaments.storage.rescrape import merge_rescrape


def _row(pid: str) -> dict:
    return {"provider_team_id": pid}


def _override(pid: str) -> dict:
    return {"provider_team_id": pid, "kind": "manual_age_group"}


def test_team_added():
    report = merge_rescrape(
        old_raw=[_row("t1")],
        new_raw=[_row("t1"), _row("t2")],
        overrides=[],
    )
    assert report.teams_added == ("t2",)


def test_team_removed_with_override():
    report = merge_rescrape(
        old_raw=[_row("t1"), _row("t2")],
        new_raw=[_row("t1")],
        overrides=[_override("t2")],
    )
    assert report.teams_removed_but_overridden == ("t2",)


def test_team_with_preserved_override():
    report = merge_rescrape(
        old_raw=[_row("t1")],
        new_raw=[_row("t1")],
        overrides=[_override("t1")],
    )
    assert report.teams_with_preserved_overrides == ("t1",)


def test_orphan_override_in_no_bucket():
    """An override for a pid never present in old or new is not surfaced."""
    report = merge_rescrape(
        old_raw=[_row("t1")],
        new_raw=[_row("t1")],
        overrides=[_override("ghost")],
    )
    assert report.teams_added == ()
    assert report.teams_removed_but_overridden == ()
    assert report.teams_with_preserved_overrides == ()


def test_team_removed_without_override_not_surfaced():
    report = merge_rescrape(
        old_raw=[_row("t1"), _row("t2")],
        new_raw=[_row("t1")],
        overrides=[],
    )
    assert report.teams_removed_but_overridden == ()


def test_combined_scenario():
    """Mixed bucket exercise: added + removed-overridden + preserved + orphan."""
    report = merge_rescrape(
        old_raw=[_row("t1"), _row("t2"), _row("t3")],
        new_raw=[_row("t1"), _row("t2"), _row("t4")],
        overrides=[_override("t1"), _override("t3"), _override("ghost")],
    )
    assert report.teams_added == ("t4",)
    assert report.teams_removed_but_overridden == ("t3",)
    assert report.teams_with_preserved_overrides == ("t1",)
