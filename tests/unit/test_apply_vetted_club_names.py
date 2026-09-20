"""Unit tests for scripts/apply_vetted_club_names.py.

The script moves teams filed under the wrong club. Two things carry the risk: the
vetted list has to still describe the database when it is applied, and the log has
to survive, because ``--revert`` reads it and it is the only way back.
"""

from datetime import datetime

import pytest

from scripts.apply_vetted_club_names import plan, resolve_log_path


def _entry(team_id="t1", from_club="Crossfire Select Soccer Club", to_club="Bellevue United FC"):
    return {"team_id_master": team_id, "from_club": from_club, "to_club": to_club, "evidence": "name says BUFC"}


def _row(team_id="t1", club="Crossfire Select Soccer Club", deprecated=False):
    return {"team_id_master": team_id, "team_name": "BUFC B14 Blue", "club_name": club, "is_deprecated": deprecated}


class TestResolveLogPath:
    def test_the_default_carries_a_timestamp_so_two_runs_cannot_collide(self):
        first = resolve_log_path(None, datetime(2026, 9, 20, 23, 45, 1))
        second = resolve_log_path(None, datetime(2026, 9, 20, 23, 45, 2))

        assert first != second
        assert first.name == "club_name_changes_20260920_234501.csv"

    def test_a_named_file_is_used_as_given(self, tmp_path):
        wanted = tmp_path / "batch.csv"

        assert resolve_log_path(wanted) == wanted

    def test_an_existing_log_stops_the_run(self, tmp_path):
        """Overwriting it would destroy the record of the batch it describes."""
        already = tmp_path / "batch.csv"
        already.write_text("team_id_master\n", encoding="utf-8")

        with pytest.raises(FileExistsError):
            resolve_log_path(already)


class TestPlan:
    def test_a_row_still_matching_the_vetted_list_is_applied(self):
        apply_now, stale = plan([_entry()], {"t1": _row()})

        assert [e["team_id_master"] for e in apply_now] == ["t1"]
        assert stale == []

    def test_a_row_whose_club_moved_since_vetting_is_skipped(self):
        """Someone else corrected it, or corrected it differently; do not overwrite blind."""
        apply_now, stale = plan([_entry()], {"t1": _row(club="Some Other Club")})

        assert apply_now == []
        assert "Some Other Club" in stale[0]

    def test_a_row_already_at_the_target_is_skipped(self):
        apply_now, stale = plan([_entry()], {"t1": _row(club="Bellevue United FC")})

        assert apply_now == []
        assert "already" in stale[0]

    def test_a_deprecated_row_is_skipped(self):
        apply_now, stale = plan([_entry()], {"t1": _row(deprecated=True)})

        assert apply_now == []
        assert "deprecated" in stale[0]

    def test_a_row_that_no_longer_exists_is_skipped(self):
        apply_now, stale = plan([_entry()], {})

        assert apply_now == []
        assert "no such team" in stale[0]

    def test_each_skip_names_the_team_it_is_about(self):
        apply_now, stale = plan([_entry("t1"), _entry("t2")], {"t1": _row("t1", club="Moved")})

        assert apply_now == []
        assert {"t1", "t2"} == {reason.split(":")[0] for reason in stale}
