"""Pairing by match number puts both team ids on the right sides, including an intra-club derby."""

from pathlib import Path

from scripts.scrape_modular11_ea import pair_games, parse_roster, parse_schedule_page, team_display_name

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "modular11_ea"


def _roster():
    return {t.provider_team_id: t for t in parse_roster((FIX / "ea_page.html").read_bytes().decode("utf-8"))}


def _rows(team_id):
    html = (FIX / f"team_{team_id}_p1.html").read_bytes().decode("utf-8")
    return parse_schedule_page(html, expected_page=1)[0]


def test_display_names_differ_within_one_club():
    roster = _roster()
    assert team_display_name(roster["7343"], _rows("7343")) == "FLYTE SC- Inland Empire"
    assert team_display_name(roster["9176"], _rows("9176")) == "FLYTE SC Blue- Inland Empire"


def test_display_name_falls_back_when_no_games():
    assert team_display_name(_roster()["7343"], []) == "FLYTE SC- Inland Empire U13 EA"


def test_derby_gets_both_ids_on_correct_sides():
    roster = _roster()
    games = pair_games([roster["7343"], roster["9176"]], {"7343": _rows("7343"), "9176": _rows("9176")}, "u13")
    derby = next(g for g in games if g.match_no == "123269")
    assert (derby.home_team_id, derby.away_team_id) == ("9176", "7343")
    assert derby.pairing == "both" and derby.status == "scheduled"


def test_opponent_outside_scrape_is_one_sided():
    roster = _roster()
    games = pair_games([roster["7343"]], {"7343": _rows("7343")}, "u13")
    first = next(g for g in games if g.match_no == "122957")
    assert (first.home_team_id, first.away_team_id, first.pairing) == ("7343", "", "one_sided")
    assert (first.home_score, first.away_score, first.status) == (6, 0, "played")


def test_each_match_appears_once():
    roster = _roster()
    games = pair_games([roster["7343"], roster["9176"]], {"7343": _rows("7343"), "9176": _rows("9176")}, "u13")
    assert len(games) == len({g.match_no for g in games}) == 39
