"""The per-age EA cleanup runner: the candidate pool, duplicate pairs to propose, stateless teams."""

import csv
import json

from scripts import prepare_modular11_ea_cleanup as prep
from scripts.find_cross_provider_duplicates import build_evidence


def _ea(uid, club, tier="EA", name=None):
    return {"provider_team_id": uid, "academy_id": uid, "club_name": club, "display_name": name or club,
            "age_group": "u17", "name_tier": tier, "tiers": tier, "regions": "", "gender": "Male", "season": "2026"}


def _team(tid, name, club, state="CA"):
    return {"team_id_master": tid, "team_name": name, "club_name": club, "state_code": state, "age_group": "u17",
            "gender": "Male", "provider_code": "gotsport", "ea_keys": frozenset()}


def _games(*rows):
    return [{"id": i, "home_team_master_id": h, "away_team_master_id": a, "game_date": d, "is_excluded": False}
            for i, (h, a, d) in enumerate(rows, 1)]


def _pairs(ea_rows, teams, games):
    pool = prep.build_pool(ea_rows, teams)
    ids = [t["team_id_master"] for t in pool]
    ev = build_evidence(games, [], lambda t: t, ids)
    return prep.propose_pairs(pool, ea_rows, ev, "2026-08-01")


CFA = [_ea("3432", "California Football Academy")]
CFA_TEAMS = [
    _team("g1", "CFA OC BU17 EA", "California Football Academy"),
    _team("g2", "CFA OC B10 EA", "California Football Academy"),
    _team("g3", "California Football Academy CFA OC BU17 EA", "California Football Academy"),
]
CFA_GAMES = _games(("g1", "x1", "2026-09-01"), ("g1", "x2", "2026-09-08"), ("g3", "x3", "2026-09-15"),
                   ("g2", "x4", "2025-10-01"))


def test_three_copies_of_one_squad_become_two_pairs_into_the_best_row():
    pairs = _pairs(CFA, CFA_TEAMS, CFA_GAMES)
    assert [(p["merge_id"], p["keep_id"]) for p in pairs] == [("g2", "g1"), ("g3", "g1")]
    assert pairs[0]["merge_name"] == "CFA OC B10 EA" and pairs[0]["keep_name"] == "CFA OC BU17 EA"


def test_club_branches_are_never_paired():
    ea = [_ea("3188", "ALBION SC Atlanta"), _ea("6967", "ALBION SC Atlanta Metro")]
    teams = [_team("a", "ALBION SC Atlanta B10 EA", "ALBION SC Atlanta", "GA"),
             _team("m", "ALBION SC Atlanta Metro B10 EA", "ALBION SC Atlanta Metro", "GA")]
    assert _pairs(ea, teams, []) == []


def test_rows_that_played_each_other_are_not_paired():
    teams = CFA_TEAMS[:2]
    assert _pairs(CFA, teams, _games(("g1", "g2", "2026-09-01"))) == []


def test_rows_that_played_on_the_same_day_are_not_paired():
    teams = CFA_TEAMS[:2]
    assert _pairs(CFA, teams, _games(("g1", "x1", "2026-09-01"), ("g2", "x2", "2026-09-01"))) == []


def test_a_colour_squad_is_not_paired():
    ea = [_ea("7343", "Sparta Tacoma")]
    teams = [_team("s1", "Sparta Tacoma B09/10 - EA", "Sparta Tacoma", "WA"),
             _team("s2", "Sparta Tacoma B09/10 Red EA", "Sparta Tacoma", "WA")]
    assert _pairs(ea, teams, []) == []


def test_different_tiers_are_not_paired():
    ea = [_ea("7151", "Rangers FC"), _ea("8914", "Rangers FC", tier="EA2", name="Rangers FC 2")]
    teams = [_team("r1", "Rangers FC U17 EA", "Rangers FC"), _team("r2", "Rangers FC U17 EA2", "Rangers FC")]
    assert _pairs(ea, teams, []) == []


def test_rangers_ea_2010_is_proposed_with_its_stale_schedule_shown():
    ea = [_ea("7151", "Rangers FC")]
    teams = [_team("r1", "Rangers FC U17 EA", "Rangers FC"), _team("r2", "EA 2010", "Rangers FC")]
    games = _games(("r1", "x1", "2026-09-06"), ("r2", "x2", "2025-11-01"), ("r2", "x3", "2025-12-01"))
    [pair] = _pairs(ea, teams, games)
    assert (pair["merge_id"], pair["keep_id"]) == ("r2", "r1")
    assert pair["evidence"] == {
        "ea_club": "Rangers FC",
        "tier": "EA",
        "games_keep": 1,
        "games_merge": 2,
        "season_game_days_keep": 1,
        "season_game_days_merge": 0,
        "last_game_keep": "2026-09-06",
        "last_game_merge": "2025-12-01",
    }


def test_pool_holds_same_and_branch_rows_only():
    ea = [_ea("3188", "ALBION SC Atlanta")]
    teams = [_team("a", "ALBION SC Atlanta B10 EA", "ALBION SC Atlanta", "GA"),
             _team("m", "ALBION SC Atlanta Metro B10 EA", "ALBION SC Atlanta Metro", "GA"),
             _team("o", "Concorde Fire B10", "Concorde Fire", "GA")]
    assert [(r["team_id_master"], r["relation"]) for r in prep.build_pool(ea, teams)] == [("a", "same"), ("m", "branch")]


def test_snapshot_filter_keeps_pool_decisions_in_the_snapshots_shape():
    snapshot = {"rules": ["R1"], "decisions": [{"team_id": "a"}, {"team_id": "b"}, {"team_id": "x"}], "extra": 1}
    assert prep.filter_snapshot(snapshot, {"a", "b"}) == {
        "rules": ["R1"],
        "decisions": [{"team_id": "a"}, {"team_id": "b"}],
        "extra": 1,
    }


class _Query:
    """Records at execute(); paging needs an order, and in_ batches are capped at 100."""

    def __init__(self, db, table):
        self.db, self.table, self.filters, self.order_by, self.window = db, table, [], None, None

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r, c=col, v=val: r.get(c) == v)
        return self

    def in_(self, col, vals):
        assert len(vals) <= 100
        self.filters.append(lambda r, c=col, v=set(vals): r.get(c) in v)
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
        return type("R", (), {"data": rows})()


class _Db:
    def __init__(self, **tables):
        self.rows = {"providers": [], "team_alias_map": [], "team_merge_map": [], "games": [], "teams": [], **tables}
        self.executed = []

    def table(self, name):
        return _Query(self, name)


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_run_writes_the_pool_pairs_and_stateless_list(tmp_path):
    _write(tmp_path / "u17" / "teams.csv", CFA)
    live = [{**t, "provider_id": "p-got", "is_deprecated": False} for t in CFA_TEAMS]
    live[2]["state_code"] = None
    for t in live:
        del t["provider_code"], t["ea_keys"]
    db = _Db(providers=[{"id": "p-got", "code": "gotsport"}], teams=live, games=CFA_GAMES)
    counts = prep.run("u17", tmp_path, db)
    assert counts == {"pool": 3, "pairs": 2, "stateless": 1}
    out = tmp_path / "u17" / "cleanup"
    pool = list(csv.DictReader((out / "candidate_pool.csv").open(encoding="utf-8")))
    assert [r["team_id_master"] for r in pool] == ["g1", "g2", "g3"]
    pairs = json.loads((out / "duplicate_pairs.json").read_text(encoding="utf-8"))
    assert [(p["merge_id"], p["keep_id"]) for p in pairs] == [("g2", "g1"), ("g3", "g1")]
    stateless = list(csv.DictReader((out / "stateless.csv").open(encoding="utf-8")))
    assert [r["team_id_master"] for r in stateless] == ["g3"]


def test_run_filters_a_state_snapshot_to_the_pool(tmp_path):
    _write(tmp_path / "u17" / "teams.csv", CFA)
    live = [{**t, "provider_id": "p-got", "is_deprecated": False} for t in CFA_TEAMS]
    for t in live:
        del t["provider_code"], t["ea_keys"]
    snapshot = tmp_path / "run.json"
    snapshot.write_text(json.dumps({"rules": ["R1"], "decisions": [{"team_id": "g1"}, {"team_id": "zz"}]}), encoding="utf-8")
    db = _Db(providers=[{"id": "p-got", "code": "gotsport"}], teams=live, games=CFA_GAMES)
    prep.run("u17", tmp_path, db, snapshot_path=snapshot)
    kept = json.loads((tmp_path / "u17" / "cleanup" / "state_pool.json").read_text(encoding="utf-8"))
    assert kept == {"rules": ["R1"], "decisions": [{"team_id": "g1"}]}


def test_a_branch_row_is_not_paired_with_its_parent_club():
    ea = [_ea("3188", "ALBION SC Atlanta")]
    teams = [_team("a", "ALBION SC Atlanta B10 EA", "ALBION SC Atlanta", "GA"),
             _team("m", "ALBION SC Atlanta Metro B10 EA", "ALBION SC Atlanta Metro", "GA")]
    assert _pairs(ea, teams, []) == []


def test_the_survivor_is_the_better_named_row_not_the_first_id():
    ea = [_ea("7151", "Rangers FC")]
    teams = [_team("a", "EA 2010", "Rangers FC"), _team("b", "Rangers FC U17 EA", "Rangers FC")]
    [pair] = _pairs(ea, teams, [])
    assert (pair["merge_id"], pair["keep_id"]) == ("a", "b")


def test_santa_monica_is_never_proposed_as_a_copy_of_santa_ana():
    ea = [_ea("4556", "ALBION SC Santa Ana")]
    teams = [_team("a", "ALBION SC Santa Ana B10 EA", "ALBION SC Santa Ana"),
             _team("m", "Albion SC Santa Monica BU17 EA", "Albion SC Santa Monica")]
    assert _pairs(ea, teams, []) == []
