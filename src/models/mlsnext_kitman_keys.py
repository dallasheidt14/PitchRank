"""MLS NEXT Kitman season keys and the club -> state table.

A Kitman squad id names one club at one age in one division. Whether it survives into next
season is unknown, so PitchRank stores `<squad id>:<season>` and a link is only true for the
season that wrote it.

Kitman gives no state. Each club's state comes from ``config/mlsnext_kitman_club_states.json``,
settled by ``scripts/prepare_mlsnext_kitman_club_states.py`` or answered by the owner. A club missing
from it gets no new teams: its squads that would be created are held, and a squad that matches an
existing team still links.
"""

import json
import re
from collections.abc import Iterable
from pathlib import Path

from src.models.modular11_ea_keys import season_start_year
from src.utils.placeholder_clubs import is_placeholder_club

__all__ = [
    "CLUB_STATES",
    "club_state_or_blank",
    "kitman_key",
    "refuse_raw_keys",
    "season_start_year",
    "split_kitman_key",
]

KEY_RE = re.compile(r"([0-9]{1,9}):(20[0-9]{2})")

CLUB_STATES: dict[str, str] = json.loads(
    (Path(__file__).resolve().parents[2] / "config" / "mlsnext_kitman_club_states.json").read_text(encoding="utf-8")
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
