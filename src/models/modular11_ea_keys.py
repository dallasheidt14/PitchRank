"""EA season keys and the club -> state table.

An EA team id names an age slot (club, age, tier) that keeps its id every season while the
players move up, so a link is only true for one season: PitchRank stores `<uid>:<season>`.

Each EA club has one state, decided with the assigning-team-states club rule and checked by
the owner. A roster club missing from the table stops the run rather than matching anywhere.
"""

import json
from datetime import date
from pathlib import Path

from src.utils.placeholder_clubs import is_placeholder_club

CLUB_STATES: dict[str, str] = json.loads(
    (Path(__file__).resolve().parents[2] / "config" / "modular11_ea_club_states.json").read_text(encoding="utf-8")
)


class UnknownClubError(KeyError):
    """An EA club the table does not hold; add it to config/modular11_ea_club_states.json."""


def ea_key(uid: str, season: int) -> str:
    return f"{uid}:{season}"


def split_ea_key(key: str) -> tuple[str, int]:
    uid, sep, season = key.partition(":")
    if not sep or not uid.isdigit() or not season.isdigit():
        raise ValueError(f"not a season-keyed EA id: {key!r}")
    return uid, int(season)


def season_start_year(today: date) -> int:
    return today.year if today.month >= 8 else today.year - 1


def club_state(ea_club: str) -> str:
    if is_placeholder_club(ea_club) or ea_club not in CLUB_STATES:
        raise UnknownClubError(ea_club)
    return CLUB_STATES[ea_club]
