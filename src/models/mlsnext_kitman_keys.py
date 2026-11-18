"""MLS NEXT Kitman season keys, the club -> state table and the clubs that play up.

A Kitman squad id names one club's team at one age in one division. Whether it survives into next
season is unknown, so PitchRank stores `<squad id>:<season>` and a link is only true for the
season that wrote it.

Kitman gives no state. Each club's state comes from ``config/mlsnext_kitman_club_states.json``,
settled by ``scripts/prepare_mlsnext_kitman_club_states.py`` or answered by the owner. A club missing
from it gets no new teams: its squads that would be created are held, and a squad that matches an
existing team still links.

A team is filed by its real age even when it plays up, so a squad's team normally holds the squad's
own age. ``config/mlsnext_kitman_play_up_clubs.json`` names the clubs, on the owner's word, whose
squads play a year up: for those, a team one board younger may carry a squad too, and a new squad is
never paired with a team automatically, because pairing by the squad's age picks the next-older team.
"""

import json
import re
from collections.abc import Iterable
from pathlib import Path

from src.models.modular11_ea_keys import season_start_year
from src.utils.placeholder_clubs import is_placeholder_club

__all__ = [
    "CLUB_STATES",
    "PLAY_UP_CLUBS",
    "club_state_or_blank",
    "kitman_key",
    "plays_up",
    "refuse_raw_keys",
    "season_start_year",
    "split_kitman_key",
    "team_ages_for_squad",
]

KEY_RE = re.compile(r"([0-9]{1,9}):(20[0-9]{2})")
AGE_RE = re.compile(r"u([0-9]{1,2})")

CLUB_STATES: dict[str, str] = json.loads(
    (Path(__file__).resolve().parents[2] / "config" / "mlsnext_kitman_club_states.json").read_text(encoding="utf-8")
)
PLAY_UP_CLUBS: dict[str, str] = json.loads(
    (Path(__file__).resolve().parents[2] / "config" / "mlsnext_kitman_play_up_clubs.json").read_text(encoding="utf-8")
)


def kitman_key(squad_id: str | int, season: int) -> str:
    return f"{squad_id}:{season}"


def split_kitman_key(key: str) -> tuple[str, int]:
    match = KEY_RE.fullmatch(key)
    if match is None:
        raise ValueError(f"not a season-keyed Kitman squad id: {key!r}")
    return match.group(1), int(match.group(2))


def refuse_raw_keys(keys: Iterable[str]) -> None:
    """Stops a run that would read ids without a season as unlinked teams and duplicate them."""
    raw = sum(KEY_RE.fullmatch(key) is None for key in keys)
    if raw:
        raise SystemExit(f"ERROR: {raw} mlsnext_kitman ids are not season-keyed (<squad id>:<season>)")


def club_state_or_blank(club_name: str) -> str:
    return "" if is_placeholder_club(club_name) else CLUB_STATES.get(club_name, "")


def plays_up(club_name: str) -> bool:
    return not is_placeholder_club(club_name) and club_name in PLAY_UP_CLUBS


def team_ages_for_squad(squad_age: str, club_name: str) -> tuple[str, ...]:
    """The stored ages a team may hold to carry this squad: the squad's, then one board younger if the club plays up.

    PitchRank keeps no u18 board, so the board below u19 is u17.
    """
    age = (squad_age or "").strip().lower()
    match = AGE_RE.fullmatch(age)
    if match is None or not plays_up(club_name):
        return (age,)
    years = int(match.group(1))
    return (age, f"u{17 if years == 19 else years - 1}")
