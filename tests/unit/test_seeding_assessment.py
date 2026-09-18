import csv
import io
from dataclasses import replace

import pytest

from src.tournaments.roster_paste import ParsedRoster, parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_assessment import (
    assess_roster, carry_decisions, corrected_identities, effective_roster, event_price, source_fingerprint,
    could_belong,
)
from src.tournaments.seeding_intake_ui import team_csv
from src.tournaments.seeding_run_store import SeedingRun, load_run, save_run


@pytest.mark.parametrize("count, expected", [
    (0, "—"), (1, "$199"), (75, "$199"), (76, "$399"), (150, "$399"), (151, "$699"),
    (300, "$699"), (301, "$1,199"), (450, "$1,199"), (451, "$1,499"), (600, "$1,499"), (601, "Custom quote"),
])
def test_published_price_boundaries(count, expected):
    assert event_price(count) == expected


def test_quote_counts_unmatched_and_excludes_younger_for_both_sources():
    parsed = parse_roster("Boys U9\nC\tYoung\nBoys U10\nC\tA\nC\tB\nGirls U19\nC\tC")
    resolved = tuple(ResolvedTeam(row.source_index, "unresolved") for row in parsed.rows)
    assessment = assess_roster(parsed, resolved, {}, coverage="complete")
    assert assessment.total == 3 and assessment.excluded == 1
    assert assessment.manual == {1, 2, 3}
    assert assessment.price == "$199" and not assessment.provisional
    matched = tuple(replace(item, status="gotsport_id", team_id_master=str(item.source_index)) for item in resolved)
    assert assess_roster(parsed, matched, {}, coverage="complete").price == "$199"


def test_failed_matching_is_pending_and_attention_does_not_double_count():
    parsed = parse_roster("C\tUnassigned\nBoys U10\nC\tA\nC\tB")
    resolved = (ResolvedTeam(0, "unresolved"), ResolvedTeam(1, "unresolved"), ResolvedTeam(2, "unresolved"))
    assessment = assess_roster(parsed, resolved, {}, coverage="complete", completed=[0, 1])
    assert assessment.manual == {0, 1}
    assert assessment.pending == {2}
    assert assessment.cohort_review == {0}
    assert assessment.attention == {0, 1, 2}
    assert (assessment.total, assessment.possible_total) == (2, 3)
    assert assessment.provisional


def test_mixed_division_does_not_inherit_database_age_or_block_unrelated_cohort():
    parsed = parse_roster("Girls U9/U10 Mexico\nC\tMixed\nGirls U11\nC\tOlder\nBoys U10\nC\tBoys")
    resolved = tuple(ResolvedTeam(row.source_index, "gotsport_id", team_id_master=str(row.source_index)) for row in parsed.rows)
    assessment = assess_roster(parsed, resolved, {}, coverage="complete")
    assert parsed.rows[0].section_age_group == ""
    assert assessment.cohort_review == {0}
    assert len([cohort for cohort in assessment.cohorts if cohort["Status"] == "Ready"]) == 2
    assigned = effective_roster(parsed, {0: {"section_age_group": "u9"}})
    final = assess_roster(assigned, resolved, {}, coverage="complete")
    assert final.total == 2 and not final.provisional


@pytest.mark.parametrize("coverage", ["unknown", "partial"])
def test_partial_or_legacy_sample_never_claims_ready(coverage):
    parsed = parse_roster("Boys U10\nC\tA")
    result = assess_roster(parsed, [ResolvedTeam(0, "gotsport_id", team_id_master="a")], {}, coverage=coverage)
    assert result.provisional and result.cohorts[0]["Status"] == "Check coverage"


def test_malformed_paste_remains_reviewable_and_is_not_a_confirmed_quote_team():
    parsed = parse_roster("Boys U10\nC\tA\nunrecognized line\nC\t\tAZ")
    result = assess_roster(parsed, (), {}, coverage="complete", completed=[])
    assert len(parsed.rows) == 3
    assert result.total == 1 and result.possible_total == 3
    assert result.cohort_review == {1, 2}
    corrected = effective_roster(parsed, {1: {"exclude": True}, 2: {
        "team_name_raw": "B", "team_name_stripped": "B", "intake_issue": ""}})
    assert assess_roster(corrected, (), {}, coverage="complete").total == 2
    assert len(parsed.rows) == 3


def test_refresh_carries_only_unique_unchanged_registrations_not_indices():
    rows = parse_roster("Boys U10\nC\tA\nC\tB\nC\tWithdrawn").rows
    old = tuple(replace(row, registration_id=f"r{row.source_index}") for row in rows)
    new = (replace(old[1], source_index=0), replace(old[0], source_index=1),
           replace(old[2], source_index=2, registration_id="new", team_name_raw="New"))
    overrides, decisions = carry_decisions(old, new, {0: {"team_id_master": "a"}, 2: {"team_id_master": "c"}},
                                          {1: {"section_age_group": "u11"}})
    assert overrides == {1: {"team_id_master": "a"}}
    assert decisions == {0: {"section_age_group": "u11"}}
    changed = (replace(old[0], team_name_raw="Changed identity"),)
    assert carry_decisions(old, changed, {0: {"team_id_master": "a"}}, {}) == ({}, {})
    assert carry_decisions(old, (old[0], replace(old[0], source_index=9)), {0: {"team_id_master": "a"}}, {}) == ({}, {})


def test_progress_and_decisions_round_trip_and_prior_snapshot_survives(tmp_path):
    parsed = parse_roster("Boys U10\nC\tA\nC\tB")
    run = SeedingRun("Quote Test", parsed.rows, (ResolvedTeam(0, "unresolved"), ResolvedTeam(1, "unresolved")),
                     assessment={"coverage": "partial", "completed": [0], "event_id": "123"},
                     cohort_decisions={1: {"section_age_group": "u11"}})
    save_run(run, base_dir=tmp_path)
    loaded = load_run("quote-test", base_dir=tmp_path)
    assert loaded.assessment == run.assessment and loaded.cohort_decisions == run.cohort_decisions
    save_run(replace(run, rows=run.rows[:1]), base_dir=tmp_path)
    history = list((tmp_path / "quote-test/history").glob("*.json"))
    assert len(history) == 1 and '"B"' in history[0].read_text()


def test_csv_keeps_all_selected_teams_and_defangs_formulas():
    parsed = parse_roster("Boys U10\nC\t=HYPERLINK(\"bad\")\nC\tUnmatched")
    data = team_csv(parsed.rows, (ResolvedTeam(0, "gotsport_id", team_id_master="a", matched_name="DB name"),), {})
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert len(rows) == 2 and rows[1]["Submitted team name"] == "Unmatched"
    assert rows[0]["PitchRank team name"] == "DB name"
    assert rows[0]["Submitted team name"].startswith("'=HYPERLINK")


def test_source_binding_includes_cohort_club_and_registration_identity():
    first = parse_roster("Boys U10\nClub A\tUnited").rows
    second = parse_roster("Girls U15\nClub B\tUnited").rows
    assert source_fingerprint(first) != source_fingerprint(second)
    assert source_fingerprint(first) != source_fingerprint((replace(first[0], registration_id="another"),))
    assert source_fingerprint(first) != source_fingerprint((replace(first[0], provider_team_id="another"),))


def test_name_correction_invalidates_auto_and_manual_identity():
    before = parse_roster("Boys U10\nC\tTeam A")
    after = effective_roster(before, {0: {"team_name_raw": "Team B", "team_name_stripped": "Team B"}})
    for method in ("exact_name", "gotsport_id"):
        resolved, manual, reset = corrected_identities(before, after,
            [ResolvedTeam(0, method, team_id_master="old-id", provider_team_id="123")], {0: {"team_id_master": "old-id"}})
        assert resolved == (ResolvedTeam(0, "unresolved"),)
        assert manual == {} and reset == {0}


def test_cohort_edit_invalidates_only_cohort_based_identity():
    before = parse_roster("Boys U10\nC\tTeam A")
    after = effective_roster(before, {0: {"section_age_group": "u11"}})
    exact = ResolvedTeam(0, "exact_name", team_id_master="old-id")
    assert corrected_identities(before, after, [exact], {})[0] == (ResolvedTeam(0, "unresolved"),)
    direct = replace(exact, status="gotsport_id", provider_team_id="123")
    assert corrected_identities(before, after, [direct], {})[0] == (direct,)


@pytest.mark.parametrize("label", ["Girls U9-U10 Mexico", "Girls U9–U10 Mexico", "Girls U9/U10 Mexico",
                                  "Girls U9-10 Mexico", "Girls U9–10 Mexico", "Girls U9/10 Mexico"])
def test_mixed_age_delimiters_do_not_block_unrelated_ready_cohort(label):
    parsed = parse_roster(label + "\nC\tMixed\nGirls U11\nC\tOlder")
    resolved = [ResolvedTeam(index, "gotsport_id", team_id_master=str(index)) for index in range(2)]
    result = assess_roster(parsed, resolved, {}, coverage="complete")
    assert result.cohorts[0]["Status"] == "Ready"


def test_progress_checkpoints_update_latest_without_archiving_each_team(tmp_path):
    parsed = parse_roster("Boys U10\nC\tA\nC\tB")
    run = SeedingRun("Checkpoint Cup", parsed.rows, ())
    save_run(run, base_dir=tmp_path)
    for completed in ([0], [0, 1]):
        save_run(replace(run, assessment={"completed": completed}), base_dir=tmp_path, archive_previous=False)
    assert load_run("checkpoint-cup", base_dir=tmp_path).assessment["completed"] == [0, 1]
    assert not (tmp_path / "checkpoint-cup/history").exists()
    save_run(replace(run, rows=run.rows[:1]), base_dir=tmp_path)
    assert len(list((tmp_path / "checkpoint-cup/history").glob("*.json"))) == 1


@pytest.mark.parametrize("label,inside,outside", [
    ("Girls U10/U11/U12", "u12", "u13"), ("Girls U10/11/12", "u12", "u13"),
    ("U9/U10G Mexico", "u10", "u11"), ("GU9/U10", "u10", "u11"),
    ("Girls U10–U14", "u12", "u15"), ("Girls U10-12-14", "u13", "u15"),
])
def test_readiness_uses_every_published_age_and_gender_suffix(label, inside, outside):
    row = replace(parse_roster("Girls U10\nC\tMixed").rows[0], section_age_group="", listed_division=label)
    assert could_belong(row, inside, "Female")
    assert not could_belong(row, outside, "Female")
    parsed = ParsedRoster((row, replace(row, source_index=1, section_age_group=inside, listed_division="")), ())
    result = assess_roster(parsed, [ResolvedTeam(i, "gotsport_id", team_id_master=str(i)) for i in range(2)],
                           {}, coverage="complete")
    assert result.cohorts[0]["Status"] == "Check coverage"


def test_incomplete_roster_price_is_explicitly_a_minimum():
    parsed = parse_roster("Boys U10\n" + "\n".join(f"C\tTeam {i}" for i in range(75)))
    for coverage in ("unknown", "partial"):
        assert assess_roster(parsed, (), {}, coverage=coverage).price == "$199 minimum"
    assert assess_roster(parsed, (), {}, coverage="complete").price == "$199"
    large = ParsedRoster(tuple(replace(parsed.rows[0], source_index=i) for i in range(601)), ())
    assert assess_roster(large, (), {}, coverage="partial").price == "Custom quote"
    assert assess_roster(ParsedRoster((), ()), (), {}, coverage="unknown").price == "Pending full roster"


def test_changing_review_cohort_discards_old_candidates_for_a_new_lookup():
    before = parse_roster("Boys U10\nC\tSquad")
    after = effective_roster(before, {0: {"section_age_group": "u11"}})
    resolved = [ResolvedTeam(0, "review", candidates=({"team_id_master": "old-cohort"},))]
    fixed, manual, reset = corrected_identities(before, after, resolved, {})
    assert fixed == (ResolvedTeam(0, "unresolved"),)
    assert not manual and reset == {0}
