"""Same-club, same-age, same-tier rules for linking EA teams to existing ones."""

import pytest

from scripts.match_modular11_ea_teams import EaTeam, classify, club_relation, is_protected, tier_marker


def _ea(tid="1", club="Emerald City FC", tiers=("EA",), state="WA", name=None):
    return EaTeam(
        provider_team_id=tid,
        club_name=club,
        display_name=name or club,
        age_group="u13",
        tiers=frozenset(tiers),
        state=state,
        season=2026,
    )


def _db(tid, name, club="Emerald City FC", state="WA", ea_keys=()):
    return {
        "team_id_master": tid,
        "team_name": name,
        "club_name": club,
        "state_code": state,
        "provider_code": "gotsport",
        "ea_keys": frozenset(ea_keys),
    }


def test_tier_marker_whole_words():
    assert tier_marker("Emerald City 2014 EA") == "EA"
    assert tier_marker("Emerald City 2014 EA2") == "EA2"
    assert tier_marker("Seattle Sea Hawks 2014") is None
    assert tier_marker("Emerald City 2014 Team") is None


def test_protected_names():
    assert is_protected("Sparta 2014 HD") and is_protected("Sparta U13 AD") and is_protected("Sparta MLS NEXT")
    assert not is_protected("Sparta 2014 EA")


def test_single_tagged_candidate_is_confident():
    [row] = classify([_ea()], [_db("a", "Emerald City FC 2014 EA")])
    assert row.bucket == "confident" and [c["team_id_master"] for c in row.candidates] == ["a"]


def test_ea2_name_is_not_a_candidate_for_ea_team():
    [row] = classify([_ea()], [_db("a", "Emerald City FC 2014 EA2")])
    assert row.bucket == "no_match"


def test_ea_name_is_not_a_candidate_for_ea2_team():
    [row] = classify([_ea(tiers=("EA2",))], [_db("a", "Emerald City FC 2014 EA")])
    assert row.bucket == "no_match"


def test_two_tagged_candidates_go_to_review():
    [row] = classify([_ea()], [_db("a", "Emerald City FC 2014 EA"), _db("b", "Emerald City FC B14 EA")])
    assert row.bucket == "review" and len(row.candidates) == 2


def test_untagged_same_club_goes_to_review():
    [row] = classify([_ea()], [_db("a", "Emerald City FC 2014 Blue")])
    assert row.bucket == "review" and "no EA tier" in row.reason


def test_other_club_is_no_match():
    [row] = classify([_ea()], [_db("a", "Sparta Tacoma 2014 EA", club="Sparta Tacoma")])
    assert row.bucket == "no_match"


def test_a_branch_candidate_does_not_block_the_club_itself():
    rush = _ea("1", club="Colorado Rush")
    cos = _ea("2", club="Colorado Rush - COS")
    rows = classify([rush, cos], [_db("a", "Colorado Rush 2014 EA", club="Colorado Rush")])
    assert {r.ea.provider_team_id: (r.bucket, r.reason) for r in rows} == {
        "1": ("confident", "one same-club, same-age, same-tier team"),
        "2": ("review", "different branch"),
    }


def test_candidate_claimed_by_two_ea_teams_goes_to_review():
    first, second = _ea("1"), _ea("2", name="Emerald City FC (2)")
    rows = classify([first, second], [_db("a", "Emerald City FC 2014 EA")])
    assert {r.ea.provider_team_id: (r.bucket, r.reason) for r in rows} == {
        "1": ("review", "claimed by another EA team: 2"),
        "2": ("review", "claimed by another EA team: 1"),
    }


def test_team_name_led_by_ea_club_matches_despite_other_club_name():
    db = _db("a", "ALBION SC Boulder County B10 EA", club="Albion SC Colorado")
    [row] = classify([_ea(club="ALBION SC Boulder County")], [db])
    assert row.bucket == "confident"


def test_team_name_led_by_ea_club_handles_bracketed_tier():
    db = _db("a", "Albion SC Fairfield B2010 (EA)", club="Regal Sporting Group")
    [row] = classify([_ea(club="ALBION SC Fairfield")], [db])
    assert row.bucket == "confident"


def test_team_name_led_by_a_longer_branch_name_is_not_the_club():
    db = _db("a", "ALBION SC Atlanta Metro B10 EA", club="Some Other Club")
    [row] = classify([_ea(club="ALBION SC Atlanta")], [db])
    assert row.bucket == "no_match"


@pytest.mark.parametrize(
    "ea_club,cand_club,cand_name,expected",
    [
        ("ALBION SC Santa Ana", "Albion SC Santa Monica", "BU17 EA", "branch"),
        ("Total Futbol Academy - OC", "Total Futbol Academy (TFA-SGV)", "TFA-SGV 2010 EA", "branch"),
        ("LA Surf LC", "LA Surf Futures", "Futures EA BU16", "branch"),
        ("ALBION SC Atlanta", "ALBION SC Atlanta Metro", "ALBION SC ATLANTA METRO B10 EA", "branch"),
        ("ALBION SC San Diego", "Albion SC San Diego", "ALBION SC San Diego EC B10 EA2", "same"),
        ("California Football Academy", "California Football Academy", "CFA OC BU17 EA", "same"),
        ("ALBION SC Boulder County", "Albion SC Colorado", "ALBION SC Boulder County B10 EA", "same"),
        ("Emerald City FC", "Sparta Tacoma", "Sparta 2010 EA", "other"),
        ("Mt. Rainier", "Mt. Rainier Futbol Club", "Mt. Rainier FC 2010 EA", "same"),
        ("LA Surf Futures", "Futures", "Futures EA BU16", "branch"),
    ],
)
def test_club_relation(ea_club, cand_club, cand_name, expected):
    assert club_relation(ea_club, cand_club, cand_name) == expected


def test_club_relation_reads_the_team_name_when_club_is_blank():
    assert club_relation("LA Surf LC", None, "LA Surf Futures 2010 EA") == "branch"


def test_ea1_reads_as_ea():
    assert tier_marker("AC Brea EA1") == "EA"


def _one(ea, *db):
    [row] = classify([ea], list(db))
    return row.bucket, row.reason, [c["team_id_master"] for c in row.candidates]


def test_branch_is_review_only():
    db = _db("a", "Albion SC Santa Monica BU17 EA", club="Albion SC Santa Monica", state="CA")
    assert _one(_ea(club="ALBION SC Santa Ana", state="CA"), db) == ("review", "different branch", ["a"])


def test_state_outside_the_clubs_state_is_not_a_candidate():
    assert _one(_ea(state="WA"), _db("a", "Emerald City FC 2014 EA", state="OR")) == ("no_match", "", [])


def test_no_state_is_never_confident():
    assert _one(_ea(), _db("a", "Emerald City FC 2014 EA", state=None)) == ("review", "no state", ["a"])


@pytest.mark.parametrize(
    "name,token",
    [
        ("Emerald City FC B10 EA Mora", "mora"),
        ("Emerald City FC BU17 EA Brimicombe", "brimicombe"),
        ("Emerald City FC U16 EA | Ramirez", "ramirez"),
        ("Emerald City FC B10 EA Coachella", "coachella"),
        ("Emerald City FC B09/10 Red EA", "red"),
        ("Emerald City FC EC B10 EA", "ec"),
    ],
)
def test_squad_qualifier_is_never_confident(name, token):
    assert _one(_ea(), _db("a", name)) == ("review", f"squad qualifier: {token}", ["a"])


@pytest.mark.parametrize("name", ["Emerald City FC B10 EA Boys", "Emerald City FC B10 Premier EA", "Emerald City FC 2010 EA"])
def test_plain_words_are_not_qualifiers(name):
    assert _one(_ea(), _db("a", name))[0] == "confident"


def test_qualifier_in_the_ea_teams_own_name_is_allowed():
    ea = _ea(name="Emerald City FC Mora")
    assert _one(ea, _db("a", "Emerald City FC B10 EA Mora"))[0] == "confident"


def test_team_linked_to_another_ea_team_this_season_is_not_a_candidate():
    db = _db("a", "Emerald City FC 2014 EA", ea_keys={"9:2026"})
    assert _one(_ea(), db) == ("no_match", "", [])


def test_team_linked_last_season_or_to_this_key_stays_a_candidate():
    assert _one(_ea(), _db("a", "Emerald City FC 2014 EA", ea_keys={"9:2025"}))[0] == "confident"
    assert _one(_ea(), _db("a", "Emerald City FC 2014 EA", ea_keys={"1:2026"}))[0] == "confident"
