"""The match report: exact club makes a link confident, anything near goes to review, the rest is new."""

import pytest

from scripts import match_mlsnext_kitman_teams as match
from scripts import scrape_mlsnext_kitman as scrape
from src.models import mlsnext_kitman_keys as keys


def _squad(sid="10", club="Alpha SC", age="u16", division="HD", season=2026, suffix=""):
    return {
        "provider_team_id": sid,
        "key": f"{sid}:{season}",
        "club_name": club,
        "display_name": f"{club} U{age[1:]} {division}" + (" II" if suffix else ""),
        "age_group": age,
        "division": division,
        "suffix": suffix,
    }


def _team(tid="T1", club="Alpha SC", name=None, age="u16", divisions=("HD",), state="AZ", suffix=""):
    return {
        "team_id_master": tid,
        "team_name": name or f"{club} U16 HD",
        "club_name": club,
        "age_group": age,
        "divisions": set(divisions),
        "state_code": state,
        "provider_code": "modular11",
        "suffix": suffix,
    }


def _one(squads, bridge, links=None, others=None):
    rows = match.classify(squads, bridge, links or {}, others)
    return [(r.bucket, r.reason) for r in rows], rows


def test_exact_club_age_and_division_is_confident():
    verdict, rows = _one([_squad()], [_team()])
    assert verdict == [("confident", "exact club, age and division")]
    assert rows[0].candidates[0]["team_id_master"] == "T1"


def test_the_club_name_compares_without_case_or_punctuation():
    verdict, _ = _one([_squad(club="A.B.C. Soccer")], [_team(club="abc  soccer")])
    assert verdict[0][0] == "confident"


def test_the_age_and_the_division_both_have_to_agree():
    assert _one([_squad(age="u15")], [_team()])[0][0][0] == "new"
    assert _one([_squad(division="AD")], [_team(divisions=("HD",))])[0][0][0] == "new"
    assert _one([_squad(division="AD")], [_team(divisions=("HD", "AD"))])[0][0][0] == "confident"


def test_two_exact_teams_are_a_review():
    verdict, _ = _one([_squad()], [_team("T1"), _team("T2")])
    assert verdict == [("review", "2 candidates")]


@pytest.mark.parametrize(
    ("kitman", "stored"),
    [
        ("Charleston SC", "Charleston Soccer Club"),
        ("Los Angeles Sports Club", "Los Angeles Soccer Club"),
        ("GFI Academy North", "GFI Academy"),
        ("Carolina Core FC", "Carolina Core FC Youth"),
    ],
)
def test_a_near_spelling_or_branch_is_never_confident(kitman, stored):
    verdict, rows = _one([_squad(club=kitman)], [_team(club=stored)])
    assert verdict == [("review", "near club name, not exact")]
    assert rows[0].candidates[0]["club_name"] == stored


def test_a_club_of_only_generic_words_does_not_match_everything():
    verdict, _ = _one([_squad(club="SA United SC")], [_team(club="FC Richmond")])
    assert verdict[0][0] == "new"


def test_a_different_club_with_a_shared_first_word_is_a_review_not_new():
    verdict, _ = _one([_squad(club="Roseville Soccer Club")], [_team(club="Roswell Soccer Club")])
    assert verdict[0][0] == "new"


def test_two_squads_claiming_one_team_are_both_reviews():
    squads = [_squad("10", division="HD"), _squad("11", division="AD")]
    bridge = [_team(divisions=("HD", "AD"))]
    verdict, _ = _one(squads, bridge)
    assert [v[0] for v in verdict] == ["review", "review"]
    assert "claimed by another squad" in verdict[0][1]


def test_a_near_candidate_does_not_block_another_squads_exact_link():
    squads = [_squad("10", club="Alpha SC"), _squad("11", club="Alpha Soccer Club Extra")]
    verdict, _ = _one(squads, [_team("T1", club="Alpha SC")])
    assert verdict[0][0] == "confident"


def test_a_candidate_already_linked_to_another_squad_this_season_is_a_review():
    verdict, _ = _one([_squad("10")], [_team()], links={"99:2026": "T1"})
    assert verdict == [("review", "its candidate is already linked to another squad this season")]


def test_a_candidate_linked_to_a_squad_of_last_season_is_free_again():
    verdict, _ = _one([_squad("10", season=2027)], [_team()], links={"99:2026": "T1"})
    assert verdict[0][0] == "confident"


def test_a_candidate_linked_to_another_squad_of_the_same_season_is_taken_in_a_later_season_too():
    verdict, _ = _one([_squad("10", season=2027)], [_team()], links={"99:2027": "T1"})
    assert verdict[0][0] == "review"


def test_a_squad_already_linked_is_reported_linked():
    verdict, rows = _one([_squad("10")], [_team()], links={"10:2026": "T1"})
    assert verdict == [("linked", "already linked")]
    assert rows[0].candidates[0]["team_id_master"] == "T1"


def test_a_link_from_another_season_does_not_count(monkeypatch):
    verdict, _ = _one([_squad("10", season=2027)], [_team()], links={"10:2026": "T1"})
    assert verdict[0][0] == "confident"


def test_a_club_table_state_that_disagrees_with_the_candidate_is_a_review(monkeypatch):
    monkeypatch.setitem(keys.CLUB_STATES, "Alpha SC", "CA")
    verdict, _ = _one([_squad()], [_team(state="AZ")])
    assert verdict == [("review", "club table says CA, candidate is in AZ")]


def test_a_candidate_with_no_state_is_not_blocked_by_the_table(monkeypatch):
    monkeypatch.setitem(keys.CLUB_STATES, "Alpha SC", "CA")
    verdict, _ = _one([_squad()], [_team(state=None)])
    assert verdict[0][0] == "confident"


def test_new_says_whether_the_club_is_known_at_another_age():
    known, _ = _one([_squad(age="u17")], [_team(age="u16")])
    unknown, _ = _one([_squad(club="Nobody FC")], [_team()])
    assert known == [("new", "club has no team at this age and division")]
    assert unknown == [("new", "club not in our MLS NEXT data")]


def test_a_new_squad_shows_the_same_clubs_teams_under_other_providers():
    other = {"team_id_master": "G1", "team_name": "Nobody FC 2010", "club_name": "Nobody FC", "age_group": "u16", "provider_code": "gotsport", "state_code": "TX"}
    elsewhere_age = {**other, "team_id_master": "G2", "age_group": "u15"}
    _, rows = _one([_squad(club="Nobody FC")], [], others=[other, elsewhere_age])
    assert rows[0].bucket == "new"
    assert [c["team_id_master"] for c in rows[0].candidates] == ["G1"]


def test_the_state_comes_from_the_club_table_or_is_blank(monkeypatch):
    monkeypatch.setitem(keys.CLUB_STATES, "Alpha SC", "AZ")
    monkeypatch.delitem(keys.CLUB_STATES, "Nobody FC", raising=False)
    _, rows = _one([_squad(club="Alpha SC"), _squad("11", club="Nobody FC")], [])
    assert [r.state for r in rows] == ["AZ", ""]


def test_a_placeholder_club_has_no_state(monkeypatch):
    monkeypatch.setitem(keys.CLUB_STATES, "No Club Selection", "AZ")
    assert match.club_state_or_blank("No Club Selection") == ""


def test_a_squad_linked_to_a_team_no_longer_in_the_live_bridge_goes_to_review():
    verdict, rows = _one([_squad("10")], [_team()], links={"10:2026": "MERGED"})
    assert verdict == [("review", "its linked team is no longer live")]
    assert rows[0].candidates[0]["team_id_master"] == "MERGED"


def test_a_suffixed_squad_does_not_take_the_plain_team():
    verdict, rows = _one([_squad(age="u17", suffix="B")], [_team(age="u17")])
    assert verdict[0][0] == "new"
    assert rows[0].candidates == ()


def test_a_plain_squad_does_not_take_a_suffixed_team():
    verdict, _ = _one([_squad(age="u17")], [_team(age="u17", suffix="B")])
    assert verdict[0][0] == "new"


def test_in_a_later_season_each_squad_matches_the_team_of_its_own_suffix():
    squads = [_squad("10", age="u17", season=2027), _squad("11", age="u17", season=2027, suffix="B")]
    bridge = [_team("T1", age="u17"), _team("T2", age="u17", suffix="B")]
    links = {"10:2026": "T1", "11:2026": "T2"}
    verdict, rows = _one(squads, bridge, links)
    assert [v[0] for v in verdict] == ["confident", "confident"]
    assert [r.candidates[0]["team_id_master"] for r in rows] == ["T1", "T2"]


def test_a_new_suffixed_squad_is_not_told_its_club_has_no_team_when_it_has_a_plain_one():
    verdict, _ = _one([_squad(age="u17", suffix="B")], [_team(age="u17")])
    assert verdict == [("new", "no team for this squad suffix at this age and division")]
    verdict, _ = _one([_squad(age="u15")], [_team(age="u17")])
    assert verdict == [("new", "club has no team at this age and division")]
    verdict, _ = _one([_squad(club="Other FC", age="u17", suffix="B")], [_team(age="u17")])
    assert verdict == [("new", "club not in our MLS NEXT data")]


def test_the_suffix_the_scraper_writes_into_a_name_is_the_one_the_matcher_reads_back():
    suffixed = scrape.Squad("30", "300", "FC Dallas", "u17", "HD", "B")
    plain = scrape.Squad("31", "301", "FC Dallas", "u17", "HD")
    assert match._team_suffix(suffixed.display_name) == "B"
    assert match._team_suffix(plain.display_name) == ""
