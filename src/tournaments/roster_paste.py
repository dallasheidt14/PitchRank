"""Parser for a pasted tournament accepted-teams list.

Turns the tab-separated block a director sends — or that an operator copies
off a GotSport "Teams Accepted" page — into ordered rows. Unambiguous headings
supply cohorts; other entries remain available for review.

Two rules the shape of the source forces:

- **The heading is authoritative.** ``BLACK LIONS 14/15 U13B SELECT`` sits in
  a U13 section while its own band reads U12, with nothing marking it as a
  play-up. The cohort token inside a team name is recorded by the resolver as
  a hint and never decides placement here.
- **Markers are split off, not discarded.** A trailing ``-c`` and a trailing
  ``*`` (immediately before ``-c`` when both occur) appear on the roster and
  nowhere in our data; eight of a measured 105 teams only matched once they
  were removed. ``*`` reads as playing up on the evidence so far, ``-c`` has no
  established meaning, so both survive as flags for later analysis rather than
  being interpreted now. An asterisk inside a name remains part of the name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.tournaments.seeding_optimizer import normalize_age_group

__all__ = ["ParsedRoster", "RosterRow", "parse_roster", "split_roster_markers"]

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
    """One roster entry; blank cohort fields and intake issues require review."""

    source_index: int
    club_raw: str
    team_name_raw: str
    state: str
    section_age_group: str
    section_gender: str
    team_name_stripped: str
    has_star_marker: bool
    has_c_marker: bool
    requested_flight: str = ""
    """Optional flight requested in a pasted roster's fourth column."""
    listed_division: str = ""
    """Neutral event-published division label; it does not imply a request."""
    registration_id: str = ""
    provider_team_id: str = ""
    intake_issue: str = ""

    @property
    def registered_name(self) -> str:
        """Tournament-facing name with only the separate play-up marker removed."""
        if self.has_star_marker:
            suffix = "-c" if self.has_c_marker else ""
            return f"{self.team_name_stripped}{suffix}".strip()
        return self.team_name_raw.strip() or self.team_name_stripped


@dataclass(frozen=True)
class ParsedRoster:
    rows: tuple[RosterRow, ...]
    warnings: tuple[str, ...]


def _parse_heading(line: str) -> tuple[str, str] | None:
    gender_match = _HEADING_GENDER.search(line)
    ages = _HEADING_AGE.findall(line)
    if not gender_match or not ages:
        return None
    # A mixed section is preserved for an explicit operator decision.
    single = len(set(ages)) == 1 and not re.search(r"[/–-]\s*(?:u\s*)?[0-9]", line, re.I)
    age = normalize_age_group(ages[0]) if single else ""
    return age, _GENDER_WORDS[gender_match.group(1).lower()]


def split_roster_markers(team_name: str) -> tuple[str, bool, bool]:
    """Remove only the supported trailing roster markers used for matching."""
    stripped = team_name.strip()
    has_c = stripped.endswith("-c")
    if has_c:
        stripped = stripped[: -len("-c")].strip()
    has_star = stripped.endswith("*")
    if has_star:
        stripped = stripped[:-1].strip()
    return stripped, has_star, has_c


def _is_column_header(cells: list[str]) -> bool:
    return len(cells) >= 2 and cells[0].strip().lower() == "club" and cells[1].strip().lower() == "team"


def parse_roster(text: str) -> ParsedRoster:
    """Parse a pasted accepted-teams block, preserving uncertain entries.

    Questionable lines remain reviewable entries. They cannot silently shrink a
    quote, and no cohort is inferred from a team name.
    """
    rows: list[RosterRow] = []
    warnings: list[str] = []
    age_group = ""
    gender = ""
    division = ""

    for line in text.splitlines():
        if not line.strip():
            continue

        if "\t" not in line:
            heading = _parse_heading(line)
            if heading:
                age_group, gender = heading
                division = line.strip() if not age_group else ""
                continue
            if _COUNTER_LINE.search(line.strip()):
                continue
            cells = ["", line.strip()]
            issue = "Confirm this line is a team, or exclude it."
        else:
            cells = line.split("\t")
            issue = "" if len(cells) >= 2 and cells[1].strip() else "Team name is missing."

        if _is_column_header(cells):
            continue

        club_raw = cells[0].strip()
        team_name_raw = cells[1].strip()
        state = cells[2].strip() if len(cells) > 2 else ""
        requested_flight = cells[3].strip() if len(cells) > 3 else ""
        stripped, has_star, has_c = split_roster_markers(team_name_raw)
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
                requested_flight=requested_flight,
                listed_division=division,
                intake_issue=issue,
            )
        )

    return ParsedRoster(rows=tuple(rows), warnings=tuple(warnings))
