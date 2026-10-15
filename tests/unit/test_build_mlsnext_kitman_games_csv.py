"""The Kitman import CSV: played games in the season window between linked, same-board teams; two rows each."""

import csv
import re
from datetime import date
from pathlib import Path

import pytest

from scripts import build_mlsnext_kitman_games_csv as build

IMPORTER = Path(__file__).resolve().parents[2] / "scripts" / "import_games_enhanced.py"
SINCE, TODAY = "2026-08-01", "2026-10-14"


def _squad(sid, club, age="u16", division="HD"):
    return {
        "provider_team_id": sid,
        "key": f"{sid}:2026",
        "club_name": club,
        "display_name": f"{club} U{age[1:]} {division}",
        "age_group": age,
        "division": division,
    }


SQUADS = {
    s["provider_team_id"]: s
    for s in [
        _squad("10", "Alpha SC"),
        _squad("11", "Beta FC"),
        _squad("12", "Gamma FC", age="u15"),
        _squad("13", "Delta FC"),
    ]
}
LINKS = {"10:2026": "M1", "11:2026": "M2", "12:2026": "M3"}


def _game(home="10", away="11", hs="3", as_="1", status="played", date="2026-09-12", division="HD", competition="League"):
    return {
        "event_id": "500",
        "game_date": date,
        "status": status,
        "division": division,
        "competition": competition,
        "age_group": "u16",
        "home_squad_id": home,
        "away_squad_id": away,
        "home_key": f"{home}:2026" if home else "",
        "away_key": f"{away}:2026" if away else "",
        "home_score": hs,
        "away_score": as_,
    }


def _build(games, links=LINKS, squads=SQUADS):
    return build.build_rows(games, squads, links, SINCE, TODAY)


def test_a_played_game_between_linked_teams_becomes_two_rows():
    rows, held = _build([_game()])
    assert held == []
    picked = [(r["team_id"], r["opponent_id"], r["home_away"], r["goals_for"], r["goals_against"], r["result"]) for r in rows]
    assert picked == [("10:2026", "11:2026", "H", 3, 1, "W"), ("11:2026", "10:2026", "A", 1, 3, "L")]
    first = rows[0]
    assert first["provider"] == "mlsnext_kitman"
    assert (first["age_group"], first["gender"], first["game_date"]) == ("u16", "Boys", "2026-09-12")
    assert (first["team_name"], first["opponent_name"]) == ("Alpha SC U16 HD", "Beta FC U16 HD")
    assert (first["event_name"], first["competition"], first["division_name"]) == ("MLS NEXT HD - League", "League", "HD")


def test_a_draw_is_d_and_zero_zero_counts():
    rows, _ = _build([_game(hs="0", as_="0")])
    assert [r["result"] for r in rows] == ["D", "D"] and rows[0]["goals_for"] == 0


def test_a_scheduled_game_is_dropped():
    assert _build([_game(hs="", as_="", status="scheduled")]) == ([], [])


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"date": "2026-10-15"}, "completed but dated in the future"),
        ({"date": "2026-07-31"}, "before the season window"),
        ({"away": "13"}, "a team is not linked"),
        ({"away": ""}, "a squad label is not a board age"),
        ({"away": "12"}, "the two squads are on different boards"),
    ],
)
def test_a_game_that_cannot_be_imported_is_held_with_its_reason(changes, reason):
    game = _game(**changes)
    rows, held = _build([game])
    assert rows == [] and [(h["event_id"], h["hold_reason"]) for h in held] == [("500", reason)]


def test_the_window_includes_both_edges():
    rows, held = _build([_game(date=SINCE), _game(date=TODAY)])
    assert held == [] and len(rows) == 4


def test_a_game_is_held_when_only_the_away_squad_is_unlinked_and_when_only_the_home_is():
    _, held = _build([_game(home="13", away="11"), _game(home="10", away="13")])
    assert [h["hold_reason"] for h in held] == ["a team is not linked"] * 2


def test_the_future_check_comes_before_the_link_check():
    _, held = _build([_game(date="2026-12-01", away="13")])
    assert held[0]["hold_reason"] == "completed but dated in the future"


def _whitelist(function_name: str) -> set[str]:
    source = IMPORTER.read_text(encoding="utf-8")
    body = source.split(f"def {function_name}(", 1)[1].split("\ndef ", 1)[0]
    return set(re.findall(r'"(\w+)": row\.get\(', body))


def test_rows_use_only_columns_both_loaders_admit():
    rows, _ = _build([_game()])
    stream, load = _whitelist("stream_games_csv"), _whitelist("load_games_csv")
    assert len(stream) > 20 and len(load) > 20
    assert set(rows[0]) <= stream & load
    assert list(rows[0]) == build.IMPORT_COLUMNS


def test_planned_links_count_a_create_as_new_and_a_keep_as_linked(tmp_path):
    path = tmp_path / "link_plan.csv"
    rows = [
        {"key": "1:2026", "action": "link", "team_id_master": "T1"},
        {"key": "2:2026", "action": "keep", "team_id_master": "T2"},
        {"key": "3:2026", "action": "create", "team_id_master": ""},
        {"key": "4:2026", "action": "hold", "team_id_master": ""},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["key", "action", "team_id_master"])
        writer.writeheader()
        writer.writerows(rows)
    assert build.planned_links(path) == {"1:2026": "T1", "2:2026": "T2", "3:2026": "new:3:2026"}


class _Teams:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def in_(self, _col, ids):
        self.ids = ids
        return self

    def execute(self):
        class R:
            pass

        result = R()
        result.data = [r for r in self.rows if r["team_id_master"] in self.ids]
        return result


def test_usable_links_keep_only_a_team_on_the_squads_own_board():
    rows = [
        {"team_id_master": "OK", "age_group": "u16", "gender": "Male", "is_deprecated": None},
        {"team_id_master": "AGE", "age_group": "u15", "gender": "Male", "is_deprecated": False},
        {"team_id_master": "SEX", "age_group": "u16", "gender": "Female", "is_deprecated": False},
        {"team_id_master": "DEP", "age_group": "u16", "gender": "Male", "is_deprecated": True},
        {"team_id_master": "UPPER", "age_group": "U16", "gender": "Male", "is_deprecated": False},
    ]
    links = {"1:2026": "OK", "2:2026": "AGE", "3:2026": "SEX", "4:2026": "DEP", "5:2026": "GONE", "6:2026": "UPPER"}
    ages = {key: "u16" for key in links}
    assert build.usable_links(_Teams(rows), links, ages) == {"1:2026": "OK", "6:2026": "UPPER"}


def test_a_link_is_judged_against_its_own_squads_age():
    rows = [{"team_id_master": "T", "age_group": "u15", "gender": "Male", "is_deprecated": False}]
    assert build.usable_links(_Teams(rows), {"1:2026": "T"}, {"1:2026": "u15"}) == {"1:2026": "T"}
    assert build.usable_links(_Teams(rows), {"1:2026": "T"}, {"1:2026": "u16"}) == {}


def _write(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_a_planned_run_writes_a_preview_file_not_an_importable_one(tmp_path, monkeypatch, capsys):
    games = [_game(date=date.today().isoformat())]
    _write(tmp_path / "games.csv", list(games[0]), games)
    _write(tmp_path / "squads.csv", list(SQUADS["10"]), list(SQUADS.values()))
    _write(
        tmp_path / "link_plan.csv",
        ["provider_team_id", "key", "action", "team_id_master"],
        [{"provider_team_id": sid, "key": f"{sid}:2026", "action": "create", "team_id_master": ""} for sid in SQUADS],
    )
    monkeypatch.setattr(build, "_new_client", lambda: object())
    assert build.main(["--in-dir", str(tmp_path), "--planned"]) == 0
    assert (tmp_path / "import_planned.csv").exists() and not (tmp_path / "import.csv").exists()
    assert (tmp_path / "held_games.csv").exists()
    assert "games_added=1" in capsys.readouterr().out


class _Result:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Query:
    """Applies filters, ordering and windows at execute() and returns only the selected columns."""

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.columns, self.want_count = None, False
        self.checks, self.sort, self.window, self.cap = [], None, None, None

    def select(self, columns="*", count=None):
        self.columns = None if columns == "*" else [c.strip() for c in columns.split(",")]
        self.want_count = count == "exact"
        return self

    def eq(self, column, value):
        self.checks.append(lambda r: r.get(column) == value)
        return self

    def in_(self, column, values):
        assert len(values) <= 100
        self.checks.append(lambda r: r.get(column) in set(values))
        return self

    def gte(self, column, value):
        self.checks.append(lambda r: str(r.get(column)) >= value)
        return self

    def lte(self, column, value):
        self.checks.append(lambda r: str(r.get(column)) <= value)
        return self

    def order(self, column):
        self.sort = column
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def limit(self, count):
        self.cap = count
        return self

    def execute(self):
        rows = [r for r in self.db.rows[self.table] if all(check(r) for check in self.checks)]
        total = len(rows)
        if self.sort:
            rows = sorted(rows, key=lambda r: r[self.sort])
        if self.window:
            rows = rows[self.window[0] : self.window[1] + 1]
        if self.cap is not None:
            rows = rows[: self.cap]
        rows = [{c: r.get(c) for c in self.columns} if self.columns else dict(r) for r in rows]
        return _Result(rows, count=total if self.want_count else None)


class _Db:
    def __init__(self, **tables):
        self.rows = {"providers": [], "team_alias_map": [], "teams": [], "team_merge_map": [], "games": [], **tables}

    def table(self, name):
        return _Query(self, name)


PROVIDER = "prov-kitman"


def _alias(aid, key, master, status="approved", provider=PROVIDER):
    return {"id": aid, "provider_id": provider, "provider_team_id": key, "team_id_master": master, "review_status": status}


def _live_db(aliases):
    return _Db(
        providers=[{"id": PROVIDER, "code": "mlsnext_kitman"}],
        team_alias_map=aliases,
        teams=[{"team_id_master": m, "age_group": "u16", "gender": "Male", "is_deprecated": None} for m in ("M1", "M2")],
    )


def test_live_links_read_every_page_of_approved_aliases_only(monkeypatch):
    monkeypatch.setattr(build, "PAGE_SIZE", 2)
    aliases = [
        _alias(1, "10:2026", "M1"),
        _alias(2, "11:2026", "M2"),
        _alias(3, "12:2026", "M3"),
        _alias(4, "13:2026", "M4", status="pending"),
        _alias(5, "14:2026", "M5", provider="another-provider"),
        _alias(6, "15:2026", "M6"),
    ]
    assert build.live_links(_live_db(aliases)) == {"10:2026": "M1", "11:2026": "M2", "12:2026": "M3", "15:2026": "M6"}


def test_live_links_refuse_an_id_without_a_season():
    with pytest.raises(SystemExit, match="not season-keyed"):
        build.live_links(_live_db([_alias(1, "10", "M1")]))


def test_live_links_stop_when_the_provider_is_not_seeded():
    with pytest.raises(SystemExit, match="apply migration 20261015120000"):
        build.live_links(_Db())


def test_a_live_run_imports_games_between_linked_teams_and_holds_the_rest(tmp_path, monkeypatch, capsys):
    today = date.today().isoformat()
    games = [_game(date=today), _game(home="10", away="13", date=today)]
    _write(tmp_path / "games.csv", list(games[0]), games)
    squads = [s for s in SQUADS.values()]
    _write(tmp_path / "squads.csv", list(squads[0]), squads)
    db = _live_db([_alias(1, "10:2026", "M1"), _alias(2, "11:2026", "M2")])
    monkeypatch.setattr(build, "_new_client", lambda: db)
    assert build.main(["--in-dir", str(tmp_path)]) == 0
    imported = list(csv.DictReader((tmp_path / "import.csv").open(encoding="utf-8")))
    assert [(r["team_id"], r["opponent_id"]) for r in imported] == [("10:2026", "11:2026"), ("11:2026", "10:2026")]
    held = list(csv.DictReader((tmp_path / "held_games.csv").open(encoding="utf-8")))
    assert [h["hold_reason"] for h in held] == ["a team is not linked"]
    assert not (tmp_path / "import_planned.csv").exists()
    assert "games_added=1" in capsys.readouterr().out


def test_a_live_link_to_a_team_on_another_board_holds_that_squads_games(tmp_path, monkeypatch, capsys):
    games = [_game(date=date.today().isoformat())]
    _write(tmp_path / "games.csv", list(games[0]), games)
    squads = list(SQUADS.values())
    _write(tmp_path / "squads.csv", list(squads[0]), squads)
    db = _live_db([_alias(1, "10:2026", "M1"), _alias(2, "11:2026", "M2")])
    db.rows["teams"][1]["age_group"] = "u15"
    monkeypatch.setattr(build, "_new_client", lambda: db)
    assert build.main(["--in-dir", str(tmp_path)]) == 0
    assert "Dropped 1 links" in capsys.readouterr().out
    assert list(csv.DictReader((tmp_path / "import.csv").open(encoding="utf-8"))) == []


def test_a_season_key_survives_the_importers_id_conversion_in_both_loaders(tmp_path):
    from scripts import import_games_enhanced as importer

    rows, _ = _build([_game()])
    _write(tmp_path / "import.csv", build.IMPORT_COLUMNS, rows)
    streamed = [g for batch in importer.stream_games_csv(tmp_path / "import.csv") for g in batch]
    loaded = importer.load_games_csv(tmp_path / "import.csv")
    for games in (streamed, loaded):
        assert [(g["team_id"], g["opponent_id"]) for g in games] == [("10:2026", "11:2026"), ("11:2026", "10:2026")]
