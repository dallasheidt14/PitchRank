"""AGE_GROUPS birth years must match the wall-clock cohort derivation.

AGE_GROUPS is the config's cohort map; its birth_year values must agree with
team_utils' season derivation and with the published season tables, or config
consumers and the ingestion path file the same cohort under different years.
"""

import importlib
from pathlib import Path

from config.settings import AGE_GROUPS
from src.utils import team_utils
from src.utils.team_utils import calculate_age_group_from_birth_year

# Explicit tables pin the derivation to named seasons: a wrong year source that
# happens to agree with the soccer season for part of the year fails here.
_SEASON_TABLES = {
    2026: {10: 2017, 11: 2016, 12: 2015, 13: 2014, 14: 2013, 15: 2012, 16: 2011, 17: 2010, 19: 2008},
    2027: {10: 2018, 11: 2017, 12: 2016, 13: 2015, 14: 2014, 15: 2013, 16: 2012, 17: 2011, 19: 2009},
}


def test_expected_cohort_keys():
    assert set(AGE_GROUPS) == {"u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19"}


def test_birth_years_round_trip_through_the_wall_clock_derivation():
    for key, meta in AGE_GROUPS.items():
        assert calculate_age_group_from_birth_year(meta["birth_year"]) == key.upper(), key


def test_u19_holds_all_three_birth_years():
    stored = AGE_GROUPS["u19"]["birth_year"]
    # stored + 1 is the U18 band that merges in; stored - 1 is the band's older year.
    for birth_year in (stored + 1, stored, stored - 1):
        assert calculate_age_group_from_birth_year(birth_year) == "U19", birth_year


def test_dashboard_team_edit_does_not_write_a_band_birth_year():
    """A band year is not a team's actual birth year, so the team-edit save
    must not stamp one onto teams.birth_year.

    The scan is region-scoped, not literal-scoped: it covers everything from
    the Manual Team Edit section to the teams update call, so a birth_year
    write in any form (dict key, later assignment, renamed payload) fails.
    Reads such as the display-only form field stay legal."""
    dashboard_source = (Path(__file__).resolve().parents[2] / "dashboard.py").read_text(encoding="utf-8")
    marker = "'age_group': new_age_group"
    assert dashboard_source.count(marker) == 1, "team-edit payload not found in dashboard.py"
    anchor = dashboard_source.index(marker)
    start = dashboard_source.rindex("Manual Team Edit", 0, anchor)
    end = dashboard_source.index("db.table('teams').update(", anchor)
    region = dashboard_source[start:end]
    for forbidden in ("'birth_year':", '"birth_year":', "['birth_year']", '["birth_year"]'):
        assert forbidden not in region, forbidden


def test_named_season_tables_anchor_the_derivation(monkeypatch):
    import config.settings as settings_module

    real_table = {key: dict(meta) for key, meta in settings_module.AGE_GROUPS.items()}
    try:
        for season, expected in _SEASON_TABLES.items():
            monkeypatch.setattr(team_utils, "CURRENT_YEAR", season)
            importlib.reload(settings_module)
            derived = {age: settings_module.AGE_GROUPS[f"u{age}"]["birth_year"] for age in expected}
            assert derived == expected, season
    finally:
        # Rebind the real season before other tests import from config.settings.
        monkeypatch.undo()
        importlib.reload(settings_module)
    # The restore is load-bearing: without it, the last table leaks process-wide.
    assert {key: dict(meta) for key, meta in settings_module.AGE_GROUPS.items()} == real_table
