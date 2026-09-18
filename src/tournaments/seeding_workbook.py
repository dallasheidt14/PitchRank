"""Offline Excel companion for the MatchBalance director cheat sheets."""

from __future__ import annotations

from io import BytesIO
from typing import Sequence

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from src.tournaments.seeding_sheet import CohortSheet, SheetTeam

FOREST = "0B5345"
FOREST_DEEP = "083E33"
YELLOW = "F4D03F"
MUTED = "5B6B66"
RULE = "D8E0DD"
BAND = "F4F7F6"


def _sheet_title(sheet: CohortSheet) -> str:
    label = f"{sheet.age_group.upper()} {'Boys' if sheet.gender == 'Male' else 'Girls'}"
    return label[:31]


def _safe_text(value: str | None) -> str:
    """Keep imported names as literal text, including formula-like names."""
    return "" if value is None else str(value)


def _set_text(cell, value: str) -> None:
    cell.value = value
    if value[:1] in {"=", "+", "-", "@"}:
        cell.data_type = "s"
        cell._value = value


def _teams_for_sheet(sheet: CohortSheet) -> list[tuple[int | None, SheetTeam, str, str]]:
    analysis = sheet.tier_analysis
    all_teams = {team.entrant_id: team for team in (*sheet.rated, *sheet.unrated)}
    if analysis is None:
        ordered_ids = [team.entrant_id for team in sheet.rated]
        statuses = {}
        markers = {}
    else:
        ordered_ids = list(analysis.ordered_ids)
        if hasattr(analysis, "marker_for_seed"):
            statuses = getattr(analysis, "placement_status", {})
            markers = {entrant_id: analysis.marker_for_seed(seed) for seed, entrant_id in enumerate(ordered_ids, 1)}
        else:
            statuses = {entrant_id: "Seeded" for entrant_id in ordered_ids}
            statuses.update({entrant_id: "Data review required" for entrant_id in analysis.review})
            markers = {}
    rows: list[tuple[int | None, SheetTeam, str, str]] = []
    for seed, entrant_id in enumerate(ordered_ids, 1):
        team = all_teams.get(entrant_id)
        if team is not None:
            rows.append((seed, team, markers.get(entrant_id, ""), statuses.get(entrant_id, "Seeded")))
    unseeded = (team for key, team in all_teams.items() if key not in set(ordered_ids))
    for team in sorted(unseeded, key=lambda value: value.team_name.casefold()):
        status = statuses.get(team.entrant_id) or team.review_reason or "Placement status needs review."
        rows.append((None, team, "", status))
    return rows


def build_seeding_workbook(
    event_name: str, sheets: Sequence[CohortSheet], *, generated_on: str, ranking_run: str,
) -> bytes:
    """Create one filterable, editable worksheet per selected cohort."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    used_titles: set[str] = set()
    for cohort in sheets:
        title = _sheet_title(cohort)
        base = title
        suffix = 2
        while title in used_titles:
            title = f"{base[:28]} {suffix}"
            suffix += 1
        used_titles.add(title)
        sheet = workbook.create_sheet(title)
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A7"
        sheet.merge_cells("A1:K1")
        sheet["A1"] = _safe_text(event_name)
        sheet["A1"].font = Font(name="Arial", size=18, bold=True, color="FFFFFF")
        sheet["A1"].fill = PatternFill("solid", fgColor=FOREST)
        sheet["A1"].alignment = Alignment(vertical="center")
        sheet.row_dimensions[1].height = 28
        sheet.merge_cells("A2:K2")
        cohort_label = "Boys" if cohort.gender == "Male" else "Girls"
        team_count = len(cohort.rated) + len(cohort.unrated)
        sheet["A2"] = f"{cohort.age_group.upper()} {cohort_label} · {team_count} accepted teams"
        sheet["A2"].font = Font(bold=True, color=FOREST_DEEP)
        sheet.merge_cells("A3:K3")
        sheet["A3"] = "Strength breaks describe competitive differences; they do not assign divisions or pools."
        sheet["A3"].font = Font(italic=True, color=MUTED)
        sheet.merge_cells("A4:K4")
        sheet["A4"] = f"Ratings as of {ranking_run} · Generated {generated_on}"
        sheet["A4"].font = Font(color=MUTED, size=9)
        headers = [
            "Suggested seed", "Team name", "Club", "PitchRank score", "State rank", "Strength marker",
            "Placement status", "Final division", "Pool", "Final seed", "Director notes",
        ]
        for column, value in enumerate(headers, 1):
            cell = sheet.cell(6, column, value)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=FOREST_DEEP)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = Border(bottom=Side(style="thin", color=YELLOW))
        for row_index, (seed, team, marker, status) in enumerate(_teams_for_sheet(cohort), 7):
            values = [
                seed, _safe_text(team.team_name), _safe_text(team.club_name),
                (team.power_score * 100 if team.power_score is not None else None),
                (
                    f"{team.state} #{team.state_rank}"
                    if team.state_rank is not None and team.state
                    else team.state_rank if team.state_rank is not None else ""
                ),
                _safe_text(marker), _safe_text(status), "", "", "", "",
            ]
            for column, value in enumerate(values, 1):
                cell = sheet.cell(row_index, column, value)
                if isinstance(value, str):
                    _set_text(cell, value)
                cell.alignment = Alignment(vertical="top", wrap_text=column in {2, 3, 6, 7, 8, 9, 11})
                cell.border = Border(bottom=Side(style="hair", color=RULE))
                if column in {8, 9, 10, 11}:
                    cell.fill = PatternFill("solid", fgColor="FFF9DB")
                if column == 4 and value is not None:
                    cell.number_format = "0.0"
                if column in {1, 4, 5, 10}:
                    cell.alignment = Alignment(horizontal="center", vertical="top")
            if row_index % 2 == 0:
                for column in range(1, 8):
                    sheet.cell(row_index, column).fill = PatternFill("solid", fgColor=BAND)
        end_row = max(6, 6 + len(_teams_for_sheet(cohort)))
        if end_row >= 7:
            table = Table(displayName=f"Cohort{len(used_titles)}", ref=f"A6:K{end_row}")
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium4",
                showFirstColumn=False,
                showLastColumn=False,
                showRowStripes=False,
                showColumnStripes=False,
            )
            sheet.add_table(table)
            sheet.auto_filter.ref = f"A6:K{end_row}"
        widths = [14, 32, 24, 15, 15, 20, 24, 18, 12, 14, 32]
        for column, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(column)].width = width
        sheet.print_title_rows = "1:6"
        sheet.print_area = f"A1:K{end_row}"
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_margins.left = 0.25
        sheet.page_margins.right = 0.25
        sheet.page_margins.top = 0.5
        sheet.page_margins.bottom = 0.5
        sheet.oddFooter.center.text = "MatchBalance by PitchRank"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def validate_seeding_workbook(payload: bytes, expected_sheets: Sequence[str]) -> None:
    """Lightweight saved-file check used by tests and the Streamlit export."""
    workbook = load_workbook(BytesIO(payload), read_only=False, data_only=False)
    if list(workbook.sheetnames) != list(expected_sheets):
        raise ValueError("Generated workbook sheets do not match the selected cohorts.")
    for sheet in workbook.worksheets:
        if sheet.freeze_panes != "A7" or sheet.auto_filter.ref != f"A6:K{sheet.max_row}":
            raise ValueError(f"Workbook layout is incomplete for {sheet.title}.")
