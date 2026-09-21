"""The variant scan exists to raise a group, so the cases below are the groups it must raise.

Four of them are shapes the hand-rebuilt scan missed in Virginia and North Carolina, each
caught by the owner reading the club list rather than by the scan. They are pinned here so
the next state does not rediscover them: a redundant acronym tag the scan's own acronym
test could not see, `Assoc` beside `Assn`, `Youth` as an organisation word, and `ysa`/`ysl`
as trailing organisation tokens.

The pairs that must stay apart matter as much. A detector that groups everything is a
detector nobody reads, and the shipped grouping keeps "FC Arkansas" away from "Arkansas
Soccer Club" for a reason.
"""

import pytest

from scripts.full_club_analysis import Vocabulary
from scripts.scan_club_name_variants import (
    _ORG_WORDS,
    ORG_TOKENS,
    _acronym_form,
    _core_key,
    _singular,
    fetch_club_names,
    fetch_states,
    group_clubs,
    scan_keys,
    unresolved_groups,
)


def grouped(*clubs):
    """True when every name lands in one group."""
    groups = group_clubs(clubs)
    return len(groups) == 1 and sorted(groups[0]) == sorted(clubs)


# --- The four shapes the hand-rebuilt scan missed -------------------------------------


def test_redundant_acronym_tag_counting_an_abbreviation_as_itself():
    """A one-letter-per-word acronym gives "cus" and cannot see "(CUSC)" as redundant."""
    assert grouped("Chesapeake United SC", "Chesapeake United SC (CUSC)")


@pytest.mark.parametrize(
    "tagged, plain",
    [
        ("Northern Virginia SC (NVSC)", "Northern Virginia SC"),
        ("Greater Fredericksburg RSC (GFRSC)", "Greater Fredericksburg RSC"),
    ],
)
def test_other_redundant_acronym_tags_fold(tagged, plain):
    assert grouped(tagged, plain)


def test_assoc_folds_beside_assn_and_association():
    assert grouped(
        "Pitt Greenville Soccer Association",
        "Pitt Greenville Soccer Assn",
        "Pitt Greenville Soccer Assoc",
    )


def test_youth_is_an_organisation_word():
    """Without it, "Havelock Youth Soccer" keeps a `youth` the short spelling never had."""
    assert grouped("Havelock Youth Soccer Association", "Havelock SC")


@pytest.mark.parametrize("trailing", ["YSA", "YSL", "YSC", "SA", "SL"])
def test_trailing_organisation_tokens_fold(trailing):
    assert grouped(f"Wilson Youth {trailing}", "Wilson Youth Soccer Association")


# --- The shapes the scan was already expected to reach ---------------------------------


def test_soccer_club_folds_onto_sc():
    assert grouped("Inwood SC", "Inwood Soccer Club")


def test_case_and_redundant_tag_fold_together():
    assert grouped("El Paso Premier League", "EL PASO PREMIER LEAGUE (EPPL)")


def test_accents_fold():
    assert grouped("Barça Academy Carolinas", "Barca Academy Carolinas")


def test_punctuation_and_legal_suffix_fold():
    assert grouped("Wake Futbol Club, Inc", "Wake FC")


def test_word_order_folds_when_the_organisation_word_is_the_same():
    assert grouped("FC Dallas", "Dallas FC")


def test_a_bare_acronym_joins_the_name_it_spells():
    assert grouped("CVYSA", "Catawba Valley Youth Soccer Association")


# --- The pairs that must stay apart ----------------------------------------------------


def test_a_leading_fc_does_not_fold_onto_a_trailing_sc():
    assert group_clubs(["FC Arkansas", "Arkansas Soccer Club"]) == []


def test_a_branch_stays_its_own_club():
    assert group_clubs(["Richmond Strikers", "Richmond Strikers South"]) == []


def test_a_tier_word_is_not_an_organisation_word():
    assert group_clubs(["Charlotte United", "Charlotte Elite"]) == []


def test_two_clubs_sharing_an_acronym_do_not_group_on_it():
    """Only a name that *is* an acronym reaches the acronym link."""
    assert group_clubs(["Texas Spurs FC", "Tyler Select FC"]) == []


def test_an_organisation_word_run_is_never_stripped_to_nothing():
    assert _core_key("Soccer Club") == "soccer|club"


def test_acronym_form_is_empty_for_a_multi_word_name():
    assert _acronym_form("Catawba Valley Youth Soccer Association") == ""
    assert _acronym_form("CVYSA") == "cvysa"


def test_scan_keys_namespace_core_and_sorted_separately():
    assert scan_keys("Inwood SC") == {"core:inwood", "sorted:inwood|sc"}


# --- The singular fold and the organisation set must agree ------------------------------


def test_an_ies_plural_still_reads_as_an_organisation_word():
    """`_singular` turns "academies" into "academie", which the set has to hold too."""
    assert grouped("Alpha Academy", "Alpha Academies")


def test_every_organisation_word_survives_singularising():
    missing = sorted(word for word in _ORG_WORDS if _singular(word) not in ORG_TOKENS)
    assert missing == []


# --- Paging must not read a capped page as the last one --------------------------------


class _CappedTable:
    """A `teams` table whose range response is capped, as PostgREST's max-rows caps it.

    1,000 is the cap a local `supabase start` commits in supabase/config.toml. The double
    returns rows only at `execute()`, because that is where the request is actually made.
    """

    def __init__(self, rows, cap):
        self._rows, self._cap, self._lo, self._hi = rows, cap, 0, 0
        self.column = None
        self.ranges = []

    def select(self, column):
        self.column = column
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args):
        return self

    def range(self, lo, hi):
        self._lo, self._hi = lo, hi
        return self

    def execute(self):
        self.ranges.append((self._lo, self._hi))
        window = self._rows[self._lo : self._hi + 1][: self._cap]
        return type("Result", (), {"data": [{self.column: value} for value in window]})()


class _Client:
    def __init__(self, table):
        self._table = table

    def table(self, name):
        assert name == "teams"
        return self._table


def test_a_capped_page_is_not_the_last_page():
    rows = [f"Club {i}" for i in range(2500)]
    table = _CappedTable(rows, cap=1000)

    assert fetch_club_names(_Client(table)) == rows
    assert len(table.ranges) == 4


def test_states_page_past_the_cap_too():
    rows = ["TX"] * 1000 + ["CA"] * 1000 + ["NY"] * 200
    assert fetch_states(_Client(_CappedTable(rows, cap=1000))) == ["CA", "NY", "TX"]


def test_a_blank_state_is_not_a_state():
    assert fetch_states(_Client(_CappedTable(["TX", None, "", "CA"], cap=1000))) == ["CA", "TX"]


# --- Groups already resolved upstream must not be listed -------------------------------

VOCABULARY = Vocabulary(spellings={}, mixed_names={})


def team(club, name="Sample B2014 Blue", state="TX"):
    return {"team_id_master": f"{club}-{name}", "team_name": name, "club_name": club, "state_code": state}


def test_a_group_an_override_already_folds_is_not_listed():
    """"Lonestar SC" has a TX override onto "Lonestar", so the pair is resolved, not open."""
    teams = [team("Lonestar SC"), team("Lonestar")]
    assert unresolved_groups(teams, "TX", VOCABULARY) == []


def test_a_group_the_automatic_pass_already_folds_is_not_listed():
    teams = [team("Bayside Soccer Club"), team("Bayside SC")]
    assert unresolved_groups(teams, "TX", VOCABULARY) == []


def test_an_open_group_is_listed_with_its_counts_and_team_names():
    teams = [
        team("Bayside Youth Soccer Association", "BYSA B2014 Red"),
        team("Bayside Youth Soccer Association", "BYSA G2013 Blue"),
        team("Bayside YSA", "BYSA B2012 White"),
    ]
    groups = unresolved_groups(teams, "TX", VOCABULARY, samples=2)

    assert groups == [
        {
            "state": "TX",
            "teams": 3,
            "variants": [
                {
                    "club": "Bayside Youth Soccer Association",
                    "teams": 2,
                    "sample_team_names": ["BYSA B2014 Red", "BYSA G2013 Blue"],
                },
                {"club": "Bayside YSA", "teams": 1, "sample_team_names": ["BYSA B2012 White"]},
            ],
        }
    ]


def test_a_rule_for_another_state_does_not_resolve_this_state():
    """`Lonestar SC` is a TX rule; the same pair in Oklahoma is still an open question."""
    teams = [team("Lonestar SC", state="OK"), team("Lonestar", state="OK")]
    groups = unresolved_groups(teams, "OK", VOCABULARY)

    assert [v["club"] for g in groups for v in g["variants"]] == ["Lonestar", "Lonestar SC"]
