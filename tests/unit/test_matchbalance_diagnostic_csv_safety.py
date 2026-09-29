"""Diagnostic MatchBalance CSV exports are safe to open in spreadsheets."""

import csv

import pytest

from scripts.analyze_matchbalance_flight_plans import _write_csv as write_plan_csv
from scripts.analyze_matchbalance_groups import _write_csv as write_group_csv
from scripts.suggest_matchbalance_flights import _write_csv as write_suggestion_csv


@pytest.mark.parametrize(
    "writer",
    [write_group_csv, write_plan_csv, write_suggestion_csv],
)
def test_every_string_cell_is_defanged_before_csv_export(tmp_path, writer):
    path = tmp_path / "diagnostic.csv"
    dangerous = {
        "equals": '=HYPERLINK("https://example.invalid")',
        "plus": "+1+1",
        "minus": "-1+1",
        "at": "@SUM(1,1)",
        "tab": "\t=1+1",
        "carriage_return": "\r=1+1",
        "newline": "\n=1+1",
    }
    writer(
        path,
        [
            {
                "safe": "Ordinary team",
                "number": 12,
                **dangerous,
            }
        ],
    )

    with path.open(encoding="utf-8-sig", newline="") as handle:
        exported = next(csv.DictReader(handle))

    assert exported["safe"] == "Ordinary team"
    assert exported["number"] == "12"
    for key, value in dangerous.items():
        assert exported[key] == "'" + value
