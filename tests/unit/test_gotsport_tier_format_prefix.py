"""A division label may lead with its playing format, not its cohort.

The San Antonio Labor Cup (event 51783) names every one of its 58 divisions
that way -- ``11v11 U14B Gold``, ``5 Team 11v11 U13B Gold``, ``4v4 U7B Silver
Crossover``. Every cohort form in ``_COHORT_PREFIX_FORMS`` anchors at position
0, so none of them matched and all 58 groups resolved to cohort ``None``. The
tier walk then had no cohort to file a team under and the whole event produced
no tier memberships -- silently, because an unresolved cohort is a WARNING and
an empty result, not an error.

``_FORMAT_TOKEN_RE`` already strips the same token when it trails the label
(``B2017 Gold (4v4)``); these tests pin the leading spelling.
"""

import pytest

from src.scrapers.gotsport_tier_parser import parse_cohort_identity, strip_cohort_prefix


class TestLeadingFormatToken:
    """Labels measured off the live event-51783 landing page, 2026-09-10."""

    @pytest.mark.parametrize(
        "label,expected_prefix,expected_residue",
        [
            # The three U14 Boys divisions this was found on.
            ("11v11 U14B Gold", "U14B ", "Gold"),
            ("11v11 U14B Silver", "U14B ", "Silver"),
            ("11v11 U14B Bronze", "U14B ", "Bronze"),
            # Small-sided formats carry the same shape.
            ("4v4 U7B Silver Crossover", "U7B ", "Silver Crossover"),
            ("7v7 U10B Bronze", "U10B ", "Bronze"),
            ("9v9 U12B Gold", "U12B ", "Gold"),
            # A team-count phrase can precede the format token.
            ("5 Team 11v11 U13B Gold", "U13B ", "Gold"),
            ("7 Team 7v7 U9G Silver", "U9G ", "Silver"),
            # Genderless cohort still resolves.
            ("9v9 U10 Silver Crossover", "U10 ", "Silver Crossover"),
        ],
    )
    def test_a_leading_format_token_does_not_hide_the_cohort(self, label, expected_prefix, expected_residue):
        prefix, residue, outcome = strip_cohort_prefix(label)

        assert outcome == "matched"
        assert prefix == expected_prefix
        assert residue == expected_residue

    @pytest.mark.parametrize(
        "label,expected_cohort",
        [
            ("11v11 U14B Gold", ("u14", "M")),
            ("4v4 U7B Silver Crossover", ("u7", "M")),
            ("5 Team 11v11 U13B Gold", ("u13", "M")),
            ("7 Team 7v7 U9G Silver", ("u9", "F")),
        ],
    )
    def test_the_recovered_prefix_still_identifies_the_cohort(self, label, expected_cohort):
        """Stripping must hand ``parse_cohort_identity`` a span it can read.

        Returning a matched outcome whose prefix no longer parses would move the
        failure one step later and look like a different bug.
        """
        prefix, _, outcome = strip_cohort_prefix(label)

        assert outcome == "matched"
        assert parse_cohort_identity(prefix) == expected_cohort

    def test_the_trailing_spelling_still_works(self):
        """The suffix form predates this and must not regress."""
        prefix, residue, outcome = strip_cohort_prefix("B2017 Gold (4v4)")

        assert outcome == "matched"
        assert prefix == "B2017 "
        assert residue == "Gold"

    def test_a_format_token_alone_is_not_a_cohort(self):
        """Nothing follows the token, so there is no cohort to recover.

        Held by trying the unmodified label first: a label the forms already
        reject is still rejected once its format token is gone.
        """
        _, residue, outcome = strip_cohort_prefix("11v11")

        assert outcome == "unknown_prefix"
        assert residue == "11v11"

    @pytest.mark.parametrize(
        "label",
        [
            # Real labels from the same event that carry no resolvable cohort.
            "Gold",
            "Silver II",
            "Bronze Crossover",
            "Silver U17-U18",
        ],
    )
    def test_a_label_with_no_cohort_still_reports_unknown(self, label):
        """The fix must not manufacture a cohort out of a tier-only label."""
        prefix, residue, outcome = strip_cohort_prefix(label)

        assert outcome == "unknown_prefix"
        assert prefix == ""
        assert residue == label

    def test_a_bare_team_count_is_not_mistaken_for_a_reverse_age_token(self):
        """``5 Team`` must not be read as Form 5's ``12U`` reverse-token shape."""
        prefix, residue, outcome = strip_cohort_prefix("5 Team 9v9 U12G Bronze")

        assert outcome == "matched"
        assert prefix == "U12G "
        assert residue == "Bronze"
