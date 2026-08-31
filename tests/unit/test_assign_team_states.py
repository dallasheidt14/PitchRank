"""The decision rules the state-assignment tool applies, and the registry behind them.

Every case here is a rule an operator is told to rely on in
.claude/skills/assigning-team-states. They drive the real ``decide`` function rather than a
reimplementation of it, because the failure this guards against is the rule changing while
the prose keeps promising the old one.
"""

import os
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.assign_team_states as assign  # noqa: E402
from scripts.assign_team_states import (  # noqa: E402
    apply_snapshot,
    build_locality_index,
    club_derived_state,
    decide,
    locality_state,
)
from src.utils.club_state_registry import CLUBS, home_state, requires_review  # noqa: E402

CLEAN_CLUB = {"clean club": Counter({"OH": 40})}
CURATED_CLUB = {"fc stars": Counter({"MA": 284})}


def team(**fields):
    base = {
        "team_id_master": "t",
        "team_name": "",
        "club_name": "",
        "state_code": None,
        "state": None,
    }
    base.update(fields)
    return base


def decision(team_row, clubs=None, locality=None, associations=None, reverts=None):
    return decide(team_row, clubs or {}, locality or {}, associations or {}, reverts or set())


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #


def test_a_home_and_a_curate_flag_are_mutually_exclusive():
    """A home settles the club; curate says nobody can. An entry cannot mean both."""
    for key, entry in CLUBS.items():
        assert bool(entry["home"]) != bool(entry["curate"]), key


@pytest.mark.parametrize(
    "club,expected",
    [
        ("arizona arsenal soccer club", "AZ"),
        ("city sc", "CA"),
        ("soccer chance academy", "OR"),
        ("steel city fc", "PA"),
    ],
)
def test_the_operator_confirmed_homes(club, expected):
    """The only external ground truth this problem has: four homes confirmed by hand,
    blind to the analysis, on 2026-08-28."""
    assert home_state(club) == expected


def test_the_registry_key_is_the_raw_club_name_lowercased():
    assert home_state("  Steel City FC  ") == "PA"


def test_an_unknown_club_neither_homes_nor_curates():
    assert home_state("a club that does not exist") is None
    assert requires_review("a club that does not exist") is False


# --------------------------------------------------------------------------- #
# Tier B
# --------------------------------------------------------------------------- #


def test_the_club_count_excludes_the_team_being_decided():
    """A wrongly-coded team must not vote for the bucket it created. With one clubmate
    sharing the error that bucket reaches the two-team floor, silences the tier, and
    preserves the very error the tier exists to correct."""
    clubs = {"c": Counter({"OH": 30, "WV": 2})}
    assert club_derived_state(team(club_name="c", state_code="WV"), clubs) == "OH"


def test_two_meaningful_states_silence_the_club():
    clubs = {"c": Counter({"OH": 30, "KY": 20})}
    assert club_derived_state(team(club_name="c"), clubs) is None


def test_a_registry_home_replaces_the_count_entirely():
    """R11: where a home is set it IS the club's state, whatever its teams say."""
    clubs = {"city sc": Counter({"AZ": 90, "CA": 10})}
    assert club_derived_state(team(club_name="city sc"), clubs) == "CA"


# --------------------------------------------------------------------------- #
# Tier E
# --------------------------------------------------------------------------- #


def test_a_token_earns_a_state_only_with_enough_teams_and_agreement():
    teams = [team(team_name="Boise Timbers", state_code="ID") for _ in range(12)]
    teams += [team(team_name="Boise Timbers", state_code="WY") for _ in range(1)]
    teams += [team(team_name="Springfield SC", state_code=code) for code in ("MO", "VA", "PA", "OH") * 4]
    index = build_locality_index(teams)
    assert index["boise"] == "ID"
    assert "springfield" not in index


def test_a_name_pointing_at_two_states_points_at_neither():
    index = {"boise": "ID", "dallas": "TX"}
    assert locality_state(team(team_name="Boise at the Dallas Cup"), index) is None


def test_brand_words_are_never_places():
    """"Surf" and "Rush" are national franchises with a dominant state, which is exactly
    the shape that reads as a place."""
    teams = [team(team_name="Surf Select", state_code="CA") for _ in range(50)]
    assert "surf" not in build_locality_index(teams)


# --------------------------------------------------------------------------- #
# The cascade
# --------------------------------------------------------------------------- #


def test_a_stored_canadian_province_is_never_touched():
    assert decision(team(state_code="ON", club_name="clean club"), CLEAN_CLUB) is None


def test_a_fill_from_the_club_auto_applies():
    assert decision(team(club_name="clean club"), CLEAN_CLUB)["action"] == "apply"


def test_a_curated_club_queues_instead():
    assert decision(team(club_name="fc stars"), CURATED_CLUB)["action"] == "queue"


def test_the_provider_record_outranks_the_club():
    result = decision(
        team(state_code="WY", club_name="clean club"), CLEAN_CLUB, associations={"t": "ID"}
    )
    assert (result["tier"], result["proposed"], result["action"]) == ("A", "ID", "apply")


def test_a_name_may_fill_but_never_correct():
    filled = decision(team(team_name="Michigan Wolves 19"))
    corrected = decision(team(team_name="Michigan Wolves 19", state_code="KY"))
    assert filled["action"] == "apply"
    assert corrected["action"] == "queue"


def test_a_place_that_contradicts_the_club_stops_the_write():
    """The Boise case: five of six clubmates said Wyoming, so the club agreed with itself
    and nothing local disputed the sixth."""
    result = decision(
        team(state_code="WY", team_name="BTT 17 Boise Timbers", club_name="boise club"),
        {"boise club": Counter({"WY": 5})},
        locality={"boise": "ID"},
    )
    assert result["action"] == "queue"
    assert result["tier"] == "R9"


def test_the_provider_record_settles_a_disagreement_rather_than_queueing_it():
    result = decision(
        team(state_code="WY", team_name="BTT 17 Boise Timbers", club_name="boise club"),
        {"boise club": Counter({"WY": 5})},
        locality={"boise": "ID"},
        associations={"t": "ID"},
    )
    assert (result["tier"], result["proposed"]) == ("A", "ID")


def test_a_reported_state_is_not_overruled_by_counting_a_club():
    """Chariho YSA is a Rhode Island club whose clubmate bucket says New York."""
    result = decision(
        team(state_code="RI", state="Rhode Island", club_name="clean club"), CLEAN_CLUB
    )
    assert result["action"] == "queue"


def test_a_reported_state_is_overruled_by_a_per_team_provider_record():
    result = decision(
        team(state_code="RI", state="Rhode Island", club_name="clean club"),
        CLEAN_CLUB,
        associations={"t": "OH"},
    )
    assert result["action"] == "apply"


def test_a_stored_dc_always_queues():
    """Every sampled DC team's association reports MD, so an auto-apply would quietly
    relabel the District."""
    result = decision(team(state_code="DC", club_name="clean club"), CLEAN_CLUB)
    assert result["action"] == "queue"


def test_a_value_the_operator_reverted_is_not_re_applied():
    """Without this a revert survives only until the next sweep recomputes the same
    evidence and writes the same value back."""
    result = decision(team(club_name="clean club"), CLEAN_CLUB, reverts={("t", "OH")})
    assert result["action"] == "queue"


def test_agreeing_with_the_stored_state_is_not_a_decision():
    assert decision(team(state_code="OH", club_name="clean club"), CLEAN_CLUB) is None


def test_a_decision_carries_the_state_it_was_computed_against():
    """--execute replays these, and the pre-image is what makes a stale one skip rather
    than overwrite a newer value."""
    result = decision(team(state_code="WY", club_name="clean club"), CLEAN_CLUB)
    assert result["pre_image"] == "WY"


# --------------------------------------------------------------------------- #
# What the scheduled job has to be able to install
# --------------------------------------------------------------------------- #


def test_nothing_under_src_scrapers_is_imported_at_module_scope():
    """The weekly fills-only job installs five packages, not requirements.txt.

    ``src.scrapers.gotsport`` reaches BaseScraper and config.settings, which pull bs4,
    pandas, scipy, sklearn and xgboost. A top-level import of it costs nothing locally
    and kills the runner at startup with ModuleNotFoundError: bs4 -- verified against a
    venv holding only supabase, python-dotenv, truststore, rich and requests. Tier A is
    the only caller and the scheduled job runs --no-tier-a, so the import belongs inside
    ``probe_associations``.
    """
    import ast

    source = Path(assign.__file__).read_text(encoding="utf-8")
    top_level = [n for n in ast.parse(source).body if isinstance(n, ast.ImportFrom)]
    offenders = [n.module for n in top_level if (n.module or "").startswith("src.scrapers")]

    assert not offenders, f"import these inside the function that needs them: {offenders}"


# --------------------------------------------------------------------------- #
# Replaying a snapshot
# --------------------------------------------------------------------------- #


def replay(monkeypatch, decisions, reverts=frozenset(), **kwargs):
    """Drive the real ``apply_snapshot`` over `decisions`, returning what it did.

    Everything that touches the database is stubbed; what is under test is which
    decisions reach ``apply_decision`` and which reach ``queue_decision``.
    """
    applied, queued = [], []
    monkeypatch.setattr(assign, "fetch_revert_blocks", lambda sb: set(reverts))
    monkeypatch.setattr(assign, "fetch_queue_rows", lambda sb: {})
    monkeypatch.setattr(assign, "mirror_rankings", lambda sb, rows: len(rows))
    monkeypatch.setattr(
        assign, "apply_decision", lambda sb, d, reason: applied.append(d["team_id"]) or True
    )
    monkeypatch.setattr(
        assign, "queue_decision", lambda sb, d, existing: queued.append(d["team_id"]) or "queued"
    )
    apply_snapshot(None, {"created_at": "2026-08-29T00:00:00+00:00", "decisions": decisions}, **kwargs)
    return applied, queued


def proposal(team_id, pre_image, action="apply"):
    return {
        "team_id": team_id, "pre_image": pre_image, "proposed": "OH", "tier": "B",
        "confidence": 0.9, "action": action,
        "reason": "fill" if pre_image is None else "correct",
    }


def test_a_decision_reverted_since_the_snapshot_is_queued_not_re_applied(monkeypatch):
    """The hard case for a limited batch. A revert restores the pre-image, so replaying
    the decision would find its predicate satisfied and quietly undo the rollback -- the
    snapshot's own reading of the ledger is too old to catch it."""
    applied, queued = replay(
        monkeypatch,
        [proposal("reverted", None), proposal("fine", None)],
        reverts={("reverted", "OH")},
        limit=None,
    )

    assert applied == ["fine"]
    assert queued == ["reverted"]


def test_fills_only_never_applies_a_correction(monkeypatch):
    """The whole basis of running this unattended. A second dry run proposes 664 applies,
    90 of them overwriting what the first pass just wrote, because a fill moves the
    clubmate counts Tier B reads next time; two teams of one club oscillate forever. A
    fill has no such feedback -- it overwrites nothing -- so only fills may run weekly."""
    applied, _ = replay(
        monkeypatch,
        [proposal("blank", None), proposal("stored-nv", "NV")],
        fills_only=True,
        limit=None,
    )

    assert applied == ["blank"]


def test_fills_only_withholds_a_correction_rather_than_queueing_it(monkeypatch):
    """Queueing them instead would hand the operator ~600 rows a week of exactly the
    proposals that do not converge. They wait for a sweep a person is running."""
    _, queued = replay(
        monkeypatch,
        [proposal("stored-nv", "NV"), proposal("needs-review", "WA", action="queue")],
        fills_only=True,
        limit=None,
    )

    assert queued == ["needs-review"]


def test_fills_only_limits_the_fills_it_keeps_not_the_applies_it_started_with(monkeypatch):
    """--limit is a batch size for an operator watching what lands. Filtering after it
    would make `--limit 50` write however many of the first 50 happened to be fills."""
    applied, _ = replay(
        monkeypatch,
        [proposal("c1", "NV"), proposal("c2", "NV"), proposal("f1", None), proposal("f2", None)],
        fills_only=True,
        limit=2,
    )

    assert applied == ["f1", "f2"]
