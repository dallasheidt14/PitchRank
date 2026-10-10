"""Doorway B: Tier A records carry both rows' values as read, which the applier checks, and the merge
map pages in a stable order."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import find_regid_duplicate_merges as regid  # noqa: E402
from tests.unit.test_find_cross_provider_duplicates import _Supabase  # noqa: E402

PLACEHOLDER, TARGET = "pppppppp-0000-4000-8000-000000000001", "tttttttt-0000-4000-8000-000000000002"


def game(gid, home, away, date):
    return {"id": gid, "home_team_master_id": home, "away_team_master_id": away,
            "home_score": 2, "away_score": 1, "game_date": date}


def test_a_tier_a_record_carries_both_rows_as_read():
    placeholder = {"team_id_master": PLACEHOLDER, "team_name": "unknown_3100001", "provider_team_id": "3100001",
                   "club_name": None, "age_group": "u12", "gender": "Male", "state_code": None}
    target = {"team_id_master": TARGET, "team_name": "Rush 2015B Red", "provider_team_id": "123456",
              "club_name": "Rush Soccer", "age_group": "u12", "gender": "Male", "state_code": "CO",
              "is_deprecated": False}
    dates = ("2026-09-05", "2026-09-12", "2026-09-19")
    games = [game(f"p{n}", PLACEHOLDER, f"opp{n}", d) for n, d in enumerate(dates)]
    games += [game(f"t{n}", TARGET, f"opp{n}", d) for n, d in enumerate(dates)]
    db = _Supabase({"games": games, "teams": [target]}, cap=1000)

    tiers = regid.build_tiers(db, lambda tid: tid, {PLACEHOLDER: placeholder}, min_games=3)

    [record] = tiers["A"]
    assert (record["merge_id"], record["keep_id"]) == (PLACEHOLDER, TARGET)
    assert record["merge_as_vetted"] == {"age_group": "u12", "gender": "Male", "state_code": None, "club_name": None}
    assert record["keep_as_vetted"] == {
        "age_group": "u12", "gender": "Male", "state_code": "CO", "club_name": "Rush Soccer",
    }


def test_the_merge_map_is_paged_in_a_stable_order():
    rows = [{"id": f"m{n:04d}", "deprecated_team_id": f"d{n}", "canonical_team_id": f"c{n}"} for n in range(2500)]
    canon = regid.load_merge_map(_Supabase({"team_merge_map": rows}, cap=1000))
    assert [canon(f"d{n}") for n in (0, 1999, 2499)] == ["c0", "c1999", "c2499"]
