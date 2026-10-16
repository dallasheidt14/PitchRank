"""The match report end to end through a fake database: what it fetches decides what it can match."""

import csv
import json

import pytest

from scripts import match_mlsnext_kitman_teams as match
from scripts import prepare_mlsnext_kitman_club_states as prepare
from src.models import mlsnext_kitman_keys as keys

KITMAN, M11, GOTSPORT = "prov-kitman", "prov-m11", "prov-gs"


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Builds lazily, applies filters and windows at execute(), and returns only the columns selected."""

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.cols, self.eqs, self.ins, self.live_only, self.sort, self.window = None, [], [], False, None, None

    def select(self, cols="*", **_kw):
        self.cols = None if cols == "*" else [c.strip() for c in cols.split(",")]
        return self

    def eq(self, column, value):
        self.eqs.append((column, value))
        return self

    def in_(self, column, values):
        assert len(values) <= 100, "an .in_() list must stay within the URI limit"
        self.ins.append((column, set(values)))
        return self

    def or_(self, _expr):
        self.live_only = True
        return self

    def order(self, column):
        self.sort = column
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def execute(self):
        self.db.executed.append(self.table)
        rows = [
            r
            for r in self.db.rows[self.table]
            if all(r.get(c) == v for c, v in self.eqs)
            and all(r.get(c) in vs for c, vs in self.ins)
            and not (self.live_only and r.get("is_deprecated") is True)
        ]
        if self.sort:
            rows = sorted(rows, key=lambda r: r[self.sort])
        if self.window:
            rows = rows[self.window[0] : self.window[1] + 1]
        keep = self.cols
        return _Result([{c: r.get(c) for c in keep} if keep else dict(r) for r in rows])


class _Db:
    def __init__(self, **tables):
        self.rows = {"providers": [], "team_alias_map": [], "team_merge_map": [], "teams": [], **tables}
        self.executed = []

    def table(self, name):
        return _Query(self, name)


def _team(tid, club, age="u16", gender="Male", state="AZ", provider=M11, deprecated=None, name=None):
    return {
        "team_id_master": tid,
        "team_name": name or f"{club} {age.upper()} HD",
        "club_name": club,
        "age_group": age,
        "gender": gender,
        "state_code": state,
        "provider_id": provider,
        "is_deprecated": deprecated,
    }


def _alias(aid, provider, key, tid, status="approved"):
    return {"id": aid, "provider_id": provider, "provider_team_id": key, "team_id_master": tid, "review_status": status}


def _write_squads(tmp_path, squads):
    columns = ["provider_team_id", "key", "club_id", "club_name", "display_name", "age_group", "division", "gender", "season"]
    with (tmp_path / "squads.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for sid, club, age, division in squads:
            writer.writerow({"provider_team_id": sid, "key": f"{sid}:2026", "club_id": "1", "club_name": club,
                             "display_name": f"{club} U{age[1:]} {division}", "age_group": age, "division": division,
                             "gender": "Male", "season": 2026})


def _report(tmp_path):
    return {r["provider_team_id"]: r for r in csv.DictReader((tmp_path / "match_report.csv").open(encoding="utf-8"))}


def _db(**extra):
    providers = [{"id": KITMAN, "code": "mlsnext_kitman"}, {"id": M11, "code": "modular11"}, {"id": GOTSPORT, "code": "gotsport"}]
    teams = [
        _team("T1", "Alpha SC"),
        _team("D1", "Beta FC", deprecated=True),
        _team("T2", "Beta FC"),
        _team("F1", "Girls FC", gender="Female"),
        _team("X1", "Gone FC", deprecated=True),
        _team("G1", "Gamma FC", provider=GOTSPORT, name="Gamma FC 2010"),
        _team("G2", "Gamma FC", age="u15", provider=GOTSPORT, name="Gamma FC 2011"),
        _team("G3", "Other FC", provider=GOTSPORT, name="Other FC 2010"),
        _team("T9", "Gamma FC", name="Gamma FC U16 HD"),
        _team("T5", "Delta FC", provider=KITMAN, name="Delta FC U16 HD"),
    ]
    aliases = [
        _alias(1, M11, "63_U16_HD", "T1"),
        _alias(2, M11, "64_U16_HD", "D1"),
        _alias(3, M11, "65_U16_AD", "F1"),
        _alias(4, M11, "66_U16_HD", "X1"),
        _alias(5, M11, "junk", "T1"),
        _alias(6, M11, "67_U16_HD\n", "T1"),
        _alias(7, M11, "68_U16_AD", "T1", status="pending"),
        {**_alias(8, KITMAN, "77:2025", "T5"), "division": "HD"},
        {**_alias(9, KITMAN, "78:2025", "T1"), "division": None},
    ]
    return _Db(providers=providers, teams=teams, team_alias_map=aliases, team_merge_map=[{"id": 1, "deprecated_team_id": "D1", "canonical_team_id": "T2"}], **extra)


@pytest.fixture(autouse=True)
def states(monkeypatch):
    monkeypatch.delitem(keys.CLUB_STATES, "Alpha SC", raising=False)


def test_bridge_keeps_live_boys_teams_with_a_modular11_mls_next_alias_resolving_merges():
    bridge = {t["team_id_master"]: t for t in match.fetch_bridge(_db(), {"modular11": M11})}
    assert sorted(bridge) == ["T1", "T2"]
    assert bridge["T1"]["divisions"] == {"HD"} and bridge["T2"]["divisions"] == {"HD"}
    assert bridge["T2"]["age_group"] == "u16"


def test_the_report_links_through_the_bridge_and_surfaces_other_providers(tmp_path):
    _write_squads(tmp_path, [("10", "Alpha SC", "u16", "HD"), ("11", "Beta FC", "u16", "HD"), ("12", "Gamma FC", "u16", "HD"),
                             ("13", "Gamma FC", "u16", "AD")])
    counts = match.run(tmp_path, _db())
    report = _report(tmp_path)
    assert counts == {"linked": 0, "confident": 2, "review": 0, "new": 2, "new_without_state": 2}
    assert (report["10"]["bucket"], report["10"]["candidate_ids"]) == ("confident", "T1")
    assert (report["11"]["bucket"], report["11"]["candidate_ids"]) == ("confident", "T2")
    assert report["12"]["bucket"] == "new"
    assert (report["12"]["candidate_ids"], report["12"]["candidate_providers"]) == ("G1", "gotsport")


def test_other_provider_teams_are_only_the_requested_clubs_and_ages_and_never_the_bridge_or_kitman():
    provider_ids = {"modular11": M11, "gotsport": GOTSPORT, "mlsnext_kitman": KITMAN}
    db = _db()
    db.rows["teams"].append(_team("K1", "Gamma FC", provider=KITMAN, name="Gamma FC U16 HD"))
    found = match.fetch_other_provider_teams(db, provider_ids, {"u16"}, {match.normalize("Gamma FC")})
    assert [t["team_id_master"] for t in found] == ["G1"]


def test_an_existing_kitman_link_is_reported_linked_and_its_team_is_not_a_second_candidate(tmp_path):
    db = _db()
    db.rows["team_alias_map"].append(_alias(20, KITMAN, "10:2026", "T1"))
    _write_squads(tmp_path, [("10", "Alpha SC", "u16", "HD"), ("14", "Alpha SC", "u16", "HD")])
    match.run(tmp_path, db)
    report = _report(tmp_path)
    assert report["10"]["bucket"] == "linked"
    assert report["14"]["bucket"] == "review" and "already linked to another squad" in report["14"]["reason"]


def test_a_link_without_a_season_stops_the_run(tmp_path):
    db = _db()
    db.rows["team_alias_map"].append(_alias(20, KITMAN, "10", "T1"))
    _write_squads(tmp_path, [("10", "Alpha SC", "u16", "HD")])
    with pytest.raises(SystemExit, match="not season-keyed"):
        match.run(tmp_path, db)


def test_before_the_provider_is_seeded_nothing_is_linked_and_the_run_still_reports(tmp_path):
    db = _db()
    db.rows["providers"] = [p for p in db.rows["providers"] if p["code"] != "mlsnext_kitman"]
    _write_squads(tmp_path, [("10", "Alpha SC", "u16", "HD")])
    assert match.run(tmp_path, db)["confident"] == 1


def test_the_other_provider_fetch_is_skipped_when_nothing_is_new(tmp_path):
    db = _db()
    _write_squads(tmp_path, [("10", "Alpha SC", "u16", "HD")])
    match.run(tmp_path, db)
    assert db.executed.count("teams") == 1  # the bridge fetch only


def test_prepare_settles_a_club_whose_mls_next_teams_agree_and_lists_the_rest(monkeypatch):
    monkeypatch.delitem(prepare.CLUB_STATES, "Alpha SC", raising=False)
    monkeypatch.setitem(prepare.CLUB_STATES, "Already FC", "NV")
    bridge = [
        {"club_name": "Alpha SC", "state_code": "AZ"},
        {"club_name": "Alpha SC", "state_code": "AZ"},
        {"club_name": "Split FC", "state_code": "AZ"},
        {"club_name": "Split FC", "state_code": "NM"},
        {"club_name": "Blank FC", "state_code": None},
        {"club_name": "Canada FC", "state_code": "ON"},
    ]
    clubs = {"Alpha SC": 6, "Split FC": 6, "Blank FC": 6, "Ea FC": 6, "Already FC": 6, "Canada FC": 4, "No Club Selection": 2}
    settled, todo = prepare.settle(clubs, bridge, {"EA FC": "WA"})
    assert settled == {"Alpha SC": "AZ", "Ea FC": "WA"}
    assert todo == ["Blank FC", "Canada FC", "Split FC"]


def test_a_team_an_earlier_season_created_is_a_candidate_through_its_kitman_alias(tmp_path):
    _write_squads(tmp_path, [("30", "Delta FC", "u16", "HD"), ("31", "Delta FC", "u16", "AD")])
    match.run(tmp_path, _db())
    report = _report(tmp_path)
    assert (report["30"]["bucket"], report["30"]["candidate_ids"], report["30"]["candidate_providers"]) == (
        "confident",
        "T5",
        "mlsnext_kitman",
    )
    assert report["31"]["bucket"] == "new"


def test_a_kitman_alias_without_a_division_adds_no_division(tmp_path):
    bridge = {t["team_id_master"]: t for t in match.fetch_bridge(_db(), {"modular11": M11, "mlsnext_kitman": KITMAN})}
    assert bridge["T1"]["divisions"] == {"HD"} and bridge["T1"]["provider_code"] == "modular11"
    assert bridge["T5"]["divisions"] == {"HD"} and bridge["T5"]["provider_code"] == "mlsnext_kitman"


def test_last_seasons_link_does_not_block_this_seasons_squad_end_to_end(tmp_path):
    db = _db()
    db.rows["team_alias_map"].append(_alias(20, KITMAN, "10:2025", "T1"))
    _write_squads(tmp_path, [("10", "Alpha SC", "u16", "HD")])
    match.run(tmp_path, db)
    assert _report(tmp_path)["10"]["bucket"] == "confident"


def test_read_answers_takes_valid_two_letter_picks_for_known_clubs_and_undoes_the_formula_escape(tmp_path):
    path = tmp_path / "todo.csv"
    rows = [
        {"club_name": "Alpha SC", "your_state": " az "},
        {"club_name": "Beta FC", "your_state": "Arizona"},
        {"club_name": "Gamma FC", "your_state": ""},
        {"club_name": "Stranger FC", "your_state": "TX"},
        {"club_name": "'=Odd FC", "your_state": "NV"},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["club_name", "your_state"])
        writer.writeheader()
        writer.writerows(rows)
    clubs = {"Alpha SC", "Beta FC", "Gamma FC", "=Odd FC"}
    assert prepare.read_answers(path, clubs) == {"Alpha SC": "AZ", "=Odd FC": "NV"}


def test_read_answers_reads_a_sheet_saved_by_excel_with_a_byte_order_mark(tmp_path):
    path = tmp_path / "todo.csv"
    path.write_bytes("club_name,your_state\r\nAlpha SC,AZ\r\n".encode("utf-8-sig"))
    assert prepare.read_answers(path, {"Alpha SC"}) == {"Alpha SC": "AZ"}


def test_the_todo_sheet_defangs_a_club_name_that_would_run_as_a_formula(tmp_path, monkeypatch):
    _write_squads(tmp_path, [("40", '=HYPERLINK("https://evil.example","x")', "u16", "HD")])
    monkeypatch.setattr(prepare, "create_client", lambda *_a: _db())
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    assert prepare.main(["--in-dir", str(tmp_path)]) == 0
    todo = list(csv.DictReader((tmp_path / "club_states_todo.csv").open(encoding="utf-8")))
    assert [r["club_name"] for r in todo] == ["'=HYPERLINK(\"https://evil.example\",\"x\")"]


def test_answers_move_a_club_out_of_the_todo_and_into_the_table(tmp_path, monkeypatch):
    _write_squads(tmp_path, [("40", "Zeta FC", "u16", "HD")])
    answers = tmp_path / "answers.csv"
    answers.write_text("club_name,your_state\nZeta FC,TX\n", encoding="utf-8")
    table = tmp_path / "table.json"
    table.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(prepare, "create_client", lambda *_a: _db())
    monkeypatch.setattr(prepare, "TABLE_PATH", table)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    assert prepare.main(["--in-dir", str(tmp_path), "--answers", str(answers), "--write"]) == 0
    assert json.loads(table.read_text(encoding="utf-8")) == {**keys.CLUB_STATES, "Zeta FC": "TX"}
    assert list(csv.DictReader((tmp_path / "club_states_todo.csv").open(encoding="utf-8"))) == []


def test_a_stale_answers_sheet_does_not_overwrite_a_club_already_in_the_table(tmp_path, monkeypatch):
    _write_squads(tmp_path, [("40", "Zeta FC", "u16", "HD")])
    answers = tmp_path / "answers.csv"
    answers.write_text("club_name,your_state\nZeta FC,TX\n", encoding="utf-8")
    table = tmp_path / "table.json"
    table.write_text("{}", encoding="utf-8")
    monkeypatch.setitem(keys.CLUB_STATES, "Zeta FC", "AZ")
    monkeypatch.setattr(prepare, "create_client", lambda *_a: _db())
    monkeypatch.setattr(prepare, "TABLE_PATH", table)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    assert prepare.main(["--in-dir", str(tmp_path), "--answers", str(answers), "--write"]) == 0
    assert json.loads(table.read_text(encoding="utf-8"))["Zeta FC"] == "AZ"
