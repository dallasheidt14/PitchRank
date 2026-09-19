from io import BytesIO
from itertools import combinations

from openpyxl import load_workbook
import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_sheet import CohortSheet, SheetTeam
from src.tournaments.seeding_tiers import TierEntrant, build_cheat_sheet_analysis
from src.tournaments.seeding_workbook import build_seeding_workbook, validate_seeding_workbook, workbook_sheet_titles


def _prediction(margin: float, blowout: float = 0.1) -> ComparePrediction:
    return ComparePrediction("team_a", 0.6, 0.3, 0.1, {"teamA": 3, "teamB": 1}, margin, abs(margin), blowout)


def test_cheat_sheet_requires_all_available_windows_for_a_break():
    ids = ["a", "b", "c", "d", "e", "f", "g", "h"]
    entrants = [TierEntrant(value, value, 1 - index * 0.05) for index, value in enumerate(ids)]
    predictions = {
        (first, second): _prediction(3 if ids.index(first) < 4 <= ids.index(second) else 0.1, 0.6)
        for first, second in combinations(ids, 2)
    }
    analysis = build_cheat_sheet_analysis(entrants, predictions)
    assert [item.after_seed for item in analysis.breaks] == [3]
    assert analysis.breaks[0].supported_windows == (3, 4, 5)
    assert all("division" not in note.lower() or "not" in note.lower() for note in analysis.notes)


def test_workbook_has_editable_director_columns_and_literal_names():
    cohort = CohortSheet(
        "u10", "Male",
        (SheetTeam("=Formula-like name", "Club", 0.82, 2, entrant_id="1"),),
        (),
    )
    payload = build_seeding_workbook("Event", [cohort], generated_on="2026-09-18", ranking_run="2026-09-17")
    validate_seeding_workbook(payload, ["U10 Boys"])
    workbook = load_workbook(BytesIO(payload), data_only=False)
    sheet = workbook["U10 Boys"]
    assert sheet["B7"].value == "=Formula-like name"
    assert sheet["B7"].data_type == "s"
    assert sheet.freeze_panes == "D7"
    assert sheet.auto_filter.ref == "A6:K7"
    assert [sheet.cell(6, column).value for column in range(8, 12)] == [
        "Final division", "Pool", "Final seed", "Director notes"
    ]


@pytest.mark.parametrize("event_name", ["=1+1", "+Event", "-Event", "@Event"])
def test_event_title_is_literal_text_after_reopening(event_name):
    cohort = CohortSheet("u10", "Male", (SheetTeam("Team", "Club", .8, entrant_id="0"),), ())
    payload = build_seeding_workbook(event_name, [cohort], generated_on="2026-09-19", ranking_run="2026-09-19")
    workbook = load_workbook(BytesIO(payload), data_only=False)
    assert workbook.active["A1"].value == event_name
    assert workbook.active["A1"].data_type == "s"
    assert load_workbook(BytesIO(payload), data_only=True).active["A1"].value == event_name


def test_unassigned_gender_cohort_stays_distinct_from_girls():
    sheets = [CohortSheet("u10", gender, (), (SheetTeam(name, "Club", entrant_id=str(index)),))
              for index, (gender, name) in enumerate((("Female", "Girls team"), ("", "Review team")))]
    payload = build_seeding_workbook("Draft Cup", sheets, generated_on="2026-09-19", ranking_run="unknown")
    validate_seeding_workbook(payload, workbook_sheet_titles(sheets))
    workbook = load_workbook(BytesIO(payload))
    assert workbook.sheetnames == ["U10 Girls", "U10 Unspecified gender"]
    assert workbook.worksheets[1]["A2"].value == "U10 Unspecified gender · 1 accepted teams"
    assert workbook.worksheets[1]["B7"].value == "Review team"


def test_cohort_notes_match_pdf_and_stay_outside_sortable_team_rows():
    from src.tournaments.seeding_sheet import render_sheet_html

    entrants = [TierEntrant(str(index), f"Team {index}", .8) for index in range(3)]
    analysis = build_cheat_sheet_analysis(
        entrants, {(a.entrant_id, b.entrant_id): _prediction(.1) for a, b in combinations(entrants, 2)},
    )
    cohort = CohortSheet("u10", "Female", tuple(
        SheetTeam(item.team_name, "Club", .8, entrant_id=item.entrant_id) for item in entrants
    ), (), analysis)
    notes = {("u10", "Female"): "=Director note\nKeep these words intact."}
    payload = build_seeding_workbook("Event", [cohort], generated_on="2026-09-19",
                                     ranking_run="2026-09-19", operator_notes=notes)
    validate_seeding_workbook(payload, ["U10 Girls"])
    sheet = load_workbook(BytesIO(payload)).active
    document = render_sheet_html("Event", [cohort], generated_on="2026-09-19",
                                 ranking_run="2026-09-19", operator_notes=notes)
    for note in (*analysis.notes, notes[("u10", "Female")]):
        cell = next(cell for row in sheet for cell in row if cell.value == note)
        assert cell.data_type == "s"
        assert note in document
        assert cell.row > 9
        assert str(sheet.max_row) in str(sheet.print_area)
    assert sheet.auto_filter.ref == "A6:K9"
    assert "Seeded: 3" in sheet["A5"].value
    assert all(sheet.cell(row, 11).value is None for row in range(7, 10))
