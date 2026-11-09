"""The gender a team record or a team row states, read only to withhold a link or a rename.

A provider record attached to a row of the other gender files one squad's games under another
squad, and a row stored under the wrong gender still names its own gender in its team name. So a
row is read from its stored column and both its names, a record from its own name and, where the
provider reports the record's own gender, that field, and any disagreement among them withholds
the link or the rename. None of these readings ever writes a gender.

A team name states a gender (owner, 2026-11-08) when it spells ``Boys`` or ``Girls``, which wins
over any letter, or else when a B or G is attached to an age or a year: ``B2014``, ``U11G``,
``17B``, ``12/13G``, ``BU07``, ``11UG``. A lone ``1B`` or ``5G`` is a squad code, and a name
spelling both genders, or carrying both letters, states neither.

Standard library only: the weekly hygiene jobs that import this install three packages.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional, Tuple

_WORD_B = re.compile(r"(?<![a-z0-9])boys?(?![a-z0-9])", re.I)
_WORD_G = re.compile(r"(?<![a-z0-9])girls?(?![a-z0-9])", re.I)


def _affix(letter: str) -> re.Pattern:
    return re.compile(
        rf"(?<![a-z0-9]){letter}(?=u[0-9]|[0-9]{{2}})"
        rf"|(?:(?<=[0-9]{{2}})|(?<=u[0-9])|(?<=[0-9]u)){letter}(?![a-z0-9])",
        re.I,
    )


_AFFIX_B = _affix("b")
_AFFIX_G = _affix("g")

_STORED = {
    "male": "Male",
    "m": "Male",
    "b": "Male",
    "boy": "Male",
    "boys": "Male",
    "female": "Female",
    "f": "Female",
    "g": "Female",
    "girl": "Female",
    "girls": "Female",
}


def name_gender(name: Optional[str]) -> Optional[str]:
    """``"Male"`` or ``"Female"`` when the name states one, else None."""
    n = name or ""
    boys, girls = bool(_WORD_B.search(n)), bool(_WORD_G.search(n))
    if boys != girls:
        return "Male" if boys else "Female"
    if boys:
        return None
    b, g = bool(_AFFIX_B.search(n)), bool(_AFFIX_G.search(n))
    if b != g:
        return "Male" if b else "Female"
    return None


def stored_gender(value: Optional[str]) -> Optional[str]:
    """A stored or provider gender as ``"Male"``/``"Female"``, or None. Never defaults to Male."""
    return _STORED.get(str(value or "").strip().lower())


def row_genders(row: Mapping[str, Any]) -> Tuple[Optional[str], ...]:
    """A team row's readings: its stored gender, its name and its registered name."""
    return (
        stored_gender(row.get("gender")),
        name_gender(row.get("team_name")),
        name_gender(row.get("team_name_original")),
    )


def gender_verdict(record: Iterable[Optional[str]], row: Iterable[Optional[str]]) -> str:
    """``"unknown"``, ``"mismatch"`` or ``"ok"`` for attaching a record to a row.

    Both sides are readings already passed through ``name_gender`` or ``stored_gender``; a None
    is no reading. Once the record states a gender, any two readings that differ make a mismatch,
    so a record contradicting itself, or a row named for one gender and stored as the other,
    refuses the link too. A row with no reading at all does not block it.
    """
    stated = {g for g in record if g}
    if not stated:
        return "unknown"
    return "ok" if len(stated | {g for g in row if g}) == 1 else "mismatch"
