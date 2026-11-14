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

from src.tournaments.cohort_labels import read_label
from src.utils.us_states import STATE_CODE_TO_NAME

__all__ = ["ParsedRoster", "RosterRow", "parse_roster", "split_roster_markers"]

# A heading names an age and a gender. One whose age is a U-age and whose
# gender is a word may carry one word more ("Girls U9/U10 Mexico", "U14 Boys
# Gold"); any other shape takes none, because "Solar 14G" and "Arsenal 2013
# Girls" are teams entered without their club column, and reading one as a
# heading drops a team from the quote.
_HEADING_EXTRA_WORDS = 1
_HEADING_FILLER = frozenset({"division", "div", "bracket", "group", "flight", "age", "and", "the"})
_U_COHORT = re.compile(r"^u[0-9]{1,2}$")
_COUNTER_LINE = re.compile(r"^teams accepted\b|\(\s*[0-9]+\s+of\s+[0-9]+\s*\)", re.IGNORECASE)
_BRACKET_LINE = re.compile(r"^(?:bracket|pool)\s+[A-Z0-9]+$", re.IGNORECASE)
_STANDINGS_STATS = frozenset({"mp", "gp", "p", "w", "l", "d", "t", "gf", "ga", "gd", "pts", "points"})
_STATE_SUFFIX = re.compile(r"\s*\(([A-Z]{2})\)\s*$")


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


def _parse_heading(line: str) -> tuple[str, str, bool] | None:
    """A heading's ``(age_group, gender, names_several_ages)``, or None for a non-heading.

    A heading replaces both carried fields even when it names more than one of
    either, so the rows below ``Boys/Girls U13`` reach cohort review instead of
    inheriting the section above.
    """
    reading = read_label(line)
    ages = {cohort for cohort in reading.cohorts if _U_COHORT.match(cohort)}
    extra = [
        word for word in reading.leftover
        if not word.isdigit() and word.lower() not in _HEADING_FILLER
    ]
    allowed = _HEADING_EXTRA_WORDS if reading.has_u_age and reading.gender_from_word else 0
    if not (ages and reading.genders) or len(extra) > allowed:
        return None
    return (reading.cohort if reading.cohort in ages else ""), reading.gender, len(reading.cohorts) > 1


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


def _is_standings_header(cells: list[str]) -> bool:
    labels = {cell.strip().lower() for cell in cells}
    return "team" in labels and len(labels & _STANDINGS_STATS) >= 2


def _table_cells(line: str) -> list[str]:
    """Accept spreadsheet tabs and Markdown tables without splitting team spaces."""
    if "\t" in line:
        return line.split("\t")
    if line.strip().startswith("|") and line.strip().endswith("|"):
        return [cell.strip() for cell in line.strip()[1:-1].split("|")]
    return [line]


def _cohort_columns(cells: list[str]) -> dict[str, int]:
    aliases = {"team name": "team", "age": "age group", "sex": "gender"}
    labels = [re.sub(r"\s+", " ", cell.strip().lower().replace("_", " ")) for cell in cells]
    labels = [aliases.get(label, label) for label in labels]
    if "team" not in labels or not ({"age group", "gender"} & set(labels)):
        return {}
    return {label: labels.index(label) for label in labels if label}


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
    standings = False
    standings_team_column = 0
    standings_club_column: int | None = None
    cohort_columns: dict[str, int] = {}
    lines = [line for line in text.splitlines() if line.strip()]

    for position, line in enumerate(lines):
        cells = _table_cells(line)
        if not any(cell.strip() for cell in cells):
            continue
        columns = _cohort_columns(cells)
        if columns:
            cohort_columns = columns
            standings = False
            continue
        if cohort_columns and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells):
            continue
        if _is_standings_header(cells):
            cohort_columns = {}
            standings = True
            labels = [cell.strip().lower() for cell in cells]
            standings_team_column = labels.index("team")
            standings_club_column = labels.index("club") if "club" in labels else None
            continue
        if _is_column_header(cells):
            cohort_columns = {}
            standings = False
            continue
        if _BRACKET_LINE.fullmatch(line.strip()) and (
            standings or (position + 1 < len(lines) and _is_standings_header(lines[position + 1].split("\t")))
        ):
            continue

        # Trailing tabs from a spreadsheet row do not make a heading a data row,
        # but a line that is not a heading keeps every column it was pasted with.
        if len(cells) == 1 or (not cohort_columns and not any(cell.strip() for cell in cells[1:])):
            heading = _parse_heading(line.strip())
            if heading:
                age_group, gender, mixed = heading
                # A mixed section is preserved for an explicit operator decision.
                division = line.strip() if mixed else ""
                standings = False
                cohort_columns = {}
                continue
        row_age, row_gender, row_division = age_group, gender, division
        if cohort_columns:
            def value(column: str) -> str:
                index = cohort_columns.get(column)
                return cells[index].strip() if index is not None and index < len(cells) else ""

            # Explicit row metadata never inherits another team's values or its name.
            issues = []
            if "age group" in cohort_columns:
                age = value("age group")
                reading = read_label(f"U{age}" if age.isascii() and age.isdigit() else age)
                row_age = reading.cohort if _U_COHORT.fullmatch(reading.cohort) else ""
                if not row_age:
                    issues.append("Check this team's age group.")
            if "gender" in cohort_columns:
                gender_value = value("gender")
                row_gender = {"m": "Male", "b": "Male", "f": "Female", "g": "Female"}.get(
                    gender_value.lower(), read_label(gender_value).gender
                )
                if not row_gender:
                    issues.append("Check this team's gender.")
            row_division = ""
            mapped = [value("club"), value("team"), value("state"), value("requested flight")]
            if not mapped[1]:
                issues.append("Team name is missing.")
            cells = mapped
            issue = " ".join(issues)
        elif standings and len(cells) > 1:
            # Standings omit the rank header even when rows carry rank numbers.
            first = cells[0].strip()
            offset = int(standings_team_column == 0 and (not first or (first.isascii() and first.isdigit())))
            name_index = standings_team_column + offset
            club_index = standings_club_column + offset if standings_club_column is not None else None
            club = cells[club_index].strip() if club_index is not None and club_index < len(cells) else ""
            cells = [club, cells[name_index].strip() if name_index < len(cells) else ""]
            issue = "" if cells[1] else "Team name is missing."
        elif len(cells) == 1:
            if _COUNTER_LINE.search(line.strip()):
                continue
            cells = ["", line.strip()]
            issue = "Confirm this line is a team, or exclude it."
        else:
            issue = "" if len(cells) >= 2 and cells[1].strip() else "Team name is missing."

        club_raw = cells[0].strip()
        team_name_raw = cells[1].strip()
        state = cells[2].strip() if len(cells) > 2 else ""
        requested_flight = cells[3].strip() if len(cells) > 3 else ""
        matching_name = team_name_raw
        if standings or cohort_columns:
            suffix = _STATE_SUFFIX.search(matching_name)
            if suffix and suffix[1] in STATE_CODE_TO_NAME:
                if state and state.upper() != suffix[1]:
                    issue = (issue + " Check the conflicting state values.").strip()
                state = state or suffix[1]
                matching_name = matching_name[:suffix.start()].strip()
        stripped, has_star, has_c = split_roster_markers(matching_name)
        rows.append(
            RosterRow(
                source_index=len(rows),
                club_raw=club_raw,
                team_name_raw=team_name_raw,
                state=state,
                section_age_group=row_age,
                section_gender=row_gender,
                team_name_stripped=stripped,
                has_star_marker=has_star,
                has_c_marker=has_c,
                requested_flight=requested_flight,
                listed_division=row_division,
                intake_issue=issue,
            )
        )

    return ParsedRoster(rows=tuple(rows), warnings=tuple(warnings))
