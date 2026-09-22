"""Five branches were folded into their parents on 2026-09-22. None may come back.

A branch is its own club. The convention has always said so; what was new is the
evidence that settles it. A branch's teams routinely carry the PARENT's name --
"FC Golden State Orange County" fields teams called "FC Golden State B2015 EA" -- so a
team-name reading argues for the fold, and argues wrongly. The provider's own club list
is what decides: SincSports gives each of these its own club id, beside a separate id
for the parent.

Collapsing a branch does two things. Unrelated teams come to share a ``club_name`` and
become candidates for each other in the duplicate scan, which compares on exactly that
value. And the next import re-supplies the branch name, so the fold is re-applied every
Monday and the provider's identity is lost again each week.

**This is a regression guard, not a detector.** A derived version was tried and
abandoned: telling a branch from a provider duplicate needs a classifier -- "Revolution
FC (East County)" and "East County Revolution FC" are one club listed twice, "SF Seals
SC" and "San Francisco Seals" differ by an acronym, "Orchard Valley SC" is what "OV" in
"OV Toros FC" stands for -- and every narrowing of the rule pulled in a new false
positive. The transferable rule is prose, in the handoff and beside the entries: before
folding a name that adds a place to its canonical, read the provider's club list, not
only the team names.
"""

from __future__ import annotations

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest  # noqa: E402

import scripts.full_club_analysis as fca  # noqa: E402

# (the branch, the parent it was folded into, the provider ids that separate them)
COLLAPSED_BRANCHES = [
    ("FC Golden State Orange County", "FC Golden State", "CA708"),
    ("Legends FC - San Gabriel Valley", "Legends FC (CA)", "CA299 beside CA278"),
    ("ROSS Valley Breakers FC West Marin", "Ross Valley Breakers FC", "CA615"),
    ("Encinitas Express Soccer Club", "Express Soccer", "CA025"),
]


@pytest.mark.parametrize("branch,parent,provider_id", COLLAPSED_BRANCHES)
def test_a_branch_is_not_folded_into_its_parent(branch, parent, provider_id):
    for state, mtype, pattern, canonical in fca.CLUB_CANONICAL_OVERRIDES:
        if canonical.strip().lower() != parent.strip().lower():
            continue
        assert not fca._matches_override(branch, mtype, pattern), (
            f"{state} {mtype} {pattern!r} folds {branch!r} into {parent!r}, but the provider lists it as its own "
            f"club ({provider_id}). A branch is its own club; move individually vetted rows instead."
        )


@pytest.mark.parametrize("branch,parent,provider_id", COLLAPSED_BRANCHES)
def test_the_branch_and_its_parent_are_still_two_different_names(branch, parent, provider_id):
    """If a later round decides one of these IS a spelling, this is the line to delete --
    together with its entry above, so the list cannot rot into a set of names nothing
    reads any more."""
    assert branch.strip().lower() != parent.strip().lower(), f"{branch!r} and {parent!r} are the same name"
