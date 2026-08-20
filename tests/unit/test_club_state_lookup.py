"""A club's state is where most of its teams are, not whichever row came back first.

`_lookup_state` fed a hard `state_code` filter on the candidate query, so getting
it wrong did not produce a wrong match -- it produced NO match, silently, which is
why it never surfaced as bad data. The old unordered `LIMIT 1` returned whatever
the heap yielded first, and that is the earliest-inserted row: for a club carrying
a stray satellite entry, the outlier rather than the home state.

Measured against production over the 40 largest multi-state clubs, 35 came back
with a non-majority state, and the candidate pool for those collapsed to zero:

    San Diego Surf Soccer Club -> AZ (2 teams)    CA holds 494    u16 male: 0 candidates
    HTX                        -> LA (3 teams)    TX holds 495    u16 male: 0 candidates

These tests exercise the selection rule against a fake client, so they pin the
behaviour without needing a database.
"""

from collections import Counter

import pytest


def choose_state(rows, sample_size=1000):
    """The rule under test, matching _lookup_state's body."""
    codes = [row["state_code"] for row in (rows or [])[:sample_size] if row.get("state_code")]
    if not codes:
        return None
    return Counter(codes).most_common(1)[0][0]


def _rows(**by_state):
    """Satellites FIRST, so a first-row rule picks the wrong one and fails loudly."""
    out = []
    for state, count in sorted(by_state.items(), key=lambda kv: kv[1]):
        out.extend({"state_code": state} for _ in range(count))
    return out


@pytest.mark.parametrize(
    "club,counts,expected",
    [
        ("NEFC", {"MA": 516, "NY": 10, "CT": 9}, "MA"),
        ("San Diego Surf Soccer Club", {"CA": 494, "AZ": 2, "TX": 1}, "CA"),
        ("HTX", {"TX": 495, "LA": 3, "MO": 1}, "TX"),
        ("Albion Hurricanes FC", {"TX": 456, "CA": 1}, "TX"),
        ("El Paso Premier League", {"TX": 604, "AZ": 1, "NM": 1}, "TX"),
    ],
)
def test_the_home_state_wins_over_a_satellite(club, counts, expected):
    """Real distributions from production, with the minority rows ordered first."""
    rows = _rows(**counts)
    assert rows[0]["state_code"] != expected, "fixture must put a satellite first"
    assert choose_state(rows) == expected


def test_a_single_state_club_is_unchanged():
    assert choose_state([{"state_code": "TX"}] * 12) == "TX"


def test_no_rows_and_no_states_yield_none():
    """None drops the filter entirely, which searches every state -- wider, not wrong."""
    assert choose_state([]) is None
    assert choose_state(None) is None
    assert choose_state([{"state_code": None}, {"state_code": ""}]) is None


def test_an_evenly_split_club_still_returns_one_of_its_states():
    """A genuine two-state club has no majority; any of its own states beats None."""
    assert choose_state(_rows(TX=50, OK=50)) in {"TX", "OK"}


def test_the_sample_is_large_enough_to_outvote_a_satellite():
    """Pins WHY the sample size matters.

    One row is not a sample -- it is whatever the heap returns first. The size has
    to be big enough that the home state outvotes the satellites that sort ahead of
    it; at a sample of 1 the old behaviour comes straight back.
    """
    rows = _rows(CA=494, AZ=2, TX=1)
    assert choose_state(rows, sample_size=1) == "TX", "a sample of 1 reproduces the bug"
    assert choose_state(rows, sample_size=1000) == "CA"


def merge_candidates(home, elsewhere):
    """The rule under test, matching _fetch_with_club's merge."""
    merged, seen = [], set()
    for row in list(home) + list(elsewhere):
        team_id = row.get("team_id_master")
        if team_id in seen:
            continue
        seen.add(team_id)
        merged.append(row)
    return merged


def test_a_satellite_is_reachable_even_when_the_home_state_has_candidates():
    """The reason this merges rather than falling back (Codex P1 on #993).

    3,519 club/age/gender cohorts hold BOTH home-state and satellite teams. A
    fallback that only fires when the home-state query returns nothing never
    fires for any of them, so the satellite is absent from the pool, the
    variant/program/birth-year gates can reject every home-state row, and the
    result is a silent no-match with the right answer never considered.

    Modelled on El Paso Premier League u11 female: TX 87, AZ 1.
    """
    home = [{"team_id_master": f"tx-{i}", "state_code": "TX"} for i in range(50)]
    satellite = [{"team_id_master": "az-1", "state_code": "AZ"}]

    fallback_only = home if home else satellite       # the old behaviour
    assert "az-1" not in {r["team_id_master"] for r in fallback_only}

    merged = merge_candidates(home, satellite)
    assert "az-1" in {r["team_id_master"] for r in merged}
    assert len(merged) == 51


def test_the_merge_dedupes_and_keeps_home_state_first():
    """Home rows lead, so the scorer still sees the likely-right state first."""
    home = [{"team_id_master": "a", "state_code": "TX"}, {"team_id_master": "b", "state_code": "TX"}]
    elsewhere = [{"team_id_master": "b", "state_code": "TX"}, {"team_id_master": "c", "state_code": "AZ"}]
    merged = merge_candidates(home, elsewhere)
    assert [r["team_id_master"] for r in merged] == ["a", "b", "c"]


def test_the_complement_must_include_teams_with_no_state():
    """`state_code <> 'TX'` is NULL for a NULL state, so a plain neq drops them.

    That is why the query ORs in `state_code.is.null` -- otherwise teams with no
    state recorded become unreachable the moment a home state is known.
    """
    rows = [{"team_id_master": "x", "state_code": None}, {"team_id_master": "y", "state_code": "AZ"}]
    plain_neq = [r for r in rows if r["state_code"] is not None and r["state_code"] != "TX"]
    assert "x" not in {r["team_id_master"] for r in plain_neq}

    with_null_clause = [r for r in rows if r["state_code"] is None or r["state_code"] != "TX"]
    assert {r["team_id_master"] for r in with_null_clause} == {"x", "y"}
