"""run() fetches live, same-age, male, non-protected, non-modular11 teams in ordered pages."""

import csv

from scripts import match_modular11_ea_teams as m

LIVE_FILTER = "is_deprecated.is.null,is_deprecated.eq.false"


class _Query:
    """Records at execute(); refuses unordered paging and any or_ filter other than the live-row one."""

    def __init__(self, db, table):
        self.db, self.table, self.filters, self.order_by, self.window = db, table, [], None, None

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def or_(self, expr):
        assert expr == LIVE_FILTER, f"unexpected or_ filter {expr!r}"
        self.filters.append(("live",))
        return self

    def order(self, col):
        self.order_by = col
        return self

    def range(self, lo, hi):
        self.window = (lo, hi)
        return self

    def execute(self):
        self.db.executed.append((self.table, list(self.filters), self.order_by, self.window))
        rows = [r for r in self.db.rows[self.table] if all(f[0] != "eq" or r.get(f[1]) == f[2] for f in self.filters)]
        if self.table == "team_alias_map":
            assert self.order_by == "id", "paging without a unique order skips rows"
            lo, hi = self.window
            rows = rows[lo : hi + 1]
        if self.table == "teams":
            assert self.order_by == "team_id_master", "paging without a unique order skips rows"
            if ("live",) in self.filters:
                rows = [r for r in rows if r.get("is_deprecated") is not True]
            rows = sorted(rows, key=lambda r: r["team_id_master"])
            lo, hi = self.window
            rows = rows[lo : hi + 1]
        return type("R", (), {"data": rows})()


class _Db:
    def __init__(self, teams, providers, aliases=()):
        self.rows = {"teams": teams, "providers": providers, "team_alias_map": list(aliases)}
        self.executed = []

    def table(self, name):
        return _Query(self, name)


GOT, M11 = "p-got", "p-m11"


def _team(tid, name, club="Emerald City FC", age="u13", gender="Male", provider=GOT, deprecated=None):
    return {
        "team_id_master": tid,
        "team_name": name,
        "club_name": club,
        "age_group": age,
        "gender": gender,
        "state_code": "WA",
        "provider_id": provider,
        "is_deprecated": deprecated,
    }


def _write_teams_csv(tmp_path):
    folder = tmp_path / "u13"
    folder.mkdir()
    columns = [
        "provider_team_id",
        "academy_id",
        "club_name",
        "display_name",
        "age_group",
        "name_tier",
        "tiers",
        "regions",
        "gender",
        "season",
    ]
    with (folder / "teams.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "provider_team_id": "1",
                "academy_id": "9",
                "club_name": "Emerald City FC",
                "display_name": "Emerald City FC",
                "age_group": "u13",
                "name_tier": "EA",
                "tiers": "EA;EA National",
                "regions": "PACNW",
                "gender": "Male",
                "season": "2026",
            }
        )


def test_run_reports_only_eligible_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "PAGE_SIZE", 2)
    teams = [
        _team("a", "Emerald City FC 2014 EA"),
        _team("b", "Emerald City FC 2014 EA", deprecated=True),
        _team("c", "Emerald City FC U13 HD"),
        _team("d", "Emerald City FC 2014 EA", provider=M11),
        _team("e", "Emerald City FC 2014 EA", age="u12"),
        _team("f", "Emerald City FC 2014 EA", gender="Female"),
    ]
    db = _Db(teams, [{"id": GOT, "code": "gotsport"}, {"id": M11, "code": "modular11"}])
    _write_teams_csv(tmp_path)
    counts = m.run("u13", tmp_path, db)
    assert counts == {"confident": 1, "review": 0, "no_match": 0}
    [row] = list(csv.DictReader((tmp_path / "u13" / "match_report.csv").open(encoding="utf-8")))
    assert row["candidate_ids"] == "a" and row["candidate_providers"] == "gotsport"
    assert row["candidate_states"] == "WA" and row["tiers"] == "EA"
    assert len([e for e in db.executed if e[0] == "teams"]) >= 2


def test_mls_next_team_is_never_offered_for_review(tmp_path):
    db = _Db([_team("c", "Emerald City FC U13 HD")], [{"id": GOT, "code": "gotsport"}])
    _write_teams_csv(tmp_path)
    assert m.run("u13", tmp_path, db) == {"confident": 0, "review": 0, "no_match": 1}


def test_dual_tier_team_matches_only_its_name_tier(tmp_path):
    folder = tmp_path / "u13"
    folder.mkdir()
    columns = [
        "provider_team_id",
        "academy_id",
        "club_name",
        "display_name",
        "age_group",
        "name_tier",
        "tiers",
        "regions",
        "gender",
        "season",
    ]
    with (folder / "teams.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "provider_team_id": "1",
                "academy_id": "9",
                "club_name": "Emerald City FC",
                "display_name": "Emerald City FC",
                "age_group": "u13",
                "name_tier": "EA",
                "tiers": "EA;EA National;EA2",
                "regions": "PACNW",
                "gender": "Male",
                "season": "2026",
            }
        )
    db = _Db([_team("a", "Emerald City FC 2014 EA2")], [{"id": GOT, "code": "gotsport"}])
    assert m.run("u13", tmp_path, db) == {"confident": 0, "review": 0, "no_match": 1}


def test_run_drops_a_team_already_linked_to_another_ea_team_this_season(tmp_path):
    providers = [{"id": GOT, "code": "gotsport"}, {"id": "p-ea", "code": "modular11_ea"}]
    aliases = [
        {"id": 1, "provider_id": "p-ea", "provider_team_id": "9:2026", "team_id_master": "a", "review_status": "approved"},
        {"id": 2, "provider_id": GOT, "provider_team_id": "1:2026", "team_id_master": "b", "review_status": "approved"},
    ]
    db = _Db([_team("a", "Emerald City FC 2014 EA"), _team("b", "Emerald City FC B14 EA")], providers, aliases)
    _write_teams_csv(tmp_path)
    assert m.run("u13", tmp_path, db) == {"confident": 1, "review": 0, "no_match": 0}
    [row] = list(csv.DictReader((tmp_path / "u13" / "match_report.csv").open(encoding="utf-8")))
    assert row["candidate_ids"] == "b"
