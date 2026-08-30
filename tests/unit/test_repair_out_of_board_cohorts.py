"""Re-resolving a bad cohort must only write a cohort PitchRank actually boards.

GotSport's U-age advances every Aug 1 while a stored label does not, so a row
stamped `u3` a season ago reads back as `U4`. Writing that moves the team from one
unboarded cohort to another and churns again next year, which is what the first
dry run of this script did across 58 of 71 candidates. Only a boarded answer is
worth the write; everything else is left alone and reported.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from repair_out_of_board_cohorts import decide  # noqa: E402


def _resolved(age_group, raw=None):
    return {"age_group": age_group, "raw_age_group": raw if raw is not None else (age_group or "").upper()}


@pytest.mark.parametrize("new", ["u10", "u12", "u14", "u15", "u19"])
def test_a_boarded_cohort_is_written(new):
    assert decide("u3", "742007", _resolved(new)) == ("updated", new)


# u20 is absent on purpose: normalize_age_group folds it into u19, so it can never
# be the resolved value. test_a_label_that_folds_into_u19_is_not_written owns that case.
@pytest.mark.parametrize("new", ["u4", "u5", "u6", "u7", "u8", "u9", "u21"])
def test_an_unboarded_cohort_is_never_written(new):
    """The +1 rollover shift: u3 reads back as u4 a season later."""
    action, proposed = decide("u3", "742007", _resolved(new))
    assert action == "skipped_provider_cohort_unboarded"
    assert proposed == new


def test_an_unchanged_cohort_is_not_rewritten():
    assert decide("u14", "742007", _resolved("u14")) == ("skipped_already_correct", "u14")


def test_a_provider_with_no_cohort_is_left_alone():
    """display_age_group is "Open" for adult teams and absent for some records."""
    assert decide("u3", "742007", _resolved(None)) == ("skipped_provider_has_no_cohort", None)


def test_a_failed_lookup_never_writes():
    """The resolver returns {} for a WAF block, which must not read as an answer."""
    assert decide("u3", "742007", {}) == ("skipped_lookup_failed", None)
    assert decide("u3", "742007", None) == ("skipped_lookup_failed", None)


def test_a_team_with_no_gotsport_alias_is_left_alone():
    assert decide("u3", None, None) == ("skipped_no_alias", None)
    assert decide("u3", "", None) == ("skipped_no_alias", None)


def test_every_skip_reason_is_distinct():
    """The summary counts these by name; a collision would hide a population."""
    actions = {
        decide("u3", None, None)[0],
        decide("u3", "1", {})[0],
        decide("u3", "1", _resolved(None))[0],
        decide("u14", "1", _resolved("u14"))[0],
        decide("u3", "1", _resolved("u4"))[0],
        decide("u3", "1", _resolved("u14"))[0],
    }
    assert len(actions) == 6


def test_the_season_evidence_skip_is_distinct():
    assert decide("u3", "1", _resolved("u19", raw="U20"))[0] not in {
        decide("u3", "1", _resolved("u4"))[0],
        decide("u3", "1", _resolved("u14"))[0],
    }


@pytest.mark.parametrize("raw", ["U18", "U20", "u18", " u20 "])
def test_a_label_that_folds_into_u19_is_not_written(raw):
    """normalize_age_group collapses U18 and U20 into u19, which is right for a fresh
    label. Here it would write the oldest board off a label that never says which
    season produced it, so an aged-out 2006 squad could land on the U19 board."""
    action, proposed = decide("u3", "742007", _resolved("u19", raw=raw))
    assert action == "skipped_needs_season_evidence"
    assert proposed == "u19"


def test_a_genuine_u19_label_is_still_written():
    assert decide("u3", "742007", _resolved("u19", raw="U19")) == ("updated", "u19")
