"""Director claims must be narrower than internal matchup-limit diagnostics."""

from dataclasses import replace
from io import BytesIO
from itertools import combinations

import pytest
from openpyxl import load_workbook

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_content import build_director_cohort, export_fingerprint
from src.tournaments.seeding_sheet import CohortSheet, SheetTeam, render_sheet_html
from src.tournaments.seeding_tiers import TierEntrant, build_cheat_sheet_analysis
from src.tournaments.seeding_workbook import build_seeding_workbook


def prediction(margin, risk=.1):
    return ComparePrediction("team_a", .6, .3, .1, {"teamA": 2, "teamB": 1}, margin, 1.5, risk, "low", .4)


def cohort(count, *, gap=None, bottom=False):
    entrants = [TierEntrant(str(i), f"Team {i}", .9 - i * .01) for i in range(count)]
    if gap:
        boundary = count - gap if bottom else gap
        entrants = [replace(e, power_score=e.power_score - (.3 if i >= boundary else 0))
                    for i, e in enumerate(entrants)]
    pairs = {(a.entrant_id, b.entrant_id): prediction(
        3 if gap and int(a.entrant_id) < boundary <= int(b.entrant_id) else .1,
        .5 if gap and int(a.entrant_id) < boundary <= int(b.entrant_id) else .1,
    ) for a, b in combinations(entrants, 2)}
    analysis = build_cheat_sheet_analysis(entrants, pairs)
    sheet = CohortSheet("u14", "Male", tuple(
        SheetTeam(e.team_name, "Club", e.power_score, entrant_id=e.entrant_id) for e in entrants
    ), (), analysis)
    return sheet, entrants, pairs


@pytest.mark.parametrize("count", [0, 1, 2, *range(3, 17), 32])
def test_counts_preserved_without_equivalence_or_format_claims(count):
    sheet, _, _ = cohort(count)
    content = build_director_cohort(sheet)
    assert len(content.rows) == count
    assert [row.seed for row in content.rows] == list(range(1, count + 1))
    assert len({row.team.entrant_id for row in content.rows}) == count
    assert content.notes == ()
    assert all(row.observation == "" for row in content.rows)
    assert all(sheet.tier_analysis.marker_for_seed(seed) == "" for seed in range(1, count + 1))
    document = render_sheet_html("Event", [sheet], generated_on="2026-09-20", ranking_run="2026-09-19")
    assert "Close range" not in document and "balanced across pools" not in document
    assert "singleton" not in document and "one team;" not in document
    assert "advancement" not in document and "games guaranteed" not in document
    workbook = load_workbook(BytesIO(build_seeding_workbook(
        "Event", [sheet], generated_on="2026-09-20", ranking_run="2026-09-19",
    )))
    tab = workbook.active
    for index, row in enumerate(content.rows, 7):
        assert tab.cell(index, 1).value == row.seed
        assert tab.cell(index, 2).value == row.team.team_name
        assert tab.cell(index, 4).value == pytest.approx(row.score)
        assert tab.cell(index, 6).value is None
    assert "Director notes" not in [tab.cell(i, 1).value for i in range(7, tab.max_row + 1)]


def test_overlapping_ranges_never_label_seed_one_and_thirteen_as_equivalent():
    sheet, _, _ = cohort(15)
    ranges = sheet.tier_analysis.close_ranges
    assert any(a.start_seed < b.start_seed <= a.end_seed < b.end_seed
               for a, b in combinations(ranges, 2))
    content = build_director_cohort(sheet)
    assert content.rows[0].seed == 1 and content.rows[12].seed == 13
    assert content.rows[0].score > content.rows[12].score
    assert content.rows[0].observation == content.rows[12].observation == ""
    assert content.notes == ()


def test_close_neighbors_do_not_hide_unsafe_endpoints_in_internal_evidence():
    _, entrants, pairs = cohort(3)
    pairs[("0", "2")] = prediction(2.5)
    analysis = build_cheat_sheet_analysis(entrants, pairs)
    assert [(r.start_seed, r.end_seed) for r in analysis.close_ranges] == [(1, 2), (2, 3)]


@pytest.mark.parametrize("gap,bottom,expected", [
    (1, False, "Seed 1 stands apart competitively above the remaining teams."),
    (2, False, "Seeds 1–2 stand apart competitively above the remaining teams."),
    (1, True, "Seed 8 stands apart competitively below the remaining teams."),
    (2, True, "Seeds 7–8 stand apart competitively below the remaining teams."),
])
def test_standouts_name_the_entire_end_segment(gap, bottom, expected):
    sheet, _, _ = cohort(8, gap=gap, bottom=bottom)
    analysis = sheet.tier_analysis
    assert analysis.notes == (expected,)
    assert analysis.breaks == ()
    assert len(analysis.standouts) == 1
    standout = analysis.standouts[0]
    assert standout.standout_end_seed - standout.standout_start_seed + 1 == gap


def test_all_window_sizes_must_agree_and_rejected_evidence_survives():
    _, entrants, pairs = cohort(8, gap=4)
    pairs[("3", "4")] = prediction(.1)
    pairs[("3", "5")] = prediction(.1)
    analysis = build_cheat_sheet_analysis(entrants, pairs)
    evidence = {w.size: w for w in analysis.boundary_windows if w.after_seed == 4}
    assert set(evidence) == {3, 4, 5}
    assert not evidence[3].supported
    assert evidence[4].supported and evidence[5].supported
    assert evidence[3].upper_ids == ("3",) and evidence[3].lower_ids == ("4", "5")
    assert evidence[3].over_limit_fraction == 0
    assert 4 not in [b.after_seed for b in analysis.breaks]


def test_clear_gap_has_one_specific_observation_across_pdf_and_excel():
    sheet, _, _ = cohort(8, gap=4)
    content = build_director_cohort(sheet, "=Keep this literal.")
    assert content.rows[3].observation == "Strength gap between seeds 4 and 5."
    assert content.rows[3].strength_break_after
    assert not content.rows[4].strength_break_after
    assert content.notes == ("Strength gap between seeds 4 and 5.", "=Keep this literal.")
    args = dict(generated_on="2026-09-20", ranking_run="2026-09-19",
                operator_notes={("u14", "Male"): "=Keep this literal."})
    document = render_sheet_html("=Event", [sheet], **args)
    tab = load_workbook(BytesIO(build_seeding_workbook("=Event", [sheet], **args))).active
    assert 'data-entrant="3" class="strength-break"' in document
    assert tab.cell(10, 6).value == content.rows[3].observation
    assert tab.cell(10, 1).border.bottom.style == "medium"
    assert tab["A1"].data_type == "s"
    for note in content.notes:
        cell = next(cell for row in tab for cell in row if cell.value == note)
        assert cell.data_type == "s" and note in document


def test_fingerprint_includes_notes_policy_and_content_not_only_prediction_date():
    sheet, _, _ = cohort(6)
    args = dict(generated_on="2026-09-20", ranking_run="2026-09-19", operator_notes={},
                analysis_version=2, policy={"max_expected_margin": 2.0})
    original = export_fingerprint("Event", [sheet], **args)
    assert export_fingerprint("Event", [sheet], **args) == original
    for changed in [dict(operator_notes={("u14", "Male"): "New note"}),
                    dict(policy={"max_expected_margin": 1.5}), dict(analysis_version=3),
                    dict(ranking_run="2026-09-20")]:
        assert export_fingerprint("Event", [sheet], **{**args, **changed}) != original
    assert export_fingerprint("Event · DRAFT", [sheet], **args) != original


def test_many_supported_gaps_show_at_most_three_observations():
    _, entrants, _ = cohort(24)
    entrants = [replace(e, power_score=.95 - (i // 4) * .12 - (i % 4) * .001)
                for i, e in enumerate(entrants)]
    pairs = {(a.entrant_id, b.entrant_id): prediction(
        3 if int(a.entrant_id) // 4 < int(b.entrant_id) // 4 else .1,
        .5 if int(a.entrant_id) // 4 < int(b.entrant_id) // 4 else .1,
    ) for a, b in combinations(entrants, 2)}
    analysis = build_cheat_sheet_analysis(entrants, pairs)
    assert len(analysis.breaks) == len(analysis.notes) == 3
    assert len({window.after_seed for window in analysis.boundary_windows if window.supported}) > 3


def test_workbook_keeps_secondary_identity_and_roster_context_on_team_row():
    team = SheetTeam("=Registered name", "Club", .7, entrant_id="0",
                     pitchrank_team_name="=Database name", plays_up=True,
                     play_up_from_age_group="u13", requested_flight="Gold", listed_division="Boys U14")
    sheet = CohortSheet("u14", "Male", (team,), ())
    content = build_director_cohort(sheet)
    args = dict(generated_on="2026-09-20", ranking_run="2026-09-19")
    document = render_sheet_html("Event", [sheet], **args)
    tab = load_workbook(BytesIO(build_seeding_workbook("Event", [sheet], **args))).active
    assert tab["B7"].value.splitlines() == list(content.rows[0].name_lines)
    assert tab["B7"].data_type == "s"
    assert tab["D7"].value == 70
    assert all(text in document for text in content.rows[0].name_lines)
    assert tab.row_dimensions[7].height >= 75
    assert tab.auto_filter.ref == "A6:K7"
