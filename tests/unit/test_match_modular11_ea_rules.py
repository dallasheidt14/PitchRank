"""Same-club, same-age, same-tier rules for linking EA teams to existing ones."""

from scripts.match_modular11_ea_teams import EaTeam, classify, is_protected, tier_marker


def _ea(tid="1", club="Emerald City FC", tiers=("EA",)):
    return EaTeam(provider_team_id=tid, club_name=club, display_name=club, age_group="u13", tiers=frozenset(tiers))


def _db(tid, name, club="Emerald City FC"):
    return {
        "team_id_master": tid,
        "team_name": name,
        "club_name": club,
        "state_code": "WA",
        "provider_code": "gotsport",
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


def test_candidate_claimed_by_two_ea_clubs_goes_to_review():
    # are_same_club treats a club and its branch as one; the shared claim must block a confident link.
    rush = _ea("1", club="Colorado Rush")
    cos = _ea("2", club="Colorado Rush - COS")
    rows = classify([rush, cos], [_db("a", "Colorado Rush 2014 EA", club="Colorado Rush")])
    assert {r.ea.provider_team_id: r.bucket for r in rows} == {"1": "review", "2": "review"}


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
