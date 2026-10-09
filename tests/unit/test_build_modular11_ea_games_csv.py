"""The EA import CSV: played games between linked teams, two rows each; impact on the 12-game line."""

import csv
import re
from pathlib import Path

from scripts import build_modular11_ea_games_csv as build

IMPORTER = Path(__file__).resolve().parents[2] / "scripts" / "import_games_enhanced.py"


def _game(match_no="1", home="7155", away="7156", hs="3", as_="1", status="played"):
    return {
        "match_no": match_no,
        "game_date": "2026-09-12",
        "age_group": "u17",
        "bracket": "EA",
        "region": "PACNW",
        "home_team_id": home,
        "away_team_id": away,
        "home_key": f"{home}:2026" if home else "",
        "away_key": f"{away}:2026" if away else "",
        "home_name": "Emerald City FC",
        "away_name": "Sparta Tacoma",
        "home_academy": "1534",
        "away_academy": "1382",
        "home_score": hs,
        "away_score": as_,
        "status": status,
        "pairing": "both",
    }


TEAMS = {
    "7155": {"provider_team_id": "7155", "display_name": "Emerald City FC", "club_name": "Emerald City FC"},
    "7156": {"provider_team_id": "7156", "display_name": "Sparta Tacoma", "club_name": "Sparta Tacoma"},
}
LINKS = {"7155:2026": "M1", "7156:2026": "M2"}


def test_played_game_with_both_linked_becomes_two_rows():
    rows, held = build.build_rows([_game()], TEAMS, LINKS)
    assert held == []
    picked = [
        (r["team_id"], r["opponent_id"], r["home_away"], r["goals_for"], r["goals_against"], r["result"]) for r in rows
    ]
    assert picked == [("7155:2026", "7156:2026", "H", 3, 1, "W"), ("7156:2026", "7155:2026", "A", 1, 3, "L")]
    assert rows[0]["provider"] == "modular11_ea"
    assert rows[0]["event_name"] == "Elite Academy League - EA"
    assert (rows[0]["age_group"], rows[0]["gender"], rows[0]["game_date"]) == ("u17", "Boys", "2026-09-12")
    assert (rows[0]["team_name"], rows[0]["opponent_name"]) == ("Emerald City FC", "Sparta Tacoma")


def test_draw_is_d():
    rows, _ = build.build_rows([_game(hs="2", as_="2")], TEAMS, LINKS)
    assert [r["result"] for r in rows] == ["D", "D"]


def test_scheduled_game_is_dropped():
    rows, held = build.build_rows([_game(hs="", as_="", status="scheduled")], TEAMS, LINKS)
    assert (rows, held) == ([], [])


def test_one_unlinked_side_is_held():
    game = _game(away="9999")
    rows, held = build.build_rows([game], TEAMS, LINKS)
    assert (rows, held) == ([], [game])


def test_blank_side_is_held():
    game = _game(away="")
    rows, held = build.build_rows([game], TEAMS, LINKS)
    assert (rows, held) == ([], [game])


def _whitelist(function_name: str) -> set[str]:
    source = IMPORTER.read_text(encoding="utf-8")
    body = source.split(f"def {function_name}(", 1)[1].split("\ndef ", 1)[0]
    return set(re.findall(r'"(\w+)": row\.get\(', body))


def test_rows_use_only_columns_both_loaders_admit():
    rows, _ = build.build_rows([_game()], TEAMS, LINKS)
    stream, load = _whitelist("stream_games_csv"), _whitelist("load_games_csv")
    assert len(stream) > 20 and len(load) > 20
    assert set(rows[0]) <= stream & load


class _Count:
    def __init__(self, db, column, value):
        self.db, self.column, self.value, self.since = db, column, value, None

    def gte(self, column, value):
        assert column == "game_date"
        self.since = value
        return self

    def limit(self, _n):
        return self

    def execute(self):
        assert self.since is not None, "count must be limited to the ranking window"
        self.db.counted.append((self.column, self.value))
        return type("R", (), {"count": self.db.stored.get((self.column, self.value), 0), "data": []})()


class _Select:
    def __init__(self, db):
        self.db = db

    def eq(self, column, value):
        return _Count(self.db, column, value)


class _Table:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def select(self, *_cols, count=None):
        assert self.name == "games" and count == "exact"
        return _Select(self.db)


class _MergePage:
    """team_merge_map paged by id, as load_merge_map reads it."""

    def __init__(self, rows):
        self.rows, self.window, self.order_by = rows, None, None

    def select(self, *_cols):
        return self

    def order(self, column):
        self.order_by = column
        return self

    def range(self, lo, hi):
        self.window = (lo, hi)
        return self

    def execute(self):
        assert self.order_by == "id"
        rows = sorted(self.rows, key=lambda r: r["id"])[self.window[0] : self.window[1] + 1]
        return type("R", (), {"data": rows})()


class _Db:
    def __init__(self, stored, merges=()):
        self.stored, self.counted, self.merges = stored, [], list(merges)

    def table(self, name):
        if name == "team_merge_map":
            return _MergePage(self.merges)
        return _Table(self, name)


def test_impact_counts_crossing_provisional_threshold(monkeypatch):
    monkeypatch.setattr(build, "PROVISIONAL_GAMES", 12)
    games = [_game(match_no=str(i), home="7155", away="7156") for i in range(3)]
    rows, _ = build.build_rows(games, TEAMS, LINKS)
    db = _Db({("home_team_master_id", "M1"): 6, ("away_team_master_id", "M1"): 4, ("home_team_master_id", "M2"): 13})
    result = build.impact(db, rows, LINKS)
    assert result == {"games_added": 3, "teams_touched": 2, "crossing_up": 1, "crossing_teams": ["M1"]}


def test_impact_follows_the_engine_threshold(monkeypatch):
    rows, _ = build.build_rows([_game()], TEAMS, LINKS)
    monkeypatch.setattr(build, "PROVISIONAL_GAMES", 2)
    result = build.impact(_Db({}), rows, LINKS)
    assert result["crossing_up"] == 0
    monkeypatch.setattr(build, "PROVISIONAL_GAMES", 1)
    assert build.impact(_Db({}), rows, LINKS)["crossing_up"] == 2


def test_planned_mode_links_created_teams_without_reading_aliases(tmp_path):
    plan = tmp_path / "link_plan.csv"
    with plan.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["provider_team_id", "key", "action", "team_id_master"])
        writer.writeheader()
        writer.writerows(
            [
                {"provider_team_id": "7155", "key": "7155:2026", "action": "link", "team_id_master": "M1"},
                {"provider_team_id": "7156", "key": "7156:2026", "action": "create", "team_id_master": ""},
                {"provider_team_id": "7157", "key": "7157:2026", "action": "hold", "team_id_master": ""},
            ]
        )
    assert build.planned_links(plan) == {"7155:2026": "M1", "7156:2026": "new:7156:2026"}


class _TeamsQuery:
    def __init__(self, rows):
        self.rows, self.ids = rows, None

    def select(self, *_cols):
        return self

    def in_(self, column, ids):
        assert column == "team_id_master" and len(ids) <= 100
        self.ids = list(ids)
        return self

    def execute(self):
        return type("R", (), {"data": [r for r in self.rows if r["team_id_master"] in self.ids]})()


class _TeamsDb:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "teams"
        return _TeamsQuery(self.rows)


def test_links_to_teams_the_importer_would_reject_are_dropped():
    rows = [
        {"team_id_master": "OK", "age_group": "u17", "gender": "Male", "is_deprecated": False},
        {"team_id_master": "AGE", "age_group": "u16", "gender": "Male", "is_deprecated": False},
        {"team_id_master": "SEX", "age_group": "u17", "gender": "Female", "is_deprecated": None},
        {"team_id_master": "DEP", "age_group": "u17", "gender": "Male", "is_deprecated": True},
    ]
    links = {"1": "OK", "2": "AGE", "3": "SEX", "4": "DEP", "5": "GONE"}
    assert build.usable_links(_TeamsDb(rows), links, "u17") == {"1": "OK"}


def test_planned_run_writes_a_preview_file_not_an_importable_one(tmp_path, monkeypatch):
    age_dir = tmp_path / "u17"
    age_dir.mkdir()
    with (age_dir / "games.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_game()))
        writer.writeheader()
        writer.writerow(_game())
    with (age_dir / "teams.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["provider_team_id", "display_name", "club_name"])
        writer.writeheader()
        writer.writerows(TEAMS.values())
    with (age_dir / "link_plan.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["provider_team_id", "key", "action", "team_id_master"])
        writer.writeheader()
        writer.writerows([{"provider_team_id": t, "key": f"{t}:2026", "action": "create", "team_id_master": ""} for t in TEAMS])
    monkeypatch.setattr(build, "_new_client", lambda: _Db({}))
    assert build.main(["--age", "u17", "--in-dir", str(tmp_path), "--planned"]) == 0
    assert (age_dir / "import_planned.csv").exists()
    assert not (age_dir / "import.csv").exists()


def test_names_come_from_the_raw_uid_while_ids_are_season_keys():
    rows, _ = build.build_rows([_game()], TEAMS, LINKS)
    assert (rows[0]["team_id"], rows[0]["team_id_source"], rows[0]["club_name"]) == ("7155:2026", "7155:2026", "Emerald City FC")


def test_season_keyed_rows_import_with_integer_scores(tmp_path):
    from scripts.import_games_enhanced import stream_games_csv

    rows, _ = build.build_rows([_game()], TEAMS, LINKS)
    path = tmp_path / "import.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=build.IMPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    [batch] = list(stream_games_csv(path))
    assert [(g["team_id"], g["opponent_id"], g["goals_for"], g["goals_against"]) for g in batch] == [
        ("7155:2026", "7156:2026", 3, 1),
        ("7156:2026", "7155:2026", 1, 3),
    ]


def test_season_keyed_rows_load_with_integer_scores(tmp_path):
    from scripts.import_games_enhanced import load_games_csv

    rows, _ = build.build_rows([_game()], TEAMS, LINKS)
    path = tmp_path / "import.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=build.IMPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    games = load_games_csv(path)
    assert [(g["team_id"], g["goals_for"], g["goals_against"]) for g in games] == [("7155:2026", 3, 1), ("7156:2026", 1, 3)]


def test_float_numeric_ids_still_lose_their_decimal(tmp_path):
    from scripts.import_games_enhanced import stream_games_csv

    path = tmp_path / "gotsport.csv"
    path.write_text("provider,team_id,opponent_id,goals_for,goals_against\ngotsport,3432.0,77.0,2,0\n", encoding="utf-8")
    [[game]] = list(stream_games_csv(path))
    assert (game["team_id"], game["opponent_id"], game["goals_for"], game["goals_against"]) == ("3432", "77", 2, 0)


class _AliasQuery:
    def __init__(self, rows):
        self.rows, self.window = rows, None

    def select(self, *_cols):
        return self

    def eq(self, *_args):
        return self

    def single(self):
        return self

    def order(self, _column):
        return self

    def range(self, lo, hi):
        self.window = (lo, hi)
        return self

    def execute(self):
        if self.window is None:
            return type("R", (), {"data": {"id": "p-ea"}})()
        return type("R", (), {"data": self.rows[self.window[0] : self.window[1] + 1]})()


class _AliasDb:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _AliasQuery(self.rows)


def test_live_links_refuse_raw_ids():
    import pytest

    with pytest.raises(SystemExit, match="migrate_modular11_ea_season_keys.py"):
        build.live_links(_AliasDb([{"provider_team_id": "7155", "team_id_master": "M1"}]))
    assert build.live_links(_AliasDb([{"provider_team_id": "7155:2026", "team_id_master": "M1"}])) == {"7155:2026": "M1"}


class _StoredQuery:
    """Records at execute(); paging needs an order and in_ batches are capped at 100."""

    def __init__(self, db, table):
        self.db, self.table, self.filters, self.order_by, self.window = db, table, [], None, None

    def select(self, *_cols):
        return self

    def in_(self, column, values):
        assert len(values) <= 100
        self.filters.append(lambda r, c=column, v=set(values): r.get(c) in v)
        return self

    def gte(self, column, value):
        self.filters.append(lambda r, c=column, v=value: r.get(c) >= v)
        return self

    def lte(self, column, value):
        self.filters.append(lambda r, c=column, v=value: r.get(c) <= v)
        return self

    def order(self, column):
        self.order_by = column
        return self

    def range(self, lo, hi):
        self.window = (lo, hi)
        return self

    def execute(self):
        rows = [dict(r) for r in self.db.rows[self.table] if all(f(r) for f in self.filters)]
        if self.window:
            assert self.order_by, "paging without an order skips rows"
            rows = sorted(rows, key=lambda r: r[self.order_by])[self.window[0] : self.window[1] + 1]
        return type("R", (), {"data": rows})()


class _StoredDb:
    def __init__(self, games=(), merges=()):
        self.rows = {"games": list(games), "team_merge_map": list(merges)}

    def table(self, name):
        return _StoredQuery(self, name)


def test_games_already_stored_are_not_counted_as_added():
    games = [_game(match_no="1"), _game(match_no="2", home="7156", away="7155", hs="0", as_="0")]
    games[1]["game_date"] = "2026-09-19"
    rows, _ = build.build_rows(games, TEAMS, LINKS)
    stored = [{"id": 1, "game_date": "2026-09-12", "home_team_master_id": "M2", "away_team_master_id": "OLD1",
               "home_score": 1, "away_score": 3}]
    db = _StoredDb(stored, [{"id": 1, "deprecated_team_id": "OLD1", "canonical_team_id": "M1"}])
    new = build.unstored_rows(db, rows, LINKS)
    assert [(r["game_date"], r["team_id"], r["goals_for"]) for r in new] == [
        ("2026-09-19", "7156:2026", 0),
        ("2026-09-19", "7155:2026", 0),
    ]


def test_planned_new_teams_have_nothing_stored():
    rows, _ = build.build_rows([_game()], TEAMS, {"7155:2026": "new:7155:2026", "7156:2026": "M2"})
    assert len(build.unstored_rows(_StoredDb(), rows, {"7155:2026": "new:7155:2026", "7156:2026": "M2"})) == 2


def test_a_stored_match_with_a_corrected_score_still_counts_as_stored():
    rows, _ = build.build_rows([_game(hs="5", as_="2")], TEAMS, LINKS)
    stored = [{"id": 1, "game_date": "2026-09-12", "home_team_master_id": "M1", "away_team_master_id": "M2",
               "home_score": 2, "away_score": 5}]
    assert build.unstored_rows(_StoredDb(stored), rows, LINKS) == []


def test_a_stored_game_with_a_blank_side_is_read_without_failing():
    rows, _ = build.build_rows([_game()], TEAMS, LINKS)
    stored = [{"id": 1, "game_date": "2026-09-12", "home_team_master_id": None, "away_team_master_id": "M2"}]
    assert len(build.unstored_rows(_StoredDb(stored), rows, LINKS)) == 2


def test_impact_counts_games_stored_under_merged_rows():
    games = [_game(match_no=str(i), home="7155", away="7156") for i in range(3)]
    rows, _ = build.build_rows(games, TEAMS, LINKS)
    db = _Db(
        {("home_team_master_id", "M1"): 6, ("away_team_master_id", "M1"): 4, ("home_team_master_id", "OLD1"): 3,
         ("home_team_master_id", "M2"): 13},
        merges=[{"id": 1, "deprecated_team_id": "OLD1", "canonical_team_id": "M1"}],
    )
    assert build.impact(db, rows, LINKS)["crossing_teams"] == []
