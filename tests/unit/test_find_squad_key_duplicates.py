"""Tests for the Doorway D squad-key duplicate detector.

Birth years are written relative to CURRENT_YEAR, because the cohort a year names moves every
Aug 1 and a literal year would turn these tests into claims about one season.

Each screen gets a fixture violating exactly that screen, and a two-sided screen gets one
fixture per side, so deleting or narrowing any one guard fails a test of its own.
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import find_squad_key_duplicates as fsk  # noqa: E402
from tests.unit.test_find_cross_provider_duplicates import _Supabase  # noqa: E402

GS, TGS, PM, M11 = "prov-gotsport", "prov-tgs", "prov-playmetrics", "prov-modular11"
PROVIDERS = {GS: "gotsport", TGS: "tgs", PM: "playmetrics", M11: "modular11"}


def born(age):
    """The younger birth year of the band that is `age` this season."""
    return fsk.CURRENT_YEAR - age + 1


def yy(year):
    return f"{year % 100:02d}"


def team(team_id, name, *, club="Colorado EDGE", provider=GS, age_group="u12", gender="Male", state="CO"):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "team_name_original": None,
        "club_name": club,
        "age_group": age_group,
        "gender": gender,
        "state_code": state,
        "provider_id": provider,
        "provider_team_id": f"{team_id}-pid",
    }


def game(game_id, home, away, date, *, is_excluded=False):
    return {
        "id": game_id,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "game_date": date,
        "is_excluded": is_excluded,
    }


def pair_ids(pairs):
    return {frozenset((p["a"]["team_id_master"], p["b"]["team_id_master"])) for p in pairs}


# --- squad key ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        (f"ESC- {born(12)} Purple", f"EDGE Purple {yy(born(12))}B"),
        (f"Colorado EDGE Pre-ECNL B{born(12) - 1}/{yy(born(12))} Select", "Colorado EDGE U12B Pre ECNL Select"),
        ("U12B Grey", f"CO EDGE {yy(born(12))}B Gray"),
        (f"EDGE {born(12)}B UNTIED", "EDGE U12B United"),
        ("EDGE U-12B Gold", "EDGE Under 12 Gold"),
        (f"EDGE '{yy(born(12))} Gold", "EDGE U12 Gold"),
        (f"EDGE '{yy(born(12) - 1)}/'{yy(born(12))} Gold", f"EDGE {yy(born(12) - 1)}/{yy(born(12))} Gold"),
        (f"EDGE {born(12) - 1} / {yy(born(12))} Gold", f"EDGE {born(12) - 1}/{yy(born(12))} Gold"),
        (f"EDGE B{yy(born(12) - 1)}/B{yy(born(12))} Gold", f"EDGE {yy(born(12) - 1)}/{yy(born(12))}B Gold"),
        ("EDGE U12B 11v11 Gold", "EDGE U12B Gold"),
        (f"EDGE {yy(born(12))} Boys Gold", f"EDGE {born(12)} Gold"),
        ("EDGE PreECNL Gold", "EDGE Pre-ECNL Gold"),
        (f"EDGE {yy(born(12) - 1)}/{yy(born(12))}U Gold", "EDGE U12 Gold"),
        (f"{yy(born(12))} EDGE Gold", f"EDGE {born(12)} Gold"),
        (f"{yy(born(12))}(B) EDGE Gold", f"EDGE {born(12)} Gold"),
        (f"EDGE B{yy(born(12))} Gold", f"EDGE {born(12)} Gold"),
        (f"EDGE {yy(born(12))} Girls Gold", f"EDGE {born(12)} Gold"),
        (f"EDGE Boys {yy(born(12))} Gold", f"EDGE {born(12)} Gold"),
        (f"EDGE Girls {yy(born(12))} Gold", f"EDGE {born(12)} Gold"),
        (f"EDGE {yy(born(12) - 1)}-{yy(born(12))} Gold", "EDGE U12 Gold"),
        (f"EDGE {yy(born(12) - 1)}\u2013{yy(born(12))} Gold", "EDGE U12 Gold"),
        (f"EDGE {yy(born(12) - 1)}B/{yy(born(12))} Gold", "EDGE U12 Gold"),
        ("EDGE U11/U12B Gold", "EDGE U11/12 Gold"),
        ("EDGE 11U-12U Gold", "EDGE U11/12 Gold"),
        ("EDGE U11\u201312 Gold", "EDGE U11-12 Gold"),
        ("EDGE U12B Gold DPLO", "EDGE U12B Gold"),
        ("EDGE U12B Gold ECRL", "EDGE U12B Gold"),
    ],
)
def test_one_squad_spelled_two_ways_shares_a_key(a, b):
    assert fsk.squad_key(a, "Colorado EDGE", "CO") == fsk.squad_key(b, "Colorado EDGE", "CO") != frozenset()


def test_a_squad_word_the_other_name_lacks_changes_the_key():
    assert fsk.squad_key("EDGE U12B Academy II", "Colorado EDGE") != fsk.squad_key("EDGE U12B Academy", "Colorado EDGE")


@pytest.mark.parametrize(
    "a, b",
    [
        (f"Colorado Rush {yy(born(13))} Blue", f"Colorado Rush {yy(born(12))} Blue"),
        ("Rush U12B Academy 11", "Rush U12B Academy 12"),
        (f"Rush B{born(12)} Academy {yy(born(12))}", f"Rush B{born(12)} Academy"),
        ("Rush U12B 14 Gold", "Rush U12B Gold"),
        ("Rush U12B 11/ Gold", "Rush U12B 12/ Gold"),
        ("7v7 14 Gold", "7v7 15 Gold"),
    ],
)
def test_a_number_the_cohort_reader_did_not_take_stays_in_the_key(a, b):
    assert fsk.squad_key(a, "Colorado Rush") != fsk.squad_key(b, "Colorado Rush")


@pytest.mark.parametrize("tier", ["NPL", "DPL", "Academy"])
def test_a_pre_tier_keeps_its_prefix_so_it_never_shares_the_full_tier_s_key(tier):
    assert fsk.squad_key(f"Club Pre-{tier} Gold", "Club") != fsk.squad_key(f"Club {tier} Gold", "Club")


def test_pre_before_a_league_is_league_wording():
    assert fsk.squad_key("Club Pre-ECNL Gold", "Club") == fsk.squad_key("Club Gold", "Club")


def test_club_initials_are_removed_only_as_a_subsequence_of_the_club():
    assert fsk.is_club_initials("cis", ["colorado", "ice", "soccer"])
    assert not fsk.is_club_initials("wc", ["albion", "sc", "colorado"])


SIX_WORD_CLUB = ["rocky", "mountain", "colorado", "front", "range", "united"]


@pytest.mark.parametrize("token, is_initials", [("rm", True), ("rmcfr", True), ("r", False), ("rmcfru", False)])
def test_club_initials_run_two_to_five_letters(token, is_initials):
    assert fsk.is_club_initials(token, SIX_WORD_CLUB) is is_initials


def test_a_name_holding_only_club_age_and_league_words_has_no_key():
    assert fsk.squad_key(f"Colorado EDGE SC PRE-ECNL {born(12)}", "Colorado EDGE") == frozenset()


# --- cohort ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        (f"Club {born(12)}B Gold", "Club U12B Gold"),
        (f"Club B{born(12) - 1}/{yy(born(12))} Gold", f"Club {born(12) - 1}B Gold"),
        (f"Club '{yy(born(12) - 1)}/'{yy(born(12))} Gold", f"Club {born(12) - 1} Gold"),
        ("Club Gold", "Club U12B Gold"),
        ("Club GU18/19 Gold", "Club U19 Gold"),
        (f"Club {born(13) - 1} {born(13)} Gold", f"Club {born(13)} Gold"),
    ],
)
def test_names_that_can_state_one_cohort_are_compatible(a, b):
    assert fsk.cohorts_compatible(a, b)


@pytest.mark.parametrize(
    "a, b",
    [
        (f"Club {born(14)} Elite", f"Club {born(13)} Elite"),
        ("Club U12G Black", "Club U11G Black"),
        (f"Club {yy(born(18))}B South", f"Club {yy(born(19) - 1)}/{yy(born(19))}B South"),
        (f"Club {born(11)}B Grey", "Club U12B Grey"),
        (f"Club U12B {born(12)} Gold", "Club U11B Gold"),
    ],
)
def test_names_stating_two_cohorts_are_refused(a, b):
    assert not fsk.cohorts_compatible(a, b)


@pytest.mark.parametrize(
    "contradictory",
    [f"EDGE U12B B{born(13) - 1}/{yy(born(13))} Gold", f"EDGE B{born(12) - 1}/{yy(born(12))} B{born(14)} Gold"],
)
def test_a_name_whose_own_age_tokens_disagree_pairs_with_nothing(contradictory):
    assert fsk.stated_cohort(contradictory)[0] == set()
    assert not fsk.cohorts_compatible(contradictory, f"EDGE B{born(12) - 1}/{yy(born(12))} Gold")
    assert not fsk.cohorts_compatible(contradictory, "EDGE Gold")
    assert not fsk.cohorts_compatible("EDGE Gold", contradictory)


SEASON_LABEL = f"{fsk.CURRENT_YEAR - 1}-{yy(fsk.CURRENT_YEAR)}"


@pytest.mark.parametrize("name", ["Club U4 Gold", "Club U30 Gold", f"Club {SEASON_LABEL} Gold"])
def test_a_number_outside_the_youth_ages_states_no_cohort(name):
    assert fsk.stated_cohort(name) == (None, set())


def test_two_years_that_are_not_consecutive_are_not_a_band():
    ages, _ = fsk.stated_cohort(f"Club {born(13)}/{yy(born(11))} Gold")
    assert ages == {13, 12}


@pytest.mark.parametrize(
    "name", ["Club U11/U12G Gold", "Club 11U-12U Gold", "Club 11u/12u Gold", "Club 11/12U Gold", "Club BU11/12 Gold"]
)
def test_a_u_age_range_allows_both_ages_in_every_spelling(name):
    assert fsk.stated_cohort(name)[0] == {11, 12}


def test_a_game_format_is_not_read_as_a_u_age():
    assert fsk.stated_cohort("Club U13/11 v 11 Blue")[0] == {13}
    assert not fsk.cohorts_compatible("Club U13/11 v 11 Blue", "Club U11 v 11 Blue")


# --- league ------------------------------------------------------------------------------


def test_ecnl_and_ecnl_rl_conflict():
    assert fsk.leagues_conflict("Rush Academy Blue ECNL", "Rush Academy Blue ECNL RL")


def test_pre_ecnl_moving_up_to_ecnl_does_not_conflict():
    assert not fsk.leagues_conflict("Rapids Pre-ECNL B14 I", "Storm ECNL B2013/14")


def test_a_name_stating_no_league_conflicts_with_nothing():
    assert not fsk.leagues_conflict("Rush Academy Blue", "Rush Academy Blue NPL")


@pytest.mark.parametrize(
    "a, b",
    [("Blue RL", "Blue ECNL"), ("Blue ECRL", "Blue ECNL"), ("Blue DPLO", "Blue NPL"), ("Blue NPL", "Blue DPL"),
     ("Blue GA", "Blue ECNL"), ("Blue MLS NEXT", "Blue GA")],
)
def test_every_league_spelling_is_read(a, b):
    assert fsk.leagues_conflict(a, b)


# --- survivor name -----------------------------------------------------------------------


def test_names_rank_band_or_u_age_then_bare_year_then_none_then_stale():
    assert fsk.name_rank(f"Club B{yy(born(12) - 1)}/B{yy(born(12))} Gold", "u12") == 2
    assert fsk.name_rank("Club U12B Gold", "u12") == 2
    assert fsk.name_rank(f"Club B{born(12) - 1}/{yy(born(12))} Gold", "u12") == 2
    assert fsk.name_rank(f"Club {born(12)}B Gold", "u12") == 1
    assert fsk.name_rank("Club Gold", "u12") == 0
    assert fsk.name_rank("Club U13B Gold", "u12") == -1


def test_a_u18_name_fits_the_u19_board():
    assert not fsk.contradicts_stored_cohort("EDGE U18B Purple", "u19")
    assert fsk.contradicts_stored_cohort("EDGE U17B Purple", "u19")


# --- pairing -----------------------------------------------------------------------------


def test_a_null_club_borrows_the_longest_club_its_name_starts_with():
    teams = [
        team("a", "Real Colorado U12B Gold", club="Real Colorado"),
        team("b", "Foxes U12B Gold", club="Real Colorado Foxes"),
        team("c", "Real Colorado Foxes U12B Blue", club=None),
    ]
    assert fsk.effective_clubs(teams)["c"] == "Real Colorado Foxes"


def test_a_null_club_borrows_only_a_club_its_name_starts_with():
    teams = [team("a", "Foxes U12B Gold", club="Foxes"), team("c", "Real Foxes U12B Blue", club=None)]
    assert fsk.effective_clubs(teams)["c"] is None


def test_a_club_of_punctuation_alone_is_never_borrowed():
    teams = [team("a", "U12B Gold", club="--"), team("c", "Anything U12B Blue", club=None)]
    assert fsk.effective_clubs(teams)["c"] is None


def test_two_spellings_of_one_squad_pair():
    admitted, _ = fsk.build_pairs(
        [team("a", f"ESC- {born(12)} Purple", provider=TGS), team("b", f"EDGE Purple {yy(born(12))}B")], PROVIDERS
    )
    assert pair_ids(admitted) == {frozenset({"a", "b"})}


def test_rows_with_no_squad_key_never_pair():
    teams = [team("a", "Colorado EDGE U12B"), team("b", f"EDGE {born(12)}B", provider=TGS)]
    assert fsk.build_pairs(teams, PROVIDERS) == ([], [])


@pytest.mark.parametrize(
    "field, value", [("age_group", "u13"), ("gender", "Female"), ("state", "UT"), ("club", "Real Colorado")]
)
def test_rows_differing_in_cohort_identity_never_pair(field, value):
    teams = [team("a", "EDGE U12B Purple"), team("b", "EDGE U12B Purple", **{field: value})]
    assert fsk.build_pairs(teams, PROVIDERS) == ([], [])


def test_clubs_differing_only_in_an_org_suffix_are_different_clubs():
    teams = [team("a", "U12B Purple", club="FC Arkansas"), team("b", "U12B Purple", club="Arkansas SC")]
    assert fsk.build_pairs(teams, PROVIDERS) == ([], [])


@pytest.mark.parametrize("missing", ["age_group", "gender"])
def test_a_row_with_no_age_group_or_gender_is_skipped(missing):
    teams = [team("a", "EDGE U12B Purple", **{missing: None}), team("b", "EDGE U12B Purple", **{missing: None})]
    assert fsk.build_pairs(teams, PROVIDERS) == ([], [])


def test_a_modular11_row_is_out_of_scope():
    teams = [team("a", "EDGE U12B Purple"), team("b", "EDGE U12B Purple", provider=M11)]
    assert fsk.build_pairs(teams, PROVIDERS) == ([], [])


DIVISION = "an AD, HD, EA or MLS division name"


@pytest.mark.parametrize(
    "a_name, b_name, reason",
    [
        ("EDGE BU12 Purple EA", "EDGE U12B Purple EA", DIVISION),
        ("EDGE U12B Purple MLS-Next", "EDGE U12B Purple", DIVISION),
        ("EDGE U12B Purple ECNL MLS-Next", "EDGE U12B Purple ECNL", DIVISION),
        (f"EDGE {born(12)} MLS Purple", "EDGE U12B Purple", DIVISION),
        ("EDGE U12B Purple", "EDGE U12B Purple MLS NEXT", DIVISION),
        ("EDGE U12B Purple", f"EDGE {born(12)} MLS Purple", DIVISION),
        ("EDGE U12B PreMLS Purple", "EDGE U12B Purple", DIVISION),
        ("EDGE U12B Purple", "EDGE U12B Pre-MLS Purple", DIVISION),
        ("EDGE U12B Purple", f"EDGE {born(11)}B Purple", "the names state different birth cohorts"),
        ("EDGE U12B Purple ECNL", "EDGE U12B Purple ECNL RL", "the names state different leagues"),
        ("EDGE U12B Purple", "EDGE U12G Purple", "the registered names state opposite genders (Male vs Female)"),
    ],
)
def test_each_name_screen_refuses_on_its_own(a_name, b_name, reason):
    _, refused = fsk.build_pairs([team("a", a_name), team("b", b_name)], PROVIDERS)
    assert [p["reason"] for p in refused] == [reason]


# --- scan --------------------------------------------------------------------------------


def _double(teams, games=(), merges=()):
    return _Supabase(
        {
            "providers": [{"id": k, "code": v} for k, v in PROVIDERS.items()],
            "teams": [{**t, "is_deprecated": False} for t in teams],
            "games": list(games),
            "team_merge_map": [{**m, "id": f"m{i}"} for i, m in enumerate(merges)],
        },
        cap=1000,
    )


def _scan(teams, games=(), merges=()):
    return fsk.scan(_double(teams, games, merges), SimpleNamespace(state=None, age_group=None))


def _only(records, status):
    matching = [r for r in records if r["status"] == status]
    assert len(matching) == 1, records
    return matching[0]


def _purple_pair():
    return [team("gs", "EDGE U12B Purple"), team("tgs", f"ESC- {born(12)} Purple", provider=TGS)]


def test_scan_proposes_a_clean_pair_keeping_the_better_named_row_over_the_busier_one():
    games = [game("g1", "tgs", "o1", "2026-09-05"), game("g2", "tgs", "o2", "2026-09-12"),
             game("g3", "gs", "o3", "2026-09-19")]
    rec = _only(_scan(_purple_pair(), games), fsk.PROPOSED)
    assert (rec["keep_id"], rec["merge_id"]) == ("gs", "tgs")
    assert (rec["games_a"], rec["games_b"]) == (1, 2)


def test_scan_breaks_an_equal_name_rank_on_games_before_the_last_date():
    teams = [team("a", "EDGE U12B Purple"), team("b", "EDGE U12 Boys Purple", provider=TGS)]
    games = [game("g1", "a", "o1", "2026-09-05"), game("g2", "a", "o2", "2026-09-06"),
             game("g3", "b", "o3", "2026-09-20")]
    assert _only(_scan(teams, games), fsk.PROPOSED)["keep_id"] == "a"


def test_scan_breaks_equal_names_and_games_on_the_last_date():
    teams = [team("a", "EDGE U12B Purple"), team("b", "EDGE U12 Boys Purple", provider=TGS)]
    games = [game("g1", "a", "o1", "2026-09-05"), game("g2", "b", "o2", "2026-09-20")]
    assert _only(_scan(teams, games), fsk.PROPOSED)["keep_id"] == "b"


@pytest.mark.parametrize(
    "games, reason",
    [
        ([game("g1", "gs", "tgs", "2026-09-05")], "the two records played each other"),
        ([game("g1", "gs", "o1", "2026-09-05"), game("g2", "tgs", "o2", "2026-09-05")],
         "both played a game on the same day"),
        ([game("g1", "gs", "gs", "2026-09-05", is_excluded=True)],
         "a row carries a self-play game and is already two squads"),
        ([game("g1", "tgs", "tgs", "2026-09-05", is_excluded=True)],
         "a row carries a self-play game and is already two squads"),
    ],
)
def test_scan_refuses_on_each_game_screen_alone(games, reason):
    assert _only(_scan(_purple_pair(), games), fsk.REJECTED)["reason"] == reason


def test_scan_reads_a_shared_date_through_a_row_merged_into_a_candidate():
    games = [game("g1", "gs", "o1", "2026-09-05"), game("g2", "old", "o2", "2026-09-05")]
    merges = [{"deprecated_team_id": "old", "canonical_team_id": "tgs"}]
    assert _only(_scan(_purple_pair(), games, merges), fsk.REJECTED)["reason"] == "both played a game on the same day"


def test_scan_records_a_name_refused_pair_with_both_ids():
    teams = [team("a", "EDGE U12B Purple ECNL"), team("b", "EDGE U12B Purple ECNL RL", provider=TGS)]
    rec = _only(_scan(teams), fsk.REJECTED)
    assert rec["reason"] == "the names state different leagues"
    assert {rec["keep_id"], rec["merge_id"]} == {"a", "b"}


def test_scan_holds_every_pair_of_a_three_row_cluster():
    teams = [*_purple_pair(), team("pm", "U12B Purple", club="Colorado EDGE", provider=PM)]
    records = _scan(teams)
    assert {r["status"] for r in records} == {fsk.HELD}
    assert {frozenset((r["keep_id"], r["merge_id"])) for r in records} == {
        frozenset({"gs", "tgs"}), frozenset({"gs", "pm"}), frozenset({"tgs", "pm"})
    }


@pytest.mark.parametrize("hub_first", [True, False])
def test_scan_holds_a_row_with_two_partners_whichever_side_it_sits(hub_first):
    hub = team("hub", "EDGE U12B Purple")
    spokes = [team("ecnl", "EDGE U12B Purple ECNL", provider=TGS), team("rl", "EDGE U12B Purple ECNL RL", provider=PM)]
    records = _scan([hub, *spokes] if hub_first else [*spokes, hub])
    assert [r["reason"] for r in records if r["status"] == fsk.HELD] == [
        "a row pairs with more than one row of its club"
    ] * 2
    assert not [r for r in records if r["status"] == fsk.PROPOSED]


def test_scan_leaves_out_a_live_row_that_already_resolves_to_another():
    teams = [team("a", "EDGE U12B Purple"), team("b", f"ESC- {born(12)} Purple", provider=TGS)]
    assert _scan(teams, merges=[{"deprecated_team_id": "a", "canonical_team_id": "b"}]) == []


def test_scan_never_proposes_both_halves_of_a_merge_cycle():
    teams = [
        team("x", "Rapids U12 Gold", club="Rapids"),
        team("xp", "Rapids Gold", club="Rapids"),
        team("b", f"Rapids {born(12)} Gold", club="Rapids", provider=TGS),
    ]
    records = _scan(teams, merges=[{"deprecated_team_id": "x", "canonical_team_id": "xp"}])
    assert [(r["status"], {r["keep_id"], r["merge_id"]}) for r in records] == [(fsk.PROPOSED, {"xp", "b"})]


def test_scan_does_not_hold_a_clean_pair_for_a_partner_the_game_screens_rejected():
    teams = [*_purple_pair(), team("pm", "U12B Purple", club="Colorado EDGE", provider=PM)]
    games = [game("g1", "gs", "o1", "2026-09-05"), game("g2", "pm", "o2", "2026-09-05"),
             game("g3", "tgs", "o3", "2026-09-12"), game("g4", "pm", "o4", "2026-09-12")]
    rec = _only(_scan(teams, games), fsk.PROPOSED)
    assert {rec["keep_id"], rec["merge_id"]} == {"gs", "tgs"}


def test_scan_holds_a_pair_neither_of_whose_names_fits_the_stored_cohort():
    teams = [team("a", "EDGE U11B Purple"), team("b", f"EDGE {born(11)}B Purple", provider=TGS)]
    assert _only(_scan(teams), fsk.HELD)["reason"] == "neither name fits the stored age group"


@pytest.mark.parametrize("stale_first", [True, False])
def test_scan_proposes_a_pair_where_only_one_name_is_stale(stale_first):
    stale, fits = team("a", "EDGE U11B Purple"), team("b", f"EDGE {born(12)}B Purple", provider=TGS)
    rec = _only(_scan([stale, fits] if stale_first else [fits, stale]), fsk.PROPOSED)
    assert rec["keep_id"] == "b"


# --- output ------------------------------------------------------------------------------


def test_the_csv_escapes_provider_text_a_spreadsheet_would_run(tmp_path):
    records = _scan([team("a", "=EDGE U12B Purple"), team("b", f"=ESC- {born(12)} Purple", provider=TGS)])
    path = tmp_path / "out.csv"
    fsk.write_csv(path, records)
    body = path.read_text(encoding="utf-8")
    assert "'=EDGE U12B Purple" in body
    assert ",=EDGE" not in body


def test_records_carry_each_row_s_registered_name_on_its_own_side():
    teams = [{**t, "team_name_original": f"{t['team_id_master']} as registered"} for t in _purple_pair()]
    rec = _only(_scan(teams), fsk.PROPOSED)
    names = {rec["name_a"]: rec["name_original_a"], rec["name_b"]: rec["name_original_b"]}
    assert names == {"EDGE U12B Purple": "gs as registered", f"ESC- {born(12)} Purple": "tgs as registered"}


def test_main_names_an_age_group_run_s_files_after_the_age_group(tmp_path, monkeypatch):
    monkeypatch.setattr(fsk, "get_client", lambda: _double(_purple_pair()))
    monkeypatch.setattr(sys, "argv", ["prog", "--state", "CO", "--age-group", "U12", "--out-dir", str(tmp_path)])
    assert fsk.main() == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "squad_key_duplicates_co_u12.csv", "squad_key_duplicates_co_u12.json"
    ]


def test_main_writes_only_proposals_to_the_json(tmp_path, monkeypatch):
    teams = [*_purple_pair(), team("x", "EDGE U12B Gold ECNL"), team("y", "EDGE U12B Gold ECNL RL", provider=TGS)]
    monkeypatch.setattr(fsk, "get_client", lambda: _double(teams))
    monkeypatch.setattr(sys, "argv", ["prog", "--state", "CO", "--out-dir", str(tmp_path)])
    assert fsk.main() == 0
    proposed = json.loads((tmp_path / "squad_key_duplicates_co.json").read_text(encoding="utf-8"))
    assert [(r["status"], r["merge_id"]) for r in proposed] == [(fsk.PROPOSED, "tgs")]
    csv_lines = (tmp_path / "squad_key_duplicates_co.csv").read_text(encoding="utf-8").splitlines()
    assert csv_lines[0].split(",") == list(fsk.RECORD_FIELDS)
    assert len(csv_lines) == 3
