from io import BytesIO
from itertools import combinations

from openpyxl import load_workbook

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_sheet import CohortSheet, SheetTeam
from src.tournaments.seeding_tiers import TierEntrant, build_cheat_sheet_analysis
from src.tournaments.seeding_workbook import build_seeding_workbook, validate_seeding_workbook


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
    assert sheet.freeze_panes == "A7"
    assert sheet.auto_filter.ref == "A6:K7"
    assert [sheet.cell(6, column).value for column in range(8, 12)] == [
        "Final division", "Pool", "Final seed", "Director notes"
    ]
