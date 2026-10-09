"""Schedule evidence and lineage for EA matching: a squad that was busy elsewhere is not this team."""

from scripts import match_modular11_ea_teams as m
from scripts.match_modular11_ea_teams import EaTeam, classify, lineage_target, schedule_conflict


def _g(day, name, club=None):
    return {"game_date": f"2026-09-{day:02d}", "opponent_name": name, "opponent_club": club}


EA_GAMES = [_g(12, "Sparta Tacoma", "Sparta Tacoma"), _g(19, "Harbor SC", "Harbor SC")]


def test_two_dates_against_other_clubs_conflict():
    cand = [_g(12, "Pacific FC 2010"), _g(19, "Seattle United B10")]
    assert schedule_conflict(EA_GAMES, cand) is True


def test_one_conflicting_date_does_not_decide():
    assert schedule_conflict(EA_GAMES, [_g(12, "Pacific FC 2010")]) is False


def test_same_opponent_club_is_not_a_conflict():
    cand = [_g(12, "Sparta Tacoma B10 EA"), _g(19, "Harbor SC B10")]
    assert schedule_conflict(EA_GAMES, cand) is False


def test_other_dates_are_not_a_conflict():
    cand = [_g(13, "Pacific FC 2010"), _g(20, "Seattle United B10")]
    assert schedule_conflict(EA_GAMES, cand) is False


def test_lineage_reads_last_seasons_key():
    assert lineage_target("9001", 2026, {"9001:2025": "T1", "9001:2026": "T2"}) == "T1"
    assert lineage_target("9001", 2026, {"9001:2026": "T2"}) is None


def _ea(tid="1"):
    return EaTeam(tid, "Emerald City FC", "Emerald City FC", "u17", frozenset({"EA"}), "WA", 2026)


def _db(tid, name):
    return {"team_id_master": tid, "team_name": name, "club_name": "Emerald City FC", "state_code": "WA",
            "provider_code": "gotsport", "ea_keys": frozenset()}


TWO = [_db("a", "Emerald City FC 2010 EA"), _db("b", "Emerald City FC B10 EA")]


def test_lineage_settles_a_two_candidate_review():
    [row] = classify([_ea()], TWO, lineage={"1": "b"})
    assert (row.bucket, row.reason, [c["team_id_master"] for c in row.candidates]) == (
        "confident",
        "last season's age-below team",
        ["b"],
    )


def test_lineage_never_adds_a_rejected_team():
    [row] = classify([_ea()], TWO, lineage={"1": "zzz"})
    assert (row.bucket, row.reason) == ("review", "2 candidates")


def test_a_busy_candidate_is_dropped():
    cand_games = {"a": [_g(12, "Pacific FC 2010"), _g(19, "Seattle United B10")]}
    [row] = classify([_ea()], TWO, ea_games={"1": EA_GAMES}, cand_games=cand_games)
    assert (row.bucket, [c["team_id_master"] for c in row.candidates]) == ("confident", ["b"])


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records at execute(); in_ batches over 100 ids and unordered paging are refused."""

    def __init__(self, db, table):
        self.db, self.table, self.filters, self.order_by, self.window = db, table, [], None, None

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((lambda r, c=col, v=val: r.get(c) == v))
        return self

    def in_(self, col, vals):
        assert len(vals) <= 100
        self.filters.append((lambda r, c=col, v=set(vals): r.get(c) in v))
        return self

    def gte(self, col, val):
        self.filters.append((lambda r, c=col, v=val: r.get(c) >= v))
        return self

    def lte(self, col, val):
        self.filters.append((lambda r, c=col, v=val: r.get(c) <= v))
        return self

    def or_(self, expr):
        assert expr == "is_deprecated.is.null,is_deprecated.eq.false"
        self.filters.append(lambda r: r.get("is_deprecated") is not True)
        return self

    def order(self, col):
        self.order_by = col
        return self

    def range(self, lo, hi):
        self.window = (lo, hi)
        return self

    def execute(self):
        self.db.executed.append(self.table)
        rows = [dict(r) for r in self.db.rows[self.table] if all(f(r) for f in self.filters)]
        if self.window:
            assert self.order_by, "paging without an order skips rows"
            rows = sorted(rows, key=lambda r: r[self.order_by])[self.window[0] : self.window[1] + 1]
        return _Result(rows)


class _Db:
    def __init__(self, **tables):
        self.rows = {"games": [], "team_merge_map": [], "teams": [], **tables}
        self.executed = []

    def table(self, name):
        return _Query(self, name)


def _game(gid, day, home, away, excluded=False):
    return {"id": gid, "game_date": f"2026-09-{day:02d}", "home_team_master_id": home, "away_team_master_id": away,
            "is_excluded": excluded}


def test_fetch_candidate_games_resolves_merges_both_ways(monkeypatch):
    monkeypatch.setattr(m, "PAGE_SIZE", 1)
    db = _Db(
        games=[
            _game(1, 12, "C", "OLD_OPP"),
            _game(2, 19, "C_OLD", "X"),
            _game(3, 20, "C", "X", excluded=True),
            _game(4, 1, "Y", "Z"),
        ],
        team_merge_map=[
            {"id": 1, "deprecated_team_id": "OLD_OPP", "canonical_team_id": "OPP"},
            {"id": 2, "deprecated_team_id": "C_OLD", "canonical_team_id": "C"},
        ],
        teams=[
            {"team_id_master": "OPP", "team_name": "Pacific FC 2010", "club_name": "Pacific FC"},
            {"team_id_master": "X", "team_name": "Seattle United B10", "club_name": None},
        ],
    )
    games = m.fetch_candidate_games(db, ["C"], 2026)
    assert sorted(games["C"], key=lambda g: g["game_date"]) == [
        {"game_date": "2026-09-12", "opponent_name": "Pacific FC 2010", "opponent_club": "Pacific FC"},
        {"game_date": "2026-09-19", "opponent_name": "Seattle United B10", "opponent_club": None},
    ]


TEAM_COLUMNS = ["provider_team_id", "academy_id", "club_name", "display_name", "age_group", "name_tier", "tiers",
                "regions", "gender", "season"]
GAME_COLUMNS = ["match_no", "game_date", "age_group", "bracket", "region", "home_team_id", "away_team_id", "home_name",
                "away_name", "home_academy", "away_academy", "home_score", "away_score", "status", "pairing",
                "home_key", "away_key"]


def _csv(path, columns, rows):
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _ea_row(uid, age="u17"):
    return {"provider_team_id": uid, "academy_id": "9", "club_name": "Emerald City FC", "display_name": "Emerald City FC",
            "age_group": age, "name_tier": "EA", "tiers": "EA", "regions": "PACNW", "gender": "Male", "season": "2026"}


def _ea_game(match_no, day, opp_uid, opp_name):
    return {"match_no": match_no, "game_date": f"2026-09-{day:02d}", "age_group": "u17", "bracket": "EA",
            "region": "PACNW", "home_team_id": "1", "away_team_id": opp_uid, "home_name": "Emerald City FC",
            "away_name": opp_name, "home_academy": "9", "away_academy": "8", "home_score": "2", "away_score": "1",
            "status": "played", "pairing": "both", "home_key": "1:2026", "away_key": f"{opp_uid}:2026"}


def _live(tid, name, club="Emerald City FC"):
    return {"team_id_master": tid, "team_name": name, "club_name": club, "state_code": "WA", "provider_id": "p-got",
            "age_group": "u17", "gender": "Male", "is_deprecated": False}


PROVIDERS = [{"id": "p-got", "code": "gotsport"}, {"id": "p-ea", "code": "modular11_ea"}]


def _report(tmp_path):
    import csv

    return list(csv.DictReader((tmp_path / "u17" / "match_report.csv").open(encoding="utf-8")))


def test_run_drops_a_candidate_busy_on_the_ea_teams_dates(tmp_path):
    _csv(tmp_path / "u17" / "teams.csv", TEAM_COLUMNS, [_ea_row("1")])
    _csv(tmp_path / "u17" / "games.csv", GAME_COLUMNS, [_ea_game("1", 12, "2", "Sparta Tacoma"),
                                                         _ea_game("2", 19, "3", "Harbor SC")])
    db = _Db(
        providers=PROVIDERS,
        team_alias_map=[],
        teams=[_live("a", "Emerald City FC 2010 EA"), _live("b", "Emerald City FC B10 EA"),
               _live("p", "Pacific FC 2010", club="Pacific FC"), _live("s", "Seattle United B10", club="Seattle United")],
        games=[_game(1, 12, "a", "p"), _game(2, 19, "s", "a")],
    )
    assert m.run("u17", tmp_path, db) == {"confident": 1, "review": 0, "no_match": 0}
    assert _report(tmp_path)[0]["candidate_ids"] == "b"


def test_run_follows_last_seasons_link_of_the_age_below_slot(tmp_path):
    _csv(tmp_path / "u17" / "teams.csv", TEAM_COLUMNS, [_ea_row("1")])
    _csv(tmp_path / "u16" / "teams.csv", TEAM_COLUMNS, [_ea_row("900", age="u16")])
    alias = {"id": 1, "provider_id": "p-ea", "provider_team_id": "900:2025", "team_id_master": "b",
             "review_status": "approved"}
    db = _Db(providers=PROVIDERS, team_alias_map=[alias],
             teams=[_live("a", "Emerald City FC 2010 EA"), _live("b", "Emerald City FC B10 EA")])
    assert m.run("u17", tmp_path, db) == {"confident": 1, "review": 0, "no_match": 0}
    [row] = _report(tmp_path)
    assert (row["candidate_ids"], row["reason"]) == ("b", "last season's age-below team")


def test_a_lone_busy_candidate_is_held_not_dropped():
    cand_games = {"a": [_g(12, "Pacific FC 2010"), _g(19, "Seattle United B10")]}
    [row] = classify([_ea()], TWO[:1], ea_games={"1": EA_GAMES}, cand_games=cand_games)
    assert (row.bucket, row.reason, [c["team_id_master"] for c in row.candidates]) == ("review", "schedule clash", ["a"])


def test_fetch_candidate_games_follows_merge_chains(monkeypatch):
    monkeypatch.setattr(m, "PAGE_SIZE", 1)
    db = _Db(
        games=[_game(1, 12, "A", "X")],
        team_merge_map=[
            {"id": 1, "deprecated_team_id": "A", "canonical_team_id": "B"},
            {"id": 2, "deprecated_team_id": "B", "canonical_team_id": "C"},
            {"id": 3, "deprecated_team_id": "X", "canonical_team_id": "Y"},
            {"id": 4, "deprecated_team_id": "Y", "canonical_team_id": "Z"},
        ],
        teams=[{"team_id_master": "Z", "team_name": "Pacific FC 2010", "club_name": "Pacific FC"}],
    )
    assert m.fetch_candidate_games(db, ["C"], 2026) == {
        "C": [{"game_date": "2026-09-12", "opponent_name": "Pacific FC 2010", "opponent_club": "Pacific FC"}]
    }
