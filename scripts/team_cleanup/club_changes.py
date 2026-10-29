"""A club-name change as the week's review judges it (review_clubs.py) and the automatic lane carries it out:
the review's verdicts, how a card words each one, and the lane's choice on a reviewed change."""

from __future__ import annotations

from scripts.team_cleanup.decisions import APPLY, DONT_APPLY
from scripts.team_cleanup.pairs import HOLD, REJECT
from scripts.team_cleanup.run_store import CHANGE_REVIEW_KEYS

CLUB_VERDICTS = (APPLY, HOLD, REJECT)
CLUB_REVIEW_WORDS = {
    APPLY: "reviewers approved it",
    HOLD: "reviewers held it",
    REJECT: "reviewers found the stored club right",
}


def change_key(change: dict) -> tuple:
    """A review row's key for its change (CHANGE_REVIEW_KEYS)."""
    return tuple(change[key] for key in CHANGE_REVIEW_KEYS)


def change_choice(change: dict) -> dict:
    """The automatic lane's choice on a club change: Don't apply when its review found the stored club right,
    which records the decline, else Apply."""
    review = change.get("review") or {}
    return {"decision": DONT_APPLY if review.get("verdict") == REJECT else APPLY}
