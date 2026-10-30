"""A state change as the week's review judges it (review_states.py): the review's verdicts and how a card words
each one. The automatic lane chooses as it does for a club change (club_changes.change_choice): Don't apply where
the reviewers found the stored value right, which records the decline."""

from __future__ import annotations

from scripts.team_cleanup.decisions import APPLY
from scripts.team_cleanup.pairs import HOLD, REJECT

STATE_VERDICTS = (APPLY, HOLD, REJECT)
STATE_REVIEW_WORDS = {
    APPLY: "reviewers found its own name settles it",
    HOLD: "reviewers held it",
    REJECT: "reviewers found the stored state right",
}
