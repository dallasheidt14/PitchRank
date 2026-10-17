"""The merge decider pages its game and merge-map reads in an order a unique column fixes,
so no page can skip or repeat a row."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.decide_team_merges import gather_evidence  # noqa: E402
from tests.unit.test_find_cross_provider_duplicates import _Supabase, _Table  # noqa: E402

MERGE_ID, KEEP_ID = "mmmmmmmm-0000-4000-8000-000000000001", "kkkkkkkk-0000-4000-8000-000000000002"


class _RecordingTable(_Table):
    def __init__(self, name, rows, cap, log):
        super().__init__(name, rows, cap)
        self._log = log

    def execute(self):
        if self._page is not None:
            self._log.append((self.name, self._order))
        return super().execute()


class _Recording(_Supabase):
    def __init__(self, tables, cap):
        super().__init__(tables, cap)
        self.paged = []

    def table(self, name):
        return _RecordingTable(name, self._tables[name], self._cap, self.paged)


def evidence_over_two_pages():
    """1,200 games and 2,500 merge-map rows, so both reads need a second 1,000-row page."""
    games = [
        {
            "id": f"g{n:05d}",
            "game_date": f"2025-{9 + n % 3:02d}-{1 + n % 28:02d}",
            "home_team_master_id": MERGE_ID,
            "away_team_master_id": f"opp{n % 40}",
        }
        for n in range(1200)
    ]
    merge_map = [{"deprecated_team_id": f"d{n:05d}", "canonical_team_id": f"c{n % 7}"} for n in range(2500)]
    teams = [
        {
            "team_id_master": t,
            "team_name": "Rush 2014 Red",
            "team_name_original": None,
            "gender": "Male",
            "club_name": "Rush Soccer",
            "state_code": "CO",
            "is_deprecated": False,
        }
        for t in (MERGE_ID, KEEP_ID)
    ]
    sb = _Recording({"games": games, "team_merge_map": merge_map, "team_alias_map": [], "teams": teams}, cap=1000)
    return gather_evidence(sb, [{"merge_id": MERGE_ID, "keep_id": KEEP_ID}]), sb


def test_every_paged_read_is_ordered_by_a_unique_column():
    _, sb = evidence_over_two_pages()

    assert set(sb.paged) == {("games", "id"), ("team_merge_map", "deprecated_team_id")}


def test_a_schedule_longer_than_a_page_is_read_whole():
    ev, _ = evidence_over_two_pages()

    assert len(ev["games"][MERGE_ID]) == 1200
    assert len({opp for _, opp in ev["games"][MERGE_ID]}) == 40
