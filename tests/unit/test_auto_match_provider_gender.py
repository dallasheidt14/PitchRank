"""The match report carries the export's GotSport gender for the record, and nothing else.

The weekly gate reads ``unknown_provider_gender`` as evidence of the record's gender, because its
own GotSport lookups go unanswered in CI. ``unknown_gender_used`` cannot stand in for it: when
nothing answers, the matcher fills that column from the gender of the team the record played.
"""

import csv
import sys

from scripts import auto_match_unknown_opponents as am
from tests.unit.test_due_diligence_gender_gate import _DB

EXPORT_COLUMNS = (
    "provider_code",
    "provider_id",
    "unknown_provider_team_id",
    "missing_side",
    "games_count",
    "unknown_team_name",
    "unknown_team_full_name",
    "unknown_club_name",
    "unknown_state",
    "unknown_age",
    "unknown_gender",
    "top_known_team_age_group",
    "top_known_team_gender",
    "top_known_team_state",
)


def _export_row(pid, name, gender, top_known_gender):
    row = dict.fromkeys(EXPORT_COLUMNS, "")
    row.update(
        provider_code="gotsport",
        provider_id="gotsport-uuid",
        unknown_provider_team_id=pid,
        missing_side="away",
        games_count="3",
        unknown_team_name=name,
        unknown_club_name="Lou Fusz Athletic",
        unknown_age="U9",
        unknown_gender=gender,
        top_known_team_age_group="u9",
        top_known_team_gender=top_known_gender,
    )
    return row


def test_the_report_carries_the_export_gender_and_never_the_opponent_s(tmp_path, monkeypatch):
    export = tmp_path / "aggregate.csv"
    with export.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerow(_export_row("750465", "LFA 17/18G Red Star Swift (2036)", "Female", "Male"))
        writer.writerow(_export_row("700001", "Lou Fusz Blue", "", "Male"))
    report = tmp_path / "report.csv"
    db = _DB({"providers": [{"id": "gotsport-uuid", "code": "gotsport", "name": "GotSport"}], "teams": []})
    monkeypatch.setattr(am, "load_env", lambda: None)
    monkeypatch.setattr(am, "get_supabase", lambda: db)
    monkeypatch.setattr(sys, "argv", ["am", "--input", str(export), "--output", str(report)])

    am.main()

    with report.open(encoding="utf-8") as f:
        rows = {r["unknown_provider_team_id"]: r for r in csv.DictReader(f)}
    assert rows["750465"]["unknown_provider_gender"] == "Female"
    assert rows["700001"]["unknown_provider_gender"] == ""
    assert rows["700001"]["unknown_gender_used"] == "Male"
    assert "teams" in db.executed
