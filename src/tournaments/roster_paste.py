"""Parser for a pasted tournament accepted-teams list.

Turns the tab-separated block a director sends — or that an operator copies
off a GotSport "Teams Accepted" page — into ordered rows carrying the cohort
from their section heading.

Two rules the shape of the source forces:

- **The heading is authoritative.** ``BLACK LIONS 14/15 U13B SELECT`` sits in
  a U13 section while its own band reads U12, with nothing marking it as a
  play-up. The cohort token inside a team name is recorded by the resolver as
  a hint and never decides placement here.
- **Markers are split off, not discarded.** A trailing ``-c`` and an embedded
  ``*`` appear on the roster and nowhere in our data; eight of a measured 105
  teams only matched once they were removed. ``*`` reads as playing up on the
  evidence so far, ``-c`` has no established meaning, so both survive as flags
  for later analysis rather than being interpreted now.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["ParsedRoster", "RosterRow", "parse_roster"]

_GENDER_WORDS = {
    "male": "Male",
    "boys": "Male",
    "boy": "Male",
    "female": "Female",
    "girls": "Female",
    "girl": "Female",
}

_HEADING_GENDER = re.compile(r"\b(male|female|boys?|girls?)\b", re.IGNORECASE)
_HEADING_AGE = re.compile(r"\bu\s*([0-9]{1,2})\b", re.IGNORECASE)
_COUNTER_LINE = re.compile(r"^teams accepted\b|\(\s*[0-9]+\s+of\s+[0-9]+\s*\)", re.IGNORECASE)


@dataclass(frozen=True)
class RosterRow:
    """One accepted team, with its cohort resolved from the enclosing heading."""

    source_index: int
    club_raw: str
    team_name_raw: str
    state: str
    section_age_group: str
    section_gender: str
    team_name_stripped: str
    has_star_marker: bool
    has_c_marker: bool


@dataclass(frozen=True)
class ParsedRoster:
    rows: tuple[RosterRow, ...]
    warnings: tuple[str, ...]


def _parse_heading(line: str) -> tuple[str, str] | None:
    gender_match = _HEADING_GENDER.search(line)
    age_match = _HEADING_AGE.search(line)
    if not gender_match or not age_match:
        return None
    return f"u{int(age_match.group(1))}", _GENDER_WORDS[gender_match.group(1).lower()]


def _split_markers(team_name: str) -> tuple[str, bool, bool]:
    has_star = "*" in team_name
    stripped = team_name.replace("*", "").strip()
    has_c = stripped.endswith("-c")
    if has_c:
        stripped = stripped[: -len("-c")].strip()
    return stripped, has_star, has_c


def _is_column_header(cells: list[str]) -> bool:
    return len(cells) >= 2 and cells[0].strip().lower() == "club" and cells[1].strip().lower() == "team"


def parse_roster(text: str) -> ParsedRoster:
    """Parse a pasted accepted-teams block into cohort-tagged rows.

    Rows the parser cannot place — a team line before any heading, or a line
    with no second column — are collected into ``warnings`` and dropped, so a
    ragged paste still yields everything it can.
    """
    rows: list[RosterRow] = []
    warnings: list[str] = []
    age_group = ""
    gender = ""

    for line in text.splitlines():
        if not line.strip():
            continue

        if "\t" not in line:
            heading = _parse_heading(line)
            if heading:
                age_group, gender = heading
            elif not _COUNTER_LINE.search(line.strip()):
                warnings.append(f"Ignored line with no team column: {line.strip()}")
            continue

        cells = line.split("\t")
        if _is_column_header(cells):
            continue

        if not age_group:
            warnings.append(f"Ignored team listed before any cohort heading: {line.strip()}")
            continue

        club_raw = cells[0].strip()
        team_name_raw = cells[1].strip()
        state = cells[2].strip() if len(cells) > 2 else ""
        stripped, has_star, has_c = _split_markers(team_name_raw)
        rows.append(
            RosterRow(
                source_index=len(rows),
                club_raw=club_raw,
                team_name_raw=team_name_raw,
                state=state,
                section_age_group=age_group,
                section_gender=gender,
                team_name_stripped=stripped,
                has_star_marker=has_star,
                has_c_marker=has_c,
            )
        )

    return ParsedRoster(rows=tuple(rows), warnings=tuple(warnings))
