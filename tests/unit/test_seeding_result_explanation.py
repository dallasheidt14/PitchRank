import csv
from dataclasses import replace
from io import BytesIO, StringIO

from openpyxl import load_workbook

from src.tournaments.seeding_content import build_director_cohort, director_csv
from src.tournaments.seeding_result_explanation import explain_results
from src.tournaments.seeding_sheet import CohortSheet, SheetTeam, render_sheet_html
from src.tournaments.seeding_tiers import TierEntrant, build_cheat_sheet_analysis
from src.tournaments.seeding_workbook import build_seeding_workbook


def test_game_examples_include_contrary_results_and_retain_sparse_warning():
    profile = {"games": 2, "distinctOpponents": 2, "latestGameDate": "2026-10-01", "limited": True,
               "componentEntrants": 1, "influentialGames": [
                   {"margin": 2, "residual": 1, "opponent_name": "Alpha", "opponent_club": "Club",
                    "date": "2026-10-01", "fixture": {"goals": 4}},
                   {"margin": -2, "residual": -1, "opponent_name": "Beta", "date": "2026-09-20",
                    "fixture": {"goals": 4}}]}
    reason = explain_results(profile)
    assert "3-1 vs Club Alpha (2026-10-01)" in reason
    assert "1-3 vs Beta (2026-09-20)" in reason
    assert "Limited evidence" in reason and "No shared-result link" in reason
    assert "saved rating" in explain_results({"games": 0})


def test_every_director_export_preserves_reason_compromise_and_coverage():
    analysis = build_cheat_sheet_analysis([TierEntrant("a", "=Alpha", .8)], {})
    reason = "3-1 vs Club (2026-10-01). Limited evidence."
    analysis = replace(analysis, ordering_evidence={"teams": {"a": {"director_reason": reason,
        "cautions": ["8 games lack usable opponent ratings", "Field sensitivity: seeds 1–4"]}}},
        tier_guidance={"status": "review_required_compromise", "cuts": [1],
            "divisions": [{"label": "Tier 1", "start_seed": 1, "end_seed": 1, "size": 1,
                           "pool_sizes": [1], "minimum_games": 0}], "warnings": ["Review worst matchup."]})
    sheet = CohortSheet("u13", "Female", (SheetTeam("=Alpha", "Club", .8, entrant_id="a", requested_flight="Gold", listed_division="League A"),),
                        (SheetTeam("Unplaced", "Club", entrant_id="b"),), tier_analysis=analysis)
    content = build_director_cohort(sheet)
    assert any("8 games lack usable opponent ratings" in note and "Field sensitivity: seeds 1–4" in note
               for note in content.notes)
    assert "Provisional tier break" in content.rows[0].break_label
    assert content.rows[0].recommendation_reason == reason
    rows = list(csv.DictReader(StringIO(director_csv(sheet).decode("utf-8-sig"))))
    assert len(rows) == 2 and rows[0]["Team"] == "'=Alpha"
    assert rows[0]["Coverage"] == "1 of 2 teams assessed"
    assert "Review-required compromise" in rows[0]["Recommendation"]
    assert "Requested: Gold" in rows[0]["Roster context"] and "Listed: League A" in rows[0]["Roster context"]
    assert rows[1]["Seed"] == ""
    assert "8 games lack usable opponent ratings" in rows[0]["Warnings and formats"]
    html = render_sheet_html("Cup", [sheet], generated_on="2026-10-18", ranking_run="2026-10-17")
    assert reason in html and "Unplaced" in html and "Review-required compromise" in html
    assert "8 games lack usable opponent ratings" in html
    assert "Requested: Gold" in html and "Listed: League A" in html
    assert '<th class="num">PowerScore</th>' not in html
    book = load_workbook(BytesIO(build_seeding_workbook("Cup", [sheet], generated_on="2026-10-18",
                                                     ranking_run="2026-10-17")))
    assert any("8 games lack usable opponent ratings" in str(cell.value)
               for row in book.active for cell in row)
    assert "Requested: Gold" in book.active["B7"].value and "Listed: League A" in book.active["B7"].value
    assert reason in book.active["G7"].value
    assert book.active.column_dimensions["D"].hidden
    assert book.active["B8"].value == "Unplaced"
