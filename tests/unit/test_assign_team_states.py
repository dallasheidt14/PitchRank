"""The decision rules the state-assignment tool applies, and the registry behind them.

Every case here is a rule an operator is told to rely on in
.claude/skills/assigning-team-states. They drive the real ``decide`` function rather than a
reimplementation of it, because the failure this guards against is the rule changing while
the prose keeps promising the old one.
"""

import itertools
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.assign_team_states as assign  # noqa: E402
from scripts.assign_team_states import (  # noqa: E402
    apply_snapshot,
    build_anchor_index,
    build_club_index,
    build_locality_index,
    club_derived_state,
    contradiction_candidates,
    decide,
    locality_state,
    probe_list,
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


def test_an_affiliate_marker_outranks_a_learned_place_word():
    """Tier C has always refused "Utah Royals FC-AZ"; Tier E did not, and read 22 Arizona
    teams as Utah because the club name holds the word "utah". The marker sits on the club
    name rather than the team's, so both fields are checked."""
    index = {"utah": "UT"}

    assert locality_state(team(team_name="Utah Royals 2015", club_name="Utah Royals FC - AZ"), index) is None
    assert locality_state(team(team_name="Utah Royals 2015", club_name="Utah Royals FC (AZ)"), index) is None


def test_an_affiliate_marker_agreeing_with_the_place_still_fires():
    """The guard refuses a contradiction, not every marker."""
    index = {"utah": "UT"}

    assert locality_state(team(team_name="Utah Royals 2015", club_name="Utah Royals FC - UT"), index) == "UT"


def test_soccer_vocabulary_is_not_an_affiliate_marker():
    """SC is Soccer Club and GA is Girls Academy. Reading them as states is what
    _NOT_STATE_TOKENS exists to stop, and Tier E now inherits that too."""
    index = {"portland": "OR"}

    assert locality_state(team(team_name="Portland Thorns", club_name="Portland Thorns - SC"), index) == "OR"
    assert locality_state(team(team_name="Portland Thorns", club_name="Portland Thorns (GA)"), index) == "OR"


def test_coach_initials_on_a_team_name_are_not_an_affiliate_marker():
    """SoCal Reds FC fields "- AV", "- RK", "- JW", "- JM" and "- AR", all California.
    7,496 team names carry a marker of that shape against 1,624 club names, so the check
    reads the club name only -- otherwise a coach's initials would suppress this tier on
    exactly the teams whose club cannot answer for them."""
    index = {"socal": "CA"}

    assert locality_state(team(team_name="MLS NEXT AD U14 - MD", club_name="Socal Reds FC"), index) == "CA"
    assert locality_state(team(team_name="SOCAL REDS FC 2012 EA - AR", club_name=""), index) == "CA"


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


def test_the_unset_default_association_cannot_settle_a_disagreement():
    """R8b. GotSport reports ``AL`` both for Alabama and for a team whose association was
    never set. The four Cold Spring Harbor Huntington (LIJSL) teams are in New York and
    reached the Alabama board by this exact path.

    Nothing is proposed here because nothing needs to change: the club already says NY.
    The point is that AL does not overrule it.
    """
    assert (
        decision(
            team(state_code="NY", club_name="lijsl club"),
            {"lijsl club": Counter({"NY": 38})},
            associations={"t": "AL"},
        )
        is None
    )


def test_a_disputed_default_lets_the_club_correct_the_team():
    """The self-healing case, and the reason a disputed AL is dropped rather than queued.
    Queueing returns a decision, which stops the cascade before Tier B is reached and
    leaves the wrong state standing with a review row beside it."""
    result = decision(
        team(state_code="MD", club_name="lijsl club"),
        {"lijsl club": Counter({"NY": 38})},
        associations={"t": "AL"},
    )
    assert (result["tier"], result["proposed"], result["action"]) == ("B", "NY", "apply")


def test_an_alabama_club_still_reaches_alabama():
    """The other 65 of the 86. The rule withholds AL only where something disputes it, so
    a club whose own teams are in Alabama is untouched."""
    result = decision(
        team(state_code="TN", club_name="prattville elite"),
        {"prattville elite": Counter({"AL": 12})},
        associations={"t": "AL"},
    )
    assert (result["proposed"], result["action"]) == ("AL", "apply")


def test_the_unset_default_still_fills_a_blank_nothing_disputes():
    """A blank with no club evidence is the case AL is the only answer for."""
    result = decision(team(club_name="unknown club"), {}, associations={"t": "AL"})
    assert (result["proposed"], result["action"]) == ("AL", "apply")


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


def _replay(monkeypatch, decisions, reverts=frozenset(), sources=None, refuse=frozenset(), **kwargs):
    """Drive the real ``apply_snapshot`` over `decisions` with every database touch stubbed.

    Returns what reached each writer and the order they were called in. ``reverts`` may be
    a set (the ledger as read every time) or a list of sets, one per read, for the tests
    that need the ledger to change mid-replay. ``refuse`` names the teams whose RPC reports
    the state moved.
    """
    captured = {"applied": [], "queued": [], "mirrored": [], "order": [], "sources_read": []}
    reads = list(reverts) if isinstance(reverts, list) else [set(reverts)]

    def fake_reverts(sb):
        return set(reads.pop(0)) if len(reads) > 1 else set(reads[0])

    def fake_sources(sb, ids):
        # Faithful to the real reader, which answers only for the ids it was handed: a
        # phase reading provenance for the wrong teams must find nothing, not everything.
        captured["sources_read"].append(list(ids))
        return {t: s for t, s in (sources or {}).items() if t in ids}

    def fake_apply(sb, d, reason):
        captured["order"].append(d["action"])
        if d["team_id"] in refuse:
            return False
        captured["applied"].append(d["team_id"])
        return True

    monkeypatch.setattr(assign, "fetch_revert_blocks", fake_reverts)
    monkeypatch.setattr(assign, "fetch_queue_rows", lambda sb: {})
    monkeypatch.setattr(assign, "fetch_state_sources", fake_sources)
    monkeypatch.setattr(assign, "state_of", lambda sb, team_id: None)
    monkeypatch.setattr(
        assign,
        "mirror_rankings",
        lambda sb, rows: (captured["order"].append("mirror"), captured["mirrored"].extend(rows))
        and len(rows),
    )
    monkeypatch.setattr(assign, "apply_decision", fake_apply)
    monkeypatch.setattr(
        assign,
        "queue_decision",
        lambda sb, d, existing: (captured["order"].append("queue"), captured["queued"].append(d["team_id"]))
        and "queued",
    )
    apply_snapshot(None, {"created_at": "2026-08-29T00:00:00+00:00", "decisions": decisions}, **kwargs)
    return captured


def replay(monkeypatch, decisions, reverts=frozenset(), **kwargs):
    """``_replay`` for the tests that read only the applies and the queue."""
    captured = _replay(monkeypatch, decisions, reverts=reverts, **kwargs)
    return captured["applied"], captured["queued"]


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


# --------------------------------------------------------------------------- #
# The contradiction audit's selection
# --------------------------------------------------------------------------- #


def anchored(**fields):
    """A team whose state a provider record confirmed, so it can anchor its club."""
    return team(state_source="tier_a", **fields)


def test_a_club_whose_confirmed_teams_agree_anchors_its_state():
    index = build_anchor_index(
        [
            anchored(team_id_master="a", club_name="Clean FC", state_code="OH"),
            anchored(team_id_master="b", club_name="Clean FC", state_code="OH"),
            team(team_id_master="c", club_name="Clean FC", state_code="WA"),
        ]
    )

    assert index == {"clean fc": ("OH", 2)}


def test_a_club_whose_confirmed_teams_disagree_anchors_nothing():
    """Two confirmed states in one club means the name covers two clubs. That is the
    shape the false positives come from, not a vote to be settled by majority."""
    index = build_anchor_index(
        [
            anchored(team_id_master="a", club_name="Elite FC", state_code="OH"),
            anchored(team_id_master="b", club_name="Elite FC", state_code="OH"),
            anchored(team_id_master="c", club_name="Elite FC", state_code="TX"),
        ]
    )

    assert index == {}


def test_an_unconfirmed_team_never_anchors():
    """The whole point is evidence from outside the column being audited. Counting a
    stored state here would make a uniformly mislabelled club anchor its own error."""
    index = build_anchor_index(
        [
            team(team_id_master="a", club_name="Guessed FC", state_code="OH"),
            team(team_id_master="b", club_name="Guessed FC", state_code="OH"),
        ]
    )

    assert index == {}


ANCHOR = {"anchored fc": ("OH", 3)}


def test_a_team_contradicting_its_confirmed_clubmates_is_selected():
    teams = [team(team_id_master="wrong", club_name="Anchored FC", state_code="WA")]

    assert contradiction_candidates(teams, ANCHOR) == [("wrong", 3)]


def test_a_team_agreeing_with_the_anchor_is_not_selected():
    teams = [team(team_id_master="fine", club_name="Anchored FC", state_code="OH")]

    assert contradiction_candidates(teams, ANCHOR) == []


def test_an_already_confirmed_team_is_not_selected():
    """Its state came from the provider, so asking again buys nothing."""
    teams = [anchored(team_id_master="known", club_name="Anchored FC", state_code="WA")]

    assert contradiction_candidates(teams, ANCHOR) == []


def test_a_stateless_team_is_not_a_contradiction():
    """A blank contradicts nothing. Those are the sweep's business, not the audit's."""
    teams = [team(team_id_master="blank", club_name="Anchored FC", state_code=None)]

    assert contradiction_candidates(teams, ANCHOR) == []


def test_a_stored_canadian_province_is_excluded():
    """No tier corrects one, so the call would buy nothing."""
    teams = [team(team_id_master="canadian", club_name="Anchored FC", state_code="ON")]

    assert contradiction_candidates(teams, ANCHOR) == []


def test_a_stored_dc_is_kept():
    """The deliberate contrast with Canada: DC queues rather than applies, and a review
    row carrying the provider's answer is worth the call."""
    teams = [team(team_id_master="district", club_name="Anchored FC", state_code="DC")]

    assert contradiction_candidates(teams, ANCHOR) == [("district", 3)]


def test_a_placeholder_club_cannot_anchor_or_be_selected():
    """It keys to "", so it never enters the index and never matches one."""
    rows = [
        anchored(team_id_master="a", club_name="No Club Selection", state_code="OH"),
        anchored(team_id_master="b", club_name="No Club Selection", state_code="OH"),
        team(team_id_master="c", club_name="No Club Selection", state_code="WA"),
    ]

    assert build_anchor_index(rows) == {}
    assert contradiction_candidates(rows, {"": ("OH", 2)}) == []


def test_candidates_are_ordered_by_anchor_strength_then_id():
    """Strongest evidence first, so a budget spends on the best of it, and deterministic
    so the next run continues where a capped one stopped."""
    index = {"one fc": ("OH", 1), "two fc": ("OH", 2)}
    teams = [
        team(team_id_master="b", club_name="One FC", state_code="WA"),
        team(team_id_master="a", club_name="One FC", state_code="WA"),
        team(team_id_master="z", club_name="Two FC", state_code="WA"),
    ]

    assert contradiction_candidates(teams, index) == [("z", 2), ("a", 1), ("b", 1)]


def test_the_probe_list_drops_a_durably_answered_team():
    """Only a durable outcome suppresses. A transient one -- a WAF block -- says nothing
    about the team, and suppressing on it would skip exactly the teams a blocked run
    failed on for the whole window; ``fetch_recent_probes`` filters those out before they
    reach here, and ``test_the_reader_drops_transient_outcomes`` is what pins that."""
    candidates = [("answered", 3), ("fresh", 2)]
    recent = {"answered": ("mapped", "OH")}

    assert probe_list(candidates, recent, None) == ["fresh"]


def test_the_probe_list_applies_the_budget_after_suppression():
    """The budget bounds new calls, not the population, so a suppressed team does not
    consume a slot that a never-asked team could have used."""
    candidates = [("answered", 3), ("a", 2), ("b", 2), ("c", 1)]
    recent = {"answered": ("mapped", "OH")}

    assert probe_list(candidates, recent, 2) == ["a", "b"]


def test_a_zero_budget_probes_nothing():
    """0 is a budget, not an absent one. The truthiness idiom would spend the lot."""
    assert probe_list([("a", 2), ("b", 1)], {}, 0) == []


def test_the_probe_list_preserves_candidate_order():
    candidates = [("z", 3), ("a", 1)]

    assert probe_list(candidates, {}, None) == ["z", "a"]


# --------------------------------------------------------------------------- #
# The audit run: the half that spends money
# --------------------------------------------------------------------------- #


def audit(
    monkeypatch,
    teams,
    aliases,
    recent=None,
    answers=None,
    outcomes=None,
    mode="audit_contradictions",
    **kwargs,
):
    """Drive the real ``build_snapshot`` in one of the answered-only modes, capturing what
    it paid for. ``mode`` names the population flag: ``audit_contradictions`` (default),
    ``anchor_clubs`` or ``probe_unclubbed``.

    Everything touching the database is stubbed, but the alias lookup and the probe both
    record the ids they were handed: those arguments are the seam where a budget or a
    cache either works or silently does not. ``looked_up`` is the last lookup; ``lookups``
    is every one, for the modes that look the population up before picking from it.
    """
    handed = {"lookups": []}

    def fake_aliases(sb, ids):
        handed["looked_up"] = list(ids)
        handed["lookups"].append(list(ids))
        return {t: f"p{t}" for t in ids if t in aliases}

    def fake_probe(ids, workers, sb, stored):
        handed["probed"] = list(ids)
        return dict(answers or {}), Counter(outcomes or {"mapped": len(ids)})

    monkeypatch.setattr(assign, "fetch_live_teams", lambda sb: teams)
    monkeypatch.setattr(assign, "fetch_revert_blocks", lambda sb: set())
    # Faithful to the real reader, which drops transient outcomes before they can
    # suppress anything. A stub returning them raw would let a fixture prove something
    # production never sees.
    durable = {
        t: v for t, v in (recent or {}).items() if not v[0].startswith(assign.TRANSIENT_OUTCOMES)
    }
    def fake_recent(sb, cutoff):
        handed["cutoff"] = cutoff
        return durable

    monkeypatch.setattr(assign, "fetch_recent_probes", fake_recent)
    monkeypatch.setattr(assign, "fetch_gotsport_aliases", fake_aliases)
    monkeypatch.setattr(assign, "write_probe_log", lambda sb, rows: None)
    monkeypatch.setattr(assign, "ranked_and_active", lambda sb, ids: [])
    monkeypatch.setattr(assign, "probe_associations", fake_probe)
    snapshot = assign.build_snapshot(None, use_tier_a=True, workers=1, **{mode: True}, **kwargs)
    return snapshot, handed


def audit_teams():
    """Two confirmed OH teams anchoring their club, and two that contradict them."""
    return [
        anchored(team_id_master="anchor1", club_name="Anchored FC", state_code="OH"),
        anchored(team_id_master="anchor2", club_name="Anchored FC", state_code="OH"),
        team(team_id_master="wrong1", club_name="Anchored FC", state_code="WA"),
        team(team_id_master="wrong2", club_name="Anchored FC", state_code="NV"),
    ]


def quiet_club_teams():
    """The population the audit exists for: nothing local disputes any of it.

    One confirmed OH anchor against five WA club-mates. Self-exclusion leaves each WA
    team four WA neighbours, so its own club derives WA, matches its stored value, and no
    free tier proposes anything. ``audit_teams()`` cannot stand in here -- its club is two
    OH against one WA and one NV, so Tier B already corrects both candidates unaided.
    """
    return [anchored(team_id_master="anchor1", club_name="Quiet FC", state_code="OH")] + unanchored_club(size=5)


def test_no_free_tier_disputes_the_quiet_club_the_audit_exists_for():
    """Half one of the feature's premise, over the same population half two uses."""
    teams = quiet_club_teams()
    clubs = build_club_index(teams)

    assert all(decision(t, clubs=clubs) is None for t in teams if t["state_code"] == "WA")


def test_the_audit_selects_the_quiet_club_anyway(monkeypatch):
    """Half two, and the reason the mode was built. Every earlier audit test ran against a
    club Tier B already corrects, so the sweep reached that population unaided and none of
    them proved the audit adds anything."""
    teams = quiet_club_teams()
    ids = {f"quiet{i}" for i in range(5)}
    snapshot, handed = audit(
        monkeypatch, teams, aliases=ids, answers={t: "OH" for t in ids}
    )

    assert sorted(handed["looked_up"]) == sorted(ids)
    assert snapshot["candidates_selected"] == 5
    assert {d["team_id"] for d in snapshot["decisions"]} == ids
    assert all(d["tier"] == "A" and d["proposed"] == "OH" for d in snapshot["decisions"])


def test_the_audit_probes_only_the_contradicting_teams(monkeypatch):
    """The anchors are already confirmed, so asking about them buys nothing, and every
    other team in the database is outside the population entirely."""
    snapshot, handed = audit(monkeypatch, audit_teams(), aliases={"wrong1", "wrong2"})

    assert sorted(handed["looked_up"]) == ["wrong1", "wrong2"]
    assert snapshot["candidates_selected"] == 2
    assert snapshot["mode"] == "audit"


def test_a_cached_answer_for_a_team_outside_the_population_decides_nothing(monkeypatch):
    """Two clauses hold the audit's write scope -- selected, and answered -- and this pins
    the pair. Removing either one alone is undetectable by construction and always will be:
    each is sufficient on its own, so no input separates them. What this catches is the
    second removal, which is the one that leaks.

    Worth the guard because the population is real and growing. The normal sweep probes
    thousands of teams the audit never selected, and their answers land in the same ledger
    this mode reads back; ``outsider`` stands in for one of them.
    """
    teams = audit_teams() + [team(team_id_master="outsider", club_name="Other FC", state_code="WA")]
    snapshot, _ = audit(
        monkeypatch,
        teams,
        aliases={"wrong1", "wrong2"},
        recent={"outsider": ("mapped", "OH")},
    )

    assert "outsider" not in {d["team_id"] for d in snapshot["decisions"]}
    assert snapshot["candidates_selected"] == 2
    # Not only the decisions: the cache filter's own clause has an observable effect, and
    # asserting the decisions alone leaves it to `audit_scope` to catch. Dropping
    # `team_id in selected` pulls every team the normal sweep ever probed into these
    # two counts while the decisions still look right.
    assert snapshot["cached_answers"] == 0
    assert snapshot["tier_a_probed"] == 0


def test_the_snapshot_reports_the_paid_call_count_it_claims_to(monkeypatch):
    """``aliases_found`` is the paid-call count and ``tier_a_probed`` deliberately is not
    -- it counts cache-seeded answers too. An operator sizes the next --probe-limit from
    the ZenRows bill against these, so a field computed off the wrong collection is read
    as a fiction rather than caught.

    ``wrong2`` is probed but has no alias, so ``aliases_found`` is strictly below the
    probed count. A fixture that hands an alias for every probed id makes the two equal and
    computing this field off ``to_probe`` invisible; a meaningful minority of real
    candidates carry no alias, so the gap is the normal case rather than the edge.
    """
    snapshot, _ = audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1"},
        answers={"wrong1": "OH"},
    )

    assert snapshot["candidates_selected"] == 2
    assert snapshot["probed"] == ["wrong1", "wrong2"]
    assert snapshot["aliases_found"] == 1
    assert snapshot["tier_a_probed"] == 1


def test_a_missing_provider_row_refuses_instead_of_retiring_the_population(monkeypatch):
    """One configuration fault must not arrive as a per-team fact about every candidate.

    The alias lookup used to return ``{}`` when the ``providers`` table held no gotsport
    row -- indistinguishable from "none of these teams has an alias". The caller then
    stamps a durable ``no gotsport alias`` on everything it asked about, and because no
    call was made the outcome counter is empty and the abort returns False before either
    of its arms runs. The whole population is suppressed for the re-probe window, the run
    exits 0, and no flag un-suppresses rows written today.
    """

    class _NoProvider:
        def table(self, name):
            assert name == "providers"
            return self

        def select(self, *a):
            return self

        def eq(self, *a):
            return self

        def limit(self, *a):
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    with pytest.raises(RuntimeError, match="No 'gotsport' row in providers"):
        assign.fetch_gotsport_aliases(_NoProvider(), ["t1", "t2"])


def test_the_outcome_histogram_escapes_the_provider_s_own_words(monkeypatch, capsys):
    """``unmapped code <raw>`` carries a provider value verbatim, and Rich reads square
    brackets as markup. Unescaped, a value like ``[/dim]`` raises and kills the run after
    the calls are paid for, while ``[red]x[/red]`` renders as styling and quietly falsifies
    the operator's record of what the provider actually said."""
    audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1", "wrong2"},
        outcomes={"unmapped code [/dim]": 2},
    )

    assert "unmapped code [/dim]" in re.sub(r"\s+", " ", capsys.readouterr().out)


def test_a_cached_answer_is_not_re_probed_but_still_decides(monkeypatch):
    """The case the ledger exists for. Probing it again would re-buy an answer we hold,
    and dropping it from the decisions would lose a correction already paid for."""
    snapshot, handed = audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1", "wrong2"},
        recent={"wrong1": ("mapped", "OH")},
        answers={"wrong2": "OH"},
    )

    assert handed["probed"] == ["wrong2"]
    assert snapshot["cached_answers"] == 1
    assert {d["team_id"] for d in snapshot["decisions"]} == {"wrong1", "wrong2"}


def test_a_zero_budget_probes_nothing_and_still_decides_from_the_cache(monkeypatch):
    """The budget bounds new calls, not the decisions a run can reach."""
    snapshot, handed = audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1", "wrong2"},
        recent={"wrong1": ("mapped", "OH")},
        probe_limit=0,
    )

    assert "looked_up" not in handed and "probed" not in handed
    assert [d["team_id"] for d in snapshot["decisions"]] == ["wrong1"]


def test_an_unanswered_candidate_produces_no_decision(monkeypatch):
    """Its club would supply a Tier B correction, and R5 auto-applies those. On the
    generic club names this audit selects, that is precisely the wrong thing to write."""
    snapshot, _ = audit(monkeypatch, audit_teams(), aliases={"wrong1", "wrong2"}, answers={})

    assert snapshot["decisions"] == []
    # The False arm. All-True here would make every hit-rate denominator equal its bucket.
    assert snapshot["answered"] == {"wrong1": False, "wrong2": False}
    assert snapshot["probes_answered"] == 0


def test_a_durable_non_answer_is_skipped_rather_than_dropped_silently(monkeypatch):
    """A 404 is an answer about the team, so it suppresses. It is reported, because a
    run that quietly probes nothing looks identical to one with nothing to do."""
    snapshot, handed = audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1", "wrong2"},
        # Through the constant, not a copy of its current wording: a literal only proves
        # that literal is durable, while the writer emits whatever the constant says. Reword
        # it to start with a transient prefix and every alias-less team is re-looked-up on
        # every run, forever, and never counted in ``skipped_durable``.
        recent={
            "wrong1": ("no such team (404)", None),
            "wrong2": (assign.NO_ALIAS_OUTCOME, None),
        },
    )

    assert handed.get("probed", []) == []
    assert snapshot["skipped_durable"] == 2
    assert snapshot["decisions"] == []


def test_a_cached_answer_is_not_counted_as_skipped(monkeypatch):
    """Two different facts: one team was answered usefully, the other answered with nothing
    to offer. Merging them makes the console line over-report."""
    snapshot, _ = audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1", "wrong2"},
        recent={"wrong1": ("mapped", "OH"), "wrong2": ("no such team (404)", None)},
    )

    assert (snapshot["cached_answers"], snapshot["skipped_durable"]) == (1, 1)


def test_a_transient_outcome_does_not_suppress_a_re_probe(monkeypatch):
    """A WAF block stamps every id in the batch. Treating those as answers would skip
    exactly the teams the block hit, for the whole window."""
    _, handed = audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1", "wrong2"},
        recent={"wrong1": ("http 403", None), "wrong2": ("request failed (Timeout)", None)},
    )

    assert sorted(handed["probed"]) == ["wrong1", "wrong2"]


def test_the_audit_does_not_count_undecidable_teams(monkeypatch):
    """It probes no stateless team, so any count would measure what it did not ask."""
    teams = audit_teams() + [team(team_id_master="blank", club_name="Nobody FC")]
    snapshot, _ = audit(monkeypatch, teams, aliases={"wrong1", "wrong2"})

    assert snapshot["undecidable"] == 0
    assert snapshot["undecidable_and_visible"] == []


def test_a_blocked_audit_still_emits_the_answers_it_already_held(monkeypatch, capsys):
    """A retry that also fails must not strand the cache a second time. The run flags
    itself so the caller writes the snapshot first, then stops non-zero."""
    snapshot, _ = audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1", "wrong2"},
        recent={"wrong1": ("mapped", "OH")},
        outcomes={"http 403": 5},
    )

    assert snapshot["probe_blocked"] is True
    assert [d["team_id"] for d in snapshot["decisions"]] == ["wrong1"]
    # The recovery advice, which differs by mode and was unpinned: collapsing it to the
    # sweep's text sends an audit operator to `--no-tier-a`, which the parser then refuses
    # beside `--audit-contradictions` -- a second exit 1, and the paid-for decisions unused.
    out = re.sub(r"\s+", " ", capsys.readouterr().out)
    assert "Re-run with --out to keep the decisions" in out
    assert "--no-tier-a" not in out


def test_a_blocked_sweep_is_told_to_use_the_flag_the_parser_allows_it(monkeypatch, capsys):
    """The other arm. A sweep may legitimately fall back to the free tiers, so its advice
    names `--no-tier-a` -- and an audit's must not, because that combination is refused."""
    monkeypatch.setattr(assign, "fetch_live_teams", lambda sb: audit_teams())
    monkeypatch.setattr(assign, "fetch_revert_blocks", lambda sb: set())
    monkeypatch.setattr(assign, "ranked_and_active", lambda sb, ids: [])
    monkeypatch.setattr(assign, "write_probe_log", lambda sb, rows: None)
    monkeypatch.setattr(assign, "fetch_gotsport_aliases", lambda sb, ids: {t: "p" for t in ids})
    monkeypatch.setattr(
        assign,
        "probe_associations",
        lambda i, w, sb, s: ({}, Counter({"http 403": 5})),
    )

    with pytest.raises(SystemExit):
        assign.build_snapshot(None, use_tier_a=True, workers=1)

    assert "--no-tier-a to decide" in re.sub(r"\s+", " ", capsys.readouterr().out)


def test_a_normal_run_records_its_mode(monkeypatch):
    """Every snapshot carries it, so a reader never has to infer the mode from absence."""
    monkeypatch.setattr(assign, "fetch_live_teams", lambda sb: audit_teams())
    monkeypatch.setattr(assign, "fetch_revert_blocks", lambda sb: set())
    monkeypatch.setattr(assign, "ranked_and_active", lambda sb, ids: [])

    snapshot = assign.build_snapshot(None, use_tier_a=False, workers=1)

    assert snapshot["mode"] == "normal"


class _PagedProbeLog:
    """A probe-log table that pages, so the reader's own paging is exercised.

    Every action-layer test above stubs ``fetch_recent_probes`` outright, and no capped
    live command is guaranteed to cross the 1,000-row boundary, so this is the only place
    the paging and the last-write-wins rule are actually driven.
    """

    def __init__(self, rows):
        self._rows = rows
        self.ranges = []
        self.filters = []
        self.projection = None
        self.ordered_by = (None, False)

    def table(self, name):
        assert name == assign.PROBE_LOG_TABLE
        return self

    def select(self, projection):
        self.projection = projection
        return self

    def gte(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, *, desc=False):
        # Keyword-only, matching postgrest-py: order("id", True) is a TypeError there, so
        # a double that accepted it would hide the mistake.
        self.ordered_by = (column, desc)
        return self

    def range(self, start, end):
        self.ranges.append((start, end))
        rows = sorted(self._rows, key=lambda r: r["id"], reverse=self.ordered_by[1])
        rows = [r for r in rows if all(r[c] >= v for c, v in self.filters)]
        self._page = rows[start : end + 1]
        return self

    def execute(self):
        return type("R", (), {"data": self._page})()


_ROW_ID = itertools.count(1)


def probe_row(team_id, outcome, state=None, probed_at="2026-09-01T00:00:00+00:00"):
    return {
        "id": next(_ROW_ID),
        "team_id_master": team_id,
        "outcome": outcome,
        "reported_state_code": state,
        "probed_at": probed_at,
    }


def test_the_reader_pages_and_keeps_the_globally_latest_row_per_team():
    """A team can appear on both sides of the page boundary. Ordered by id and taken
    last-write-wins, the newer row wins wherever it sits."""
    rows = [probe_row(f"t{i}", "mapped", "OH") for i in range(assign.PAGE_SIZE - 1)]
    rows.append(probe_row("straddler", "mapped", "OH"))
    rows.append(probe_row("straddler", "mapped", "WA"))
    sb = _PagedProbeLog(rows)

    latest = assign.fetch_recent_probes(sb, datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert sb.ranges[:2] == [(0, assign.PAGE_SIZE - 1), (assign.PAGE_SIZE, 2 * assign.PAGE_SIZE - 1)]
    assert latest["straddler"] == ("mapped", "WA")


def test_the_reader_drops_transient_outcomes():
    """They describe the run, not the team. Returning one would let a blocked batch
    suppress its own retry for the whole window."""
    sb = _PagedProbeLog(
        [
            probe_row("answered", "mapped", "OH"),
            probe_row("blocked", "http 403"),
            probe_row("timeout", "request failed (Timeout)"),
            probe_row("garbled", "unparseable payload"),
            probe_row("missing", "no such team (404)"),
        ]
    )

    latest = assign.fetch_recent_probes(sb, datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert sorted(latest) == ["answered", "missing"]


def test_a_later_transient_row_does_not_erase_an_earlier_answer():
    """Last-write-wins runs over qualifying rows only, so a WAF block arriving after a
    real answer must not unseat it."""
    sb = _PagedProbeLog([probe_row("t", "mapped", "OH"), probe_row("t", "http 403")])

    assert assign.fetch_recent_probes(sb, datetime(2026, 1, 1, tzinfo=timezone.utc))["t"] == (
        "mapped",
        "OH",
    )


class _PagedTeams:
    """A teams table that records what was asked for, mirroring ``_PagedProbeLog``."""

    def __init__(self, rows):
        self._rows = rows
        self.projection = None

    def table(self, name):
        assert name == "teams"
        return self

    def select(self, projection):
        self.projection = projection
        return self

    def order(self, column, *, desc=False, nullsfirst=None):
        # Keyword-only like postgrest-py's, so a positional ``desc`` fails here as it
        # would in production.
        self.ordered_by = (column, desc)
        return self

    def eq(self, column, value):
        assert (column, value) == ("is_deprecated", False)
        return self

    def range(self, start, end):
        self._page = self._rows[start : end + 1]
        return self

    def execute(self):
        return type("R", (), {"data": self._page})()


def test_both_paged_readers_order_by_their_key():
    """IMP-154: an unordered range read lets a row the scrapers update mid-read move between
    pages, and every club count is one row off."""
    teams = _PagedTeams([])
    assign.fetch_live_teams(teams)
    assert teams.ordered_by == ("team_id_master", False)

    audit_rows = QuerySpy({})
    assign.fetch_revert_blocks(audit_rows)
    assert audit_rows.orders("team_state_audit") == [("id", False, None)]


class QuerySpy:
    """A Supabase client that records the filters and the order a reader sends, per table,
    and answers from fixed rows. ``order`` carries postgrest-py's signature -- ``desc`` and
    ``nullsfirst`` keyword-only -- so a positional argument fails here as in production."""

    def __init__(self, rows_by_table):
        self.rows = rows_by_table
        self.calls = {}
        self._table = None

    def table(self, name):
        self._table = name
        self.calls.setdefault(name, [])
        return self

    def select(self, columns, **kwargs):
        return self

    def limit(self, n):
        return self

    def range(self, start, stop):
        return self

    def eq(self, column, value):
        self.calls[self._table].append(("eq", column, value))
        return self

    def in_(self, column, ids):
        self.calls[self._table].append(("in_", column, list(ids)))
        return self

    def order(self, column, *, desc=False, nullsfirst=None):
        self.calls[self._table].append(("order", column, desc, nullsfirst))
        return self

    def orders(self, table):
        return [call[1:] for call in self.calls[table] if call[0] == "order"]

    def execute(self):
        return type("R", (), {"data": list(self.rows.get(self._table, []))})()


def test_the_alias_reader_takes_approved_rows_newest_first():
    """A quarantined alias is another team's record: ``audit_polluted_gotsport_aliases``
    marks one ``pending`` and leaves it beside the approved row, and the row that wins the
    ``setdefault`` is the first the order returns. A nullable ``created_at`` sorts NULL
    ahead of every date under a bare ``desc``."""
    sb = QuerySpy(
        {
            "providers": [{"id": 7}],
            "team_alias_map": [
                {"team_id_master": "t", "provider_team_id": 200},
                {"team_id_master": "t", "provider_team_id": 100},
            ],
        }
    )

    assert assign.fetch_gotsport_aliases(sb, ["t"]) == {"t": "200"}
    calls = sb.calls["team_alias_map"]
    assert ("eq", "provider_id", 7) in calls
    assert ("eq", "review_status", "approved") in calls
    assert ("in_", "team_id_master", ["t"]) in calls
    assert sb.orders("team_alias_map") == [("created_at", True, False), ("provider_team_id", False, None)]


def test_the_team_query_still_requests_state_source():
    """Every anchor reads it, and a team dict without the key simply never anchors. So
    dropping it from the projection empties the audit's population in silence: no error,
    no failing tier, just nothing selected.

    Driven through the real call rather than by string-splitting the module's own source:
    that split takes the first ``.select("team_id_master`` in the file, so any helper added
    above ``fetch_live_teams`` would silently redirect it at a different query.
    """
    sb = _PagedTeams([{"team_id_master": "t", "state_source": "tier_a"}])

    assert assign.fetch_live_teams(sb) == [{"team_id_master": "t", "state_source": "tier_a"}]
    assert "state_source" in sb.projection


def test_an_omitted_window_falls_back_to_the_default_not_to_zero(monkeypatch):
    """A zero window suppresses nothing, so every run would re-buy the whole population.
    The flag defaults to None so an omitted one is distinguishable from an explicit one;
    the number lives here."""
    _, handed = audit(monkeypatch, audit_teams(), aliases={"wrong1", "wrong2"})
    age = datetime.now(timezone.utc) - handed["cutoff"]

    assert abs(age.days - assign.REPROBE_AFTER_DAYS) <= 1


def test_an_explicit_window_overrides_the_default(monkeypatch):
    _, handed = audit(
        monkeypatch, audit_teams(), aliases={"wrong1", "wrong2"}, reprobe_after_days=7
    )
    age = datetime.now(timezone.utc) - handed["cutoff"]

    assert abs(age.days - 7) <= 1


def test_the_hit_rate_counts_every_answer_not_only_the_wrong_ones(monkeypatch):
    """A team that answered and agreed produces no correction, only a confirm. Building the
    denominator from corrections alone makes it equal the numerator, and every bucket reads
    100%; the report reads the answered map instead."""
    teams = audit_teams()
    snapshot, _ = audit(
        monkeypatch,
        teams,
        aliases={"wrong1", "wrong2"},
        # wrong1 is contradicted; wrong2 turns out to be right where it stands.
        answers={"wrong1": "OH", "wrong2": "NV"},
    )

    assert snapshot["answered"] == {"wrong1": True, "wrong2": True}
    assert {d["team_id"]: d["action"] for d in snapshot["decisions"]} == {"wrong1": "apply", "wrong2": "confirm"}


def test_a_club_with_no_confirmed_team_anchors_nothing_and_selects_nothing():
    """This is the rule that bounds the audit's entire spend. Defaulting the anchor lookup
    instead of missing it would make every team in an unanchored club a candidate: 176,857
    teams against 1,173, measured 2026-09-01."""
    teams = [
        team(team_id_master="a", club_name="Unconfirmed FC", state_code="OH"),
        team(team_id_master="b", club_name="Unconfirmed FC", state_code="WA"),
    ]

    assert build_anchor_index(teams) == {}
    assert contradiction_candidates(teams, build_anchor_index(teams)) == []
    assert contradiction_candidates(teams, {"other fc": ("OH", 5)}) == []


def test_one_confirmed_team_is_enough_to_anchor_a_club():
    """--team on a single team is how a club with no anchor gets its first one, so the
    count of 1 has to work. Requiring two would drop 570 of 1,173 candidates today."""
    teams = [
        anchored(team_id_master="only", club_name="Solo FC", state_code="OH"),
        team(team_id_master="wrong", club_name="Solo FC", state_code="WA"),
    ]

    assert build_anchor_index(teams) == {"solo fc": ("OH", 1)}
    assert contradiction_candidates(teams, build_anchor_index(teams)) == [("wrong", 1)]


def test_a_blocked_sweep_still_exits_before_deciding(monkeypatch):
    """Normal mode keeps the original behaviour: Tier A's silence means nothing when the
    calls failed, so the run must not fall through to a Tier B auto-apply. Only the audit
    defers, and only because it has paid-for answers to protect."""
    monkeypatch.setattr(assign, "fetch_live_teams", lambda sb: audit_teams())
    monkeypatch.setattr(assign, "fetch_revert_blocks", lambda sb: set())
    monkeypatch.setattr(assign, "fetch_gotsport_aliases", lambda sb, ids: {t: "p" for t in ids})
    monkeypatch.setattr(assign, "write_probe_log", lambda sb, rows: None)
    monkeypatch.setattr(assign, "ranked_and_active", lambda sb, ids: [])
    monkeypatch.setattr(
        assign, "probe_associations", lambda ids, w, sb, st: ({}, Counter({"http 403": 9}))
    )

    with pytest.raises(SystemExit) as exc:
        assign.build_snapshot(None, use_tier_a=True, workers=1)

    assert exc.value.code == 1


def test_the_blocked_threshold_is_a_fifth_of_the_calls(monkeypatch):
    """The line between "blocked" and "quiet" decides whether a sweep writes at all."""
    assert assign.probe_is_unusable(Counter({"mapped": 79, "http 403": 21})) is True
    assert assign.probe_is_unusable(Counter({"mapped": 80, "http 403": 20})) is False


def test_a_provider_that_answers_everything_with_nothing_is_blocked_not_quiet():
    """The failure the durability rule created. A 404 and an empty payload are durable
    per-team facts, so an outage returning them for a whole batch would be filed as a
    batch of quiet teams, suppress every one of them for the full window, and exit 0.

    A 404 counts toward the ratio because a 404 for a team we hold a live alias for is a
    statement about the provider. An empty payload does not -- it is a legitimate answer
    for a small minority of teams -- so the mapped share is what catches an outage of them.
    """
    assert assign.probe_is_unusable(Counter({"no such team (404)": 1110})) is True
    assert assign.probe_is_unusable(Counter({"no association in payload": 1110})) is True
    assert assign.probe_is_unusable(Counter({"mapped": 94, "no association in payload": 6})) is False
    # A healthy 404 rate still passes: the point is the ratio, not the presence of one.
    assert assign.probe_is_unusable(Counter({"mapped": 90, "no such team (404)": 10})) is False
    # Mapped is non-zero on both sides here, so only the ratio can decide it. Without the
    # 404 in the failure set this reads as a 70% success rate and the run writes.
    assert assign.probe_is_unusable(Counter({"mapped": 70, "no such team (404)": 30})) is True
    # The exclusion the constant's comment justifies at length, pinned. Adding
    # "no association" to PROVIDER_FAILURE_OUTCOMES would make this True and abort a run
    # whose mapped share is a healthy 70%.
    assert (
        assign.probe_is_unusable(Counter({"mapped": 70, "no association in payload": 30}))
        is False
    )


def test_one_answered_call_does_not_disarm_the_mapped_share():
    """Presence is satisfied by a single answer, so the arm has to be a share. A partial
    degradation that returns an empty payload for all but one probe of a large batch is an
    outage, and reading it as "at least one team mapped, so the provider is fine" durably
    retires every other team in that batch for the full window."""
    assert (
        assign.probe_is_unusable(Counter({"mapped": 1, "no association in payload": 1123}))
        is True
    )
    assert (
        assign.probe_is_unusable(Counter({"mapped": 112, "no association in payload": 1012}))
        is True
    )


def test_a_small_batch_of_empty_answers_is_not_an_outage():
    """The regression the share arm's floor exists to prevent. A small minority of aliased
    teams legitimately carry no association, so a one-team ``--team`` run that draws one
    would print "Tier A is blocked" and exit 1 when nothing had failed -- and, because the named
    path ignores recency, re-buy the same call on every retry.

    The failure ratio stays ungated, so a one-team run that is genuinely refused still
    aborts. That distinction is what makes the floor safe here."""
    assert assign.probe_is_unusable(Counter({"no association in payload": 1})) is False
    assert assign.probe_is_unusable(Counter({"unmapped code CAN": 1})) is False
    assert assign.probe_is_unusable(Counter({"http 403": 1})) is True
    assert assign.probe_is_unusable(Counter({"request failed (Timeout)": 1})) is True
    # Just under the floor and just over it, so the floor itself is pinned rather than
    # inferred from a batch that happens to sit far from it.
    assert assign.probe_is_unusable(Counter({"no association in payload": 19})) is False
    assert assign.probe_is_unusable(Counter({"no association in payload": 20})) is True


def test_the_durable_outcomes_stay_out_of_the_retry_set():
    """The two roles must not collapse into one another. Counting a 404 as transient would
    re-buy it every run, which is the waste the ledger exists to stop; leaving it out of
    the abort is what let an outage pass for silence."""
    assert not "no such team (404)".startswith(assign.TRANSIENT_OUTCOMES)
    assert "no such team (404)".startswith(assign.PROVIDER_FAILURE_OUTCOMES)
    assert not assign.NO_ALIAS_OUTCOME.startswith(assign.TRANSIENT_OUTCOMES)


def test_the_provenance_a_tier_a_write_stamps_is_the_one_the_anchor_reads():
    """Two literals held equal by nothing was how the audit could empty itself in silence:
    the writer stamps ``state_source`` and ``build_anchor_index`` matches on it, and a
    change to either used to leave the whole suite green while no club anchored anything."""
    assert assign.TIER_A_SOURCE == assign.state_source_for("A")

    captured = {}

    class _RPC:
        def execute(self):
            return type("R", (), {"data": [{"ok": True}]})()

    class _SB:
        def rpc(self, name, params):
            captured.update(params)
            return _RPC()

    def stamped(tier):
        assert assign.apply_decision(
            _SB(),
            {
                "team_id": "t1", "pre_image": "WA", "proposed": "OH",
                "tier": tier, "confidence": 0.99,
            },
            "why",
        )
        return captured["p_source"]

    # Tier B as well as A: asserting only the A case cannot tell the real call from a
    # hardcoded "tier_a", which is the drift this test exists to catch.
    assert stamped("A") == assign.TIER_A_SOURCE
    assert stamped("B") == "tier_b"

    anchor = team(team_id_master="a", club_name="Pinned FC", state_code="OH")
    anchor["state_source"] = stamped("A")
    assert build_anchor_index([anchor]) == {"pinned fc": ("OH", 1)}


def test_a_named_team_keeps_a_decision_no_tier_a_answer_backs(monkeypatch):
    """--team wins over the audit's mapped-answer restriction. Without that bypass the
    one-off route would print "No decision" for a team whose Tier B answer is exactly what
    the operator asked for."""
    snapshot, handed = audit(
        monkeypatch, audit_teams(), aliases={"wrong1"}, answers={}, only_team="wrong1"
    )

    assert handed["looked_up"] == ["wrong1"]
    assert [(d["team_id"], d["tier"]) for d in snapshot["decisions"]] == [("wrong1", "B")]
    assert snapshot["mode"] == "normal"


def test_a_named_team_ignores_the_audit_flags_but_not_the_budget(monkeypatch):
    """The budget is about spend, so it binds on every path. Recency is about the audit's
    backlog, so it does not: a named team is asked because someone wants it asked now."""
    seeded = {
        "teams": audit_teams(),
        "aliases": {"wrong1", "wrong2"},
        "recent": {"wrong1": ("mapped", "OH")},
        "answers": {"wrong1": "OH"},
        "only_team": "wrong1",
    }

    capped, handed = audit(monkeypatch, probe_limit=0, **seeded)
    assert "looked_up" not in handed, "--probe-limit 0 still paid for a call"
    assert capped["mode"] == "normal"

    _, uncapped = audit(monkeypatch, probe_limit=None, **seeded)
    assert uncapped["looked_up"] == ["wrong1"], "a recent answer wrongly suppressed a named team"


def test_the_reader_filters_on_the_cutoff_column():
    """Without the filter the window is infinite: every probe ever logged suppresses a
    re-probe, and a registration that moved at a season boundary is never re-asked."""
    sb = _PagedProbeLog(
        [
            probe_row("old", "mapped", "OH", probed_at="2020-01-01T00:00:00+00:00"),
            probe_row("recent", "mapped", "WA", probed_at="2026-09-01T00:00:00+00:00"),
        ]
    )

    latest = assign.fetch_recent_probes(sb, datetime(2026, 6, 1, tzinfo=timezone.utc))

    assert sorted(latest) == ["recent"]
    assert sb.filters == [("probed_at", "2026-06-01T00:00:00+00:00")]


def test_the_reader_orders_ascending_by_id():
    """Last-write-wins is only meaningful against a total order. PostgREST returns pages
    in unspecified order without one, so the newest row per team would be arbitrary."""
    sb = _PagedProbeLog([probe_row("t", "mapped", "OH"), probe_row("t", "mapped", "WA")])

    assert assign.fetch_recent_probes(sb, datetime(2026, 1, 1, tzinfo=timezone.utc))["t"] == (
        "mapped",
        "WA",
    )
    assert sb.ordered_by == ("id", False)


def test_the_reader_asks_for_the_columns_it_reads():
    sb = _PagedProbeLog([probe_row("t", "mapped", "OH")])
    assign.fetch_recent_probes(sb, datetime(2026, 1, 1, tzinfo=timezone.utc))

    for column in ("team_id_master", "outcome", "reported_state_code"):
        assert column in sb.projection


# --------------------------------------------------------------------------- #
# What the run reports
# --------------------------------------------------------------------------- #


def audit_snapshot(**overrides):
    """A snapshot for the reporting tests, asymmetric in every dimension by construction.

    **No two of these defaults may be equal by accident.** A report test can only see a
    figure move if the figure it moved to holds something different: with ``probed``,
    ``aliases_found`` and ``probes_answered`` all at 2 -- which is how this fixture was
    first written -- reading the wrong snapshot key, or printing one count where another
    belongs, produces identical output and every mutation of it passes.

    That mistake has now been made five times in this file and found by mutation each time
    (equal apply/queue totals, anchor counts that skipped the boundary, a hit rate whose
    numerator and denominator coincided, an alias set covering every probed id, and these
    three counts). Keeping the defaults distinct here is what stops the sixth.
    """
    base = {
        "mode": "audit",
        "decisions": [],
        "tier_d_available": False,
        "candidates_selected": 10,
        "probed": ["a", "b", "c"],
        "aliases_found": 4,
        "probes_answered": 2,
        "cached_answers": 5,
        "skipped_durable": 0,
        "budget_applied": False,
        "anchor_counts": {},
        "answered": {},
    }
    base.update(overrides)
    return base


def test_the_decision_table_and_totals_report_the_decisions_behind_them(capsys):
    """A live run once printed "0 answered (87 from earlier runs)" -- a parenthetical larger
    than the total it qualified -- because ``summarize`` was reached by tests while almost
    none of what it prints was asserted. Every count here disagreed with its own data under
    mutation while the suite stayed green: the corrections columns could be blanked, and the
    apply and queue totals swapped, which is that same shape in a sibling line.

    Asserted as one rendered block rather than a substring per line, so a count that moves
    to the wrong column fails rather than finding its number somewhere else on the page.
    """
    # Three applies against two queues, deliberately unequal: with 2 and 2 the totals can be
    # swapped without changing a character of the output.
    decisions = [
        {"team_id": "f1", "pre_image": None, "proposed": "OH", "tier": "B", "action": "apply"},
        {"team_id": "c1", "pre_image": "WA", "proposed": "OH", "tier": "A", "action": "apply"},
        {"team_id": "c2", "pre_image": "NV", "proposed": "OH", "tier": "A", "action": "queue"},
        {"team_id": "c3", "pre_image": "NV", "proposed": "OH", "tier": "E", "action": "queue"},
        {"team_id": "c4", "pre_image": "NV", "proposed": "OH", "tier": "B", "action": "apply"},
    ]
    assign.summarize(
        {
            "decisions": decisions, "tier_d_available": False, "undecidable": 7,
            "undecidable_and_visible": ["vis1"],
        }
    )
    out = re.sub(r"\s+", " ", capsys.readouterr().out)

    # Tier A: no fills, one correction applied, one queued. Tier B: a fill and a correction.
    assert "│ A │ 0 │ 0 │ 1 │ 1 │" in out
    assert "│ B │ 1 │ 0 │ 1 │ 0 │" in out
    assert "│ E │ 0 │ 0 │ 0 │ 1 │" in out
    # Tiers that decided nothing are omitted entirely, so the table stays readable.
    assert "│ C │" not in out
    assert "3 to apply, 2 to review, across 1 fills and 4 corrections." in out
    assert "7 teams have no state and no tier that can decide them" in out
    assert "1 of them are ranked and Active" in out
    assert "vis1" in out


def test_the_audit_report_names_the_split_between_applied_and_queued(capsys):
    """The line an operator reads to decide whether a snapshot is safe to apply unattended.
    Reporting every correction as auto-applied survived the suite."""
    assign.summarize(
        audit_snapshot(
            decisions=[
                {"team_id": "a", "pre_image": "WA", "proposed": "OH", "tier": "A", "action": "apply"},
                {"team_id": "b", "pre_image": "WA", "proposed": "OH", "tier": "A", "action": "queue"},
                {"team_id": "c", "pre_image": "WA", "proposed": "OH", "tier": "A", "action": "queue"},
            ]
        )
    )
    out = re.sub(r"\s+", " ", capsys.readouterr().out)

    assert "3 corrections, 1 auto-applied and 2 queued for review." in out


def test_a_run_that_skipped_durable_non_answers_says_so(capsys):
    """Its stated purpose is that a run which quietly probes nothing must not look like a
    run with nothing to do. Deleting the line left the suite green."""
    assign.summarize(audit_snapshot(skipped_durable=13))
    out = re.sub(r"\s+", " ", capsys.readouterr().out)

    assert "13 skipped: answered before, but with no state to offer." in out


def test_the_audit_selection_line_reports_three_different_figures(capsys):
    """Selected, probed and answered are different numbers, and printing one of them three
    times is indistinguishable from a run that behaved that way.

    Every figure here is distinct, including the two this test originally set equal: with
    ``probed`` and ``aliases_found`` both at 2, the line could read either from the wrong
    snapshot key and still render identically. Not all three came from the fixture -- the
    alias count is deliberately below the probed count, which is the real shape (1,124 of
    1,173 candidates carry a GotSport id).
    """
    assign.summarize(
        audit_snapshot(
            candidates_selected=10, probed=["a", "b", "c"], aliases_found=2,
            probes_answered=4, cached_answers=3,
        )
    )
    out = re.sub(r"\s+", " ", capsys.readouterr().out)

    assert (
        "10 contradict a confirmed club-mate, 3 probed, 2 had a GotSport id, "
        "7 answered (3 of them from earlier runs)." in out
    )


def test_the_answered_total_includes_the_answers_the_cache_supplied(capsys):
    """A live run printed "0 answered (87 from earlier runs)" -- a parenthetical larger
    than the total it qualified, because the count read this run's probes alone."""
    assign.summarize(audit_snapshot(probes_answered=0, cached_answers=87))

    line = re.sub(r"\s+", " ", capsys.readouterr().out)
    assert "87 answered (87 of them from earlier runs)" in line


def test_the_capped_caveat_follows_the_budget_not_the_probe_count(capsys):
    """An uncapped run that reused cached answers has a short probe list too. Reading that
    as "capped" mislabels the very run that finished the backlog."""
    assign.summarize(audit_snapshot(budget_applied=False, probed=["a"], candidates_selected=99))
    uncapped = re.sub(r"\s+", " ", capsys.readouterr().out)
    assert "only comparable on an uncapped one" not in uncapped

    # An empty probe list and a full population: the shape that got no warning before.
    assign.summarize(audit_snapshot(budget_applied=True, probed=[], candidates_selected=99))
    capped = re.sub(r"\s+", " ", capsys.readouterr().out)
    assert "only comparable on an uncapped one" in capped


def test_the_hit_rate_is_reported_per_anchor_bucket(capsys):
    """The comparison the ordering exists to enable. Denominator is teams that answered,
    not teams selected: diluting by unanswered teams confounds the two buckets.

    Two asymmetries, both load-bearing, both added after a mutation walked through the
    fixture that lacked them:

    ``m2`` carries exactly two anchors, on the boundary ``_anchor_bucket`` splits at. With
    only 3 and 1 in the fixture, moving the split to ``>= 3`` changed no output at all.

    ``agree`` answered and produced no decision -- the provider confirmed the stored state.
    It belongs in the denominator and not the numerator, which is the only reason those are
    two numbers. While every answered team also disagreed, the rate was 100% by
    construction, and hardcoding it to "100.0%", or printing the denominator as the
    numerator, changed nothing the suite could see.

    ``m2`` is queued rather than applied, and still counts. R8 and R17 queue a decision
    precisely because the tool refuses to call the provider's disagreement an established
    correction -- so the label is "disagreed", and counting only the applies would understate
    the tier against itself.
    """
    decisions = [
        {"team_id": "s1", "action": "apply", "pre_image": "WA", "tier": "A"},
        {"team_id": "m1", "action": "apply", "pre_image": "WA", "tier": "A"},
        {"team_id": "m2", "action": "queue", "pre_image": "WA", "tier": "A"},
    ]
    assign.summarize(
        audit_snapshot(
            decisions=decisions,
            anchor_counts={"m1": 3, "m2": 2, "agree": 2, "s1": 1, "s2": 1},
            answered={"m1": True, "m2": True, "agree": True, "s1": True, "s2": False},
        )
    )

    out = re.sub(r"\s+", " ", capsys.readouterr().out)
    # 2 of 3, not 2 of 2: ``agree`` answered and is counted, but disagreed with nothing.
    assert "anchored by 2 or more: the provider disagreed on 2 of 3 answered (66.7%)" in out
    assert "anchored by exactly 1: the provider disagreed on 1 of 1 answered (100.0%)" in out


def test_the_report_survives_a_run_that_answered_nothing(capsys):
    assign.summarize(audit_snapshot(anchor_counts={"a": 2}, answered={"a": False}))

    assert "no answers" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #


def run_cli(monkeypatch, capsys, *argv, credentials=None):
    """Drive the real `main()` argv validation, which runs before any credential check.

    The credentials are cleared here, for every caller, rather than left to the ambient
    environment. These tests assert that a guard refuses; if one of them ever regresses,
    `main()` runs on -- and on a machine carrying the documented root ``.env`` that means a
    real service-role client and a full production sweep, one paid GotSport call per
    disputed-or-stateless team, before ``pytest.raises`` gets to fail. Cleared, the worst a
    regression costs is the credential error.

    ``credentials`` sets them instead, for the two guards that sit behind that check.
    """
    url, key = credentials or (None, None)
    monkeypatch.setattr(assign, "SUPABASE_URL", url)
    monkeypatch.setattr(assign, "SUPABASE_KEY", key)
    monkeypatch.setattr(assign, "create_client", lambda u, k: None)
    monkeypatch.setattr(sys, "argv", ["assign_team_states.py", *argv])
    with pytest.raises(SystemExit) as exc:
        assign.main()
    return exc.value.code, re.sub(r"\s+", " ", capsys.readouterr().out)


@pytest.mark.parametrize(
    "argv,expected",
    [
        (("--audit-contradictions", "--no-tier-a"), "nothing to ask"),
        (("--probe-limit", "10"), "only bounds --audit-contradictions"),
        (("--reprobe-after-days", "30"), "only applies to --audit-contradictions"),
        (("--audit-contradictions", "--probe-limit", "-1"), "cannot be negative"),
        (("--audit-contradictions", "--reprobe-after-days", "0"), "must be at least 1"),
        (("--audit-contradictions", "--reprobe-after-days", "-5"), "must be at least 1"),
        (("--anchor-clubs", "--no-tier-a"), "nothing to ask"),
        (("--probe-unclubbed", "--no-tier-a"), "nothing to ask"),
        (("--anchor-clubs", "--audit-contradictions"), "one population"),
        (("--anchor-clubs", "--probe-unclubbed"), "one population"),
    ],
)
def test_a_meaningless_flag_combination_is_refused_by_name(monkeypatch, capsys, argv, expected):
    """Each guard runs before the credential check, so these assert on the message rather
    than the exit code -- CI sets no keys, and every argv exits 1 there regardless."""
    code, out = run_cli(monkeypatch, capsys, *argv)

    assert code == 1
    assert expected in out


def test_an_ordinary_invocation_passes_validation(monkeypatch, capsys):
    """The inverse. Without it, a guard that rejected everything would look correct.

    ``run_cli`` clears the credentials, so this reaches the credential guard and stops.
    """
    code, out = run_cli(monkeypatch, capsys, "--no-tier-a")

    assert code == 1
    assert "Missing SUPABASE_URL" in out


@pytest.mark.parametrize(
    "argv,expected",
    [
        (("--set", "OH"), "--set needs --team"),
        (("--execute",), "--execute needs --snapshot"),
    ],
)
def test_a_guard_behind_the_credential_check_still_refuses_by_name(
    monkeypatch, capsys, argv, expected
):
    """The two guards the argv block above cannot reach, because they sit after the
    credential check. Enumerated cases cannot fail for a case they omit, and deleting
    either of these passed the whole suite.

    The only tests that hand ``run_cli`` credentials, and safe because both guards refuse
    before anything is fetched -- ``create_client`` is stubbed to ``None``, so a regression
    reaching the database would raise rather than spend.
    """
    code, out = run_cli(
        monkeypatch, capsys, *argv, credentials=("https://example.test", "key")
    )

    assert code == 1
    assert expected in out


def test_a_blocked_audit_writes_its_snapshot_before_it_exits(tmp_path, monkeypatch, capsys):
    """The entire reason the audit defers its abort. Exiting first would strand the
    answers earlier runs already paid for, on every retry."""
    out_file = tmp_path / "audit.json"
    monkeypatch.setattr(assign, "SUPABASE_URL", "https://example.test")
    monkeypatch.setattr(assign, "SUPABASE_KEY", "key")
    monkeypatch.setattr(assign, "create_client", lambda url, key: None)
    monkeypatch.setattr(
        assign,
        "build_snapshot",
        lambda *a, **k: {
            "created_at": "2026-09-01T00:00:00+00:00", "mode": "audit", "decisions": [],
            "tier_d_available": False, "undecidable": 0, "undecidable_and_visible": [],
            "candidates_selected": 1, "probed": [], "aliases_found": 0, "probes_answered": 0,
            "cached_answers": 1, "skipped_durable": 0, "budget_applied": False,
            "anchor_counts": {}, "answered": {}, "probe_blocked": True,
        },
    )
    monkeypatch.setattr(sys, "argv", ["x", "--audit-contradictions", "--out", str(out_file)])

    with pytest.raises(SystemExit) as exc:
        assign.main()

    assert exc.value.code == 1
    assert out_file.exists(), "the snapshot must be on disk before the run stops"


def test_a_blocked_probe_stops_a_named_team_run_even_in_audit_mode(monkeypatch):
    """--team has no cache to protect, so it keeps the sweep's immediate abort. Deferring
    here would let a silenced Tier A fall through to a Tier B auto-apply on exactly the
    uniformly-mislabelled club the one-off route exists for."""
    monkeypatch.setattr(assign, "fetch_live_teams", lambda sb: audit_teams())
    monkeypatch.setattr(assign, "fetch_revert_blocks", lambda sb: set())
    monkeypatch.setattr(assign, "fetch_recent_probes", lambda sb, cutoff: {})
    monkeypatch.setattr(assign, "fetch_gotsport_aliases", lambda sb, ids: {t: "p" for t in ids})
    monkeypatch.setattr(assign, "write_probe_log", lambda sb, rows: None)
    monkeypatch.setattr(assign, "ranked_and_active", lambda sb, ids: [])
    monkeypatch.setattr(
        assign, "probe_associations", lambda i, w, sb, s: ({}, Counter({"http 403": 4}))
    )

    with pytest.raises(SystemExit) as exc:
        assign.build_snapshot(
            None, use_tier_a=True, workers=1, only_team="wrong1", audit_contradictions=True
        )

    assert exc.value.code == 1


def test_the_run_records_whether_the_budget_actually_bit(monkeypatch):
    """A cached or durably-answered team shortens the probe list too, so the shortening
    cannot stand in for the budget. Reading it that way labels the uncapped run that
    finishes the backlog as capped, and its bucket rates as incomparable."""
    teams = audit_teams()
    cached_one = {"wrong1": ("mapped", "OH")}

    uncapped, _ = audit(monkeypatch, teams, aliases={"wrong1", "wrong2"}, recent=cached_one)
    assert uncapped["budget_applied"] is False, "a cache hit is not a budget"

    capped, _ = audit(monkeypatch, teams, aliases={"wrong1", "wrong2"}, probe_limit=1)
    assert capped["budget_applied"] is True


def test_answered_covers_every_candidate_not_only_the_ones_probed(monkeypatch):
    """A cached team is a candidate that answered without being probed. Building the map
    over the probe list drops it, and the bucket it belongs to loses its denominator."""
    snapshot, _ = audit(
        monkeypatch,
        audit_teams(),
        aliases={"wrong1", "wrong2"},
        recent={"wrong1": ("mapped", "OH")},
        answers={"wrong2": "OH"},
    )

    assert snapshot["answered"] == {"wrong1": True, "wrong2": True}
    assert snapshot["probed"] == ["wrong2"]


# --------------------------------------------------------------------------- #
# Anchoring clubs: one paid call per club the provider has never confirmed
# --------------------------------------------------------------------------- #


def anchor_pass(teams, recent=None, aliases=None):
    """Drive the real grouping and pick, every team aliased unless told otherwise, merging
    the two reasons lists the way ``build_snapshot`` does."""
    aliased = {t["team_id_master"] for t in teams} if aliases is None else set(aliases)
    clubs, passed_over = assign.anchorable_clubs(teams)
    selected, skipped = assign.anchor_candidates(clubs, build_club_index(teams), recent or {}, aliased)
    passed_over.update(skipped)
    return selected, passed_over


def unanchored_club(name="Quiet FC", state="WA", size=3):
    return [
        team(team_id_master=f"{name.split()[0].lower()}{i}", club_name=name, state_code=state)
        for i in range(size)
    ]


def test_one_team_is_selected_per_club_the_provider_has_never_confirmed():
    teams = unanchored_club() + [
        anchored(team_id_master="anchor1", club_name="Anchored FC", state_code="OH"),
        team(team_id_master="anchor2", club_name="Anchored FC", state_code="OH"),
    ]
    selected, skipped = anchor_pass(teams)

    assert [team_id for team_id, _ in selected] == ["quiet0"]
    assert skipped["anchored"] == 1


def test_a_club_with_one_team_or_no_name_cannot_be_anchored():
    teams = [
        team(team_id_master="solo", club_name="Solo FC", state_code="OH"),
        team(team_id_master="ph0", club_name="No Club Selection", state_code="CA"),
        team(team_id_master="ph1", club_name="No Club Selection", state_code="CA"),
        team(team_id_master="blank0", club_name="", state_code="CA"),
        team(team_id_master="blank1", club_name="", state_code="CA"),
    ]
    selected, skipped = anchor_pass(teams)

    assert selected == []
    assert skipped["single team"] == 1


def test_the_club_modal_state_team_is_preferred_then_the_lowest_id():
    teams = [
        team(team_id_master="a", club_name="Split FC", state_code="NV"),
        team(team_id_master="c", club_name="Split FC", state_code="WA"),
        team(team_id_master="b", club_name="Split FC", state_code="WA"),
    ]
    selected, _ = anchor_pass(teams)

    assert [team_id for team_id, _ in selected] == ["b"]


def test_a_team_answered_without_a_state_is_passed_over_for_a_club_mate():
    selected, passed_over = anchor_pass(
        unanchored_club(), recent={"quiet0": ("no association in payload", None)}
    )

    assert [team_id for team_id, _ in selected] == ["quiet1"]
    assert passed_over["answered without a state; a club-mate asked instead"] == 1


def test_three_non_answers_retire_the_club():
    recent = {f"quiet{i}": ("no such team (404)", None) for i in range(3)}
    selected, skipped = anchor_pass(unanchored_club(size=4), recent=recent)

    assert selected == []
    assert skipped["unanswerable"] == 1


def test_an_answer_already_bought_is_selected_ahead_of_a_paid_call():
    """``probe_list`` drops it from the paid list and the cache seeds its answer, so the
    club is anchored for free -- but only if the selector picks that team."""
    selected, _ = anchor_pass(unanchored_club(), recent={"quiet2": ("mapped", "WA")})

    assert [team_id for team_id, _ in selected] == ["quiet2"]


def test_a_team_without_a_gotsport_id_is_never_selected():
    selected, skipped = anchor_pass(unanchored_club(), aliases={"quiet1", "quiet2"})
    assert [team_id for team_id, _ in selected] == ["quiet1"]

    selected, skipped = anchor_pass(unanchored_club(), aliases=set())
    assert selected == []
    assert skipped["no alias"] == 1


def test_bigger_clubs_are_anchored_first():
    """Names chosen so that alphabetical order opposes size: a sort that lost its size term
    would put Alpha first and still look plausible."""
    teams = (
        unanchored_club("Alpha FC", size=2)
        + unanchored_club("Middle FC", size=3)
        + unanchored_club("Zeta FC", size=5)
    )
    selected, _ = anchor_pass(teams)

    assert selected == [("zeta0", 5), ("middle0", 3), ("alpha0", 2)]


def test_a_stateless_club_mate_neither_counts_nor_gets_picked():
    """One stated team plus two blanks is a single-team club: the blanks cannot anchor
    anything and must not inflate the club's size in the budget ordering."""
    teams = [
        team(team_id_master="stated", club_name="Half FC", state_code="OH"),
        team(team_id_master="blank1", club_name="Half FC", state_code=None),
        team(team_id_master="blank2", club_name="Half FC", state_code=None),
    ]
    selected, passed_over = anchor_pass(teams)

    assert selected == []
    assert passed_over["single team"] == 1


def test_a_stored_province_is_never_asked_about():
    """No tier corrects a province and no confirm can stamp one, so the call buys nothing --
    the exclusion the audit already carries."""
    ontario = [
        team(team_id_master=f"on{i}", club_name="Oakville SC", state_code="ON") for i in range(3)
    ]
    selected, _ = anchor_pass(ontario + unanchored_club())

    assert [team_id for team_id, _ in selected] == ["quiet0"]
    assert assign.unclubbed_candidates(
        [team(team_id_master="lone", club_name="", state_code="QC")]
    ) == []


def test_a_no_alias_row_is_not_an_answer_and_its_team_is_not_the_pick():
    """A ``no gotsport alias`` ledger row records that no call was made: three of them must
    not retire a club whose other members would answer, and the team it names must not be
    the pick either, since ``probe_list`` would drop it and the club would be reported as
    answered without a call ever going out."""
    recent = {f"quiet{i}": (assign.NO_ALIAS_OUTCOME, None) for i in range(3)}
    selected, passed_over = anchor_pass(unanchored_club(size=4), recent=recent)

    assert [team_id for team_id, _ in selected] == ["quiet3"]
    assert passed_over["unanswerable"] == 0
    assert passed_over["answered without a state; a club-mate asked instead"] == 0


def test_a_cached_unset_default_answer_anchors_nothing():
    """A mapped ``AL`` in the ledger is the provider's unset default; ``decide`` throws it
    away as soon as a local reading disputes it and the selector has none, so treating it
    as a bought anchor would leave the club unanchored forever and re-buy the same answer
    after the window."""
    selected, passed_over = anchor_pass(unanchored_club(), recent={"quiet2": ("mapped", "AL")})

    assert [team_id for team_id, _ in selected] == ["quiet0"]
    assert passed_over["answered without a state; a club-mate asked instead"] == 1


def test_a_club_is_passed_over_for_one_reason_only():
    """The pass-over counter fires only when a club-mate was actually asked; a club whose
    only aliased member answered silently is exhausted, not "no alias" and not both."""
    _, passed_over = anchor_pass(
        unanchored_club(), recent={"quiet0": ("no association in payload", None)}, aliases={"quiet0"}
    )

    assert passed_over["unanswerable"] == 1
    assert passed_over["no alias"] == 0
    assert passed_over["answered without a state; a club-mate asked instead"] == 0


def test_a_two_team_club_is_retired_once_both_members_answer_silently():
    """The cap is three silent answers, which a two-team club can never reach. Once every
    aliased member is in the ledger the club is exhausted; calling it "no alias" instead sends the
    operator to backfill aliases that exist and re-buys both calls after the window."""
    silent = ("no association in payload", None)
    selected, passed_over = anchor_pass(
        unanchored_club(size=2), recent={"quiet0": silent, "quiet1": silent}
    )

    assert selected == []
    assert passed_over["unanswerable"] == 1
    assert passed_over["no alias"] == 0

    _, passed_over = anchor_pass(unanchored_club(size=2), aliases=set())
    assert passed_over["no alias"] == 1


def test_a_mixed_border_club_is_one_club_to_both_passes():
    """One US team and one Canadian team: the province member is not askable, so the club
    is a single-team club to the anchor pass -- and therefore the US team is the unclubbed
    pass's business, not nobody's."""
    teams = [
        team(team_id_master="us", club_name="Border FC", state_code="WA"),
        team(team_id_master="ca", club_name="Border FC", state_code="ON"),
    ]
    selected, passed_over = anchor_pass(teams)

    assert selected == [] and passed_over["single team"] == 1
    assert assign.unclubbed_candidates(teams) == [("us", 1)]


def test_an_operator_set_team_is_never_bought_by_any_selector():
    """``--set`` outranks every automated write, so a call about that team could change
    nothing; the anchor pass picks a club-mate, the unclubbed pass leaves it out, and the
    audit does not count it as a dissenter."""
    by_hand = team(team_id_master="byhand", club_name="Quiet FC", state_code="WA", state_source="operator")
    selected, _ = anchor_pass([by_hand] + unanchored_club())
    assert [team_id for team_id, _ in selected] == ["quiet0"]

    lone = team(team_id_master="lone", club_name="", state_code="WA", state_source="operator")
    assert assign.unclubbed_candidates([lone]) == []

    dissenters = [
        anchored(team_id_master="a1", club_name="Set FC", state_code="OH"),
        team(team_id_master="byhand2", club_name="Set FC", state_code="WA", state_source="operator"),
        team(team_id_master="plain", club_name="Set FC", state_code="WA"),
    ]
    audited = contradiction_candidates(dissenters, build_anchor_index(dissenters))
    assert [team_id for team_id, _ in audited] == ["plain"]


def test_the_alias_pool_is_exactly_the_anchorable_clubs_members():
    """One grouping feeds both the lookup and the pick, so a solo club or an anchored club
    never reaches the alias lookup at all."""
    teams = unanchored_club() + [
        team(team_id_master="solo", club_name="Solo FC", state_code="OH"),
        anchored(team_id_master="anchor1", club_name="Anchored FC", state_code="OH"),
        team(team_id_master="mate", club_name="Anchored FC", state_code="OH"),
    ]
    clubs, _ = assign.anchorable_clubs(teams)

    assert sorted(assign.anchor_pool(clubs)) == ["quiet0", "quiet1", "quiet2"]


def test_the_unclubbed_pass_takes_lone_teams_and_teams_with_no_club():
    teams = [
        team(team_id_master="solo", club_name="Solo FC", state_code="OH"),
        team(team_id_master="ph0", club_name="No Club Selection", state_code="CA"),
        team(team_id_master="blank0", club_name="", state_code="CA"),
        team(team_id_master="pair0", club_name="Pair FC", state_code="CA"),
        team(team_id_master="pair1", club_name="Pair FC", state_code="CA"),
    ]
    selected = assign.unclubbed_candidates(teams)

    assert selected == [("blank0", 1), ("ph0", 1), ("solo", 1)]


def test_the_unclubbed_pass_skips_a_blank_state_and_a_confirmed_team():
    """The alias filter belongs to the caller; the population itself leaves out a team with
    no state to check and one the provider already vouched for."""
    teams = [
        team(team_id_master="stateless", club_name="", state_code=None),
        anchored(team_id_master="vouched", club_name="", state_code="CA"),
        team(team_id_master="ok", club_name="", state_code="CA"),
    ]

    assert assign.unclubbed_candidates(teams) == [("ok", 1)]


def confirms(team_row, answer, clubs=None, candidates=None, reverts=frozenset()):
    """Drive the real ``confirm_decisions`` for one candidate with one bought answer."""
    team_id = team_row["team_id_master"]
    return assign.confirm_decisions(
        [team_row],
        candidates if candidates is not None else {team_id},
        {team_id: answer} if answer else {},
        clubs or {},
        {},
        set(reverts),
    )


def test_an_agreeing_answer_becomes_a_confirm_that_records_provenance_only():
    (decision,) = confirms(team(team_id_master="q", club_name="Quiet FC", state_code="WA"), "WA")

    assert decision["action"] == "confirm"
    assert decision["tier"] == "A"
    assert (decision["pre_image"], decision["proposed"]) == ("WA", "WA")
    assert decision["confidence"] == 0.95
    assert decision["reason"] == "provider confirms WA"


def test_a_team_the_provider_already_confirmed_is_not_confirmed_again():
    assert confirms(anchored(team_id_master="q", club_name="Quiet FC", state_code="WA"), "WA") == []


def test_an_operator_set_value_is_not_overwritten_by_a_confirm():
    """``--set`` stamps ``operator`` at confidence 1.0; a confirm would replace it with
    ``tier_a`` at 0.95 and drop the team out of every reader that trusts the hand mark."""
    by_hand = team(team_id_master="q", club_name="Quiet FC", state_code="WA", state_source="operator")

    assert confirms(by_hand, "WA") == []


def test_a_value_the_operator_reverted_away_from_is_not_reconfirmed():
    """R17 for confirms: a revert restores the earlier provenance so the automated writer
    stops re-asserting the value it undid, and the ledger answer is reused for free, so
    without this the next anchor pass would re-confirm the club and re-arm the audit."""
    quiet = team(team_id_master="q", club_name="Quiet FC", state_code="WA")

    assert confirms(quiet, "WA", reverts={("q", "WA")}) == []


def test_a_disagreeing_or_missing_answer_confirms_nothing():
    quiet = team(team_id_master="q", club_name="Quiet FC", state_code="WA")

    assert confirms(quiet, "OH") == []
    assert confirms(quiet, None) == []


def test_an_answer_for_a_team_outside_the_candidates_confirms_nothing():
    quiet = team(team_id_master="q", club_name="Quiet FC", state_code="WA")

    assert confirms(quiet, "WA", candidates=set()) == []


def test_the_unset_default_confirms_alabama_only_when_nothing_local_disputes_it():
    """R8b, applied to the confirm as it is to the correction: a disputed ``AL`` is the
    absence of an answer, and an undisputed one still says Alabama."""
    stored_al = team(team_id_master="q", club_name="Cold Spring FC", state_code="AL")
    disputed = {"cold spring fc": Counter({"NY": 5, "AL": 1})}
    agreed = {"cold spring fc": Counter({"AL": 5})}

    assert confirms(stored_al, "AL", clubs=disputed) == []
    assert [d["action"] for d in confirms(stored_al, "AL", clubs=agreed)] == ["confirm"]


def quiet_unanchored():
    """Five WA teams of one club and no confirmed member: nothing local disputes them
    and no audit can reach them, which is the population the anchor pass exists for."""
    return unanchored_club(size=5)


def verify(monkeypatch, teams, aliases, mode="anchor_clubs", **kwargs):
    """The audit harness, pointed at one of the two new population flags."""
    return audit(monkeypatch, teams, aliases, mode=mode, **kwargs)


def test_the_anchor_pass_asks_one_team_of_the_quiet_club_and_nothing_else(monkeypatch):
    teams = quiet_unanchored() + audit_teams()
    snapshot, handed = verify(monkeypatch, teams, aliases={t["team_id_master"] for t in teams})

    assert handed["probed"] == ["quiet0"]
    assert snapshot["mode"] == "anchor"
    assert snapshot["candidates_selected"] == 1
    # The anchored club is not even looked up: its dissenters are the audit's business.
    looked_up = {t for lookup in handed["lookups"] for t in lookup}
    assert "anchor1" not in looked_up and "wrong1" not in looked_up
    assert snapshot["decisions"] == []
    # Written by the run, not hand-built for the report: the one anchored club is the
    # reason the pass had a club to pass over.
    assert snapshot["passed_over"] == {"anchored": 1}
    assert snapshot["club_sizes"] == {"quiet0": 5}
    # The map from the population lookup is what the probe used, so the paid stage did
    # not buy the same lookup twice.
    assert len(handed["lookups"]) == 1


def test_an_agreeing_anchor_answer_lands_in_the_snapshot_as_a_confirm(monkeypatch):
    teams = quiet_unanchored()
    ids = {t["team_id_master"] for t in teams}
    snapshot, handed = verify(monkeypatch, teams, aliases=ids, answers={"quiet0": "WA"})

    (decision,) = snapshot["decisions"]
    assert (decision["team_id"], decision["action"], decision["proposed"]) == ("quiet0", "confirm", "WA")
    # The alias lookup covers the whole club, so a first pick without a GotSport id is
    # passed over for a club-mate that has one rather than retiring the club.
    assert set(handed["lookups"][0]) == ids


def test_a_disagreeing_anchor_answer_corrects_that_team_and_leaves_the_club_to_the_audit(monkeypatch):
    teams = quiet_unanchored()
    snapshot, _ = verify(
        monkeypatch, teams, aliases={t["team_id_master"] for t in teams}, answers={"quiet0": "OH"}
    )

    (decision,) = snapshot["decisions"]
    assert (decision["team_id"], decision["tier"], decision["action"]) == ("quiet0", "A", "apply")
    assert (decision["pre_image"], decision["proposed"]) == ("WA", "OH")


def test_a_blocked_anchor_pass_keeps_the_answers_it_held_and_flags_itself(monkeypatch, capsys):
    teams = quiet_unanchored() + [
        team(team_id_master=f"loud{i}", club_name="Loud FC", state_code="NV") for i in range(3)
    ]
    snapshot, handed = verify(
        monkeypatch,
        teams,
        aliases={t["team_id_master"] for t in teams},
        recent={"quiet0": ("mapped", "WA")},
        outcomes={"http 403": 5},
    )

    assert handed["probed"] == ["loud0"]
    assert snapshot["probe_blocked"] is True
    assert [(d["team_id"], d["action"]) for d in snapshot["decisions"]] == [("quiet0", "confirm")]
    out = re.sub(r"\s+", " ", capsys.readouterr().out)
    assert "Re-run with --out to keep the decisions" in out
    assert "--no-tier-a" not in out


def test_the_unclubbed_pass_probes_the_lone_teams_only(monkeypatch):
    teams = [
        team(team_id_master="solo", club_name="Solo FC", state_code="OH"),
        team(team_id_master="blank0", club_name="", state_code="CA"),
        team(team_id_master="pair0", club_name="Pair FC", state_code="CA"),
        team(team_id_master="pair1", club_name="Pair FC", state_code="CA"),
    ]
    snapshot, handed = verify(
        monkeypatch, teams, aliases={t["team_id_master"] for t in teams}, mode="probe_unclubbed"
    )

    assert handed["probed"] == ["blank0", "solo"]
    assert snapshot["mode"] == "unclubbed"
    assert "club_sizes" not in snapshot
    assert "anchor_counts" not in snapshot


def test_the_unclubbed_pass_reports_the_teams_it_could_not_ask(monkeypatch):
    """The anchor pass counts a club it cannot ask under "no alias"; the unclubbed pass
    must count its teams the same way rather than dropping them silently."""
    teams = [
        team(team_id_master="blank0", club_name="", state_code="CA"),
        team(team_id_master="blank1", club_name="", state_code="CA"),
        team(team_id_master="blank2", club_name="", state_code="CA"),
    ]
    snapshot, handed = verify(monkeypatch, teams, aliases={"blank1"}, mode="probe_unclubbed")

    assert handed["probed"] == ["blank1"]
    assert snapshot["passed_over"] == {"no alias": 2}


def test_a_zero_budget_selects_the_population_but_buys_nothing(monkeypatch):
    teams = quiet_unanchored()
    snapshot, handed = verify(
        monkeypatch, teams, aliases={t["team_id_master"] for t in teams}, probe_limit=0
    )

    assert "probed" not in handed
    assert snapshot["candidates_selected"] == 1
    assert snapshot["budget_applied"] is True
    # The alias figure is the population's, not the probe's: a zero-budget rehearsal
    # would otherwise report "0 had a GotSport id" for a fully aliased club.
    assert snapshot["aliases_found"] == 5


def test_a_disputed_unset_default_answer_cannot_authorize_a_club_correction(monkeypatch):
    """The provider's ``AL`` for a team whose club reads otherwise is the absence of an
    answer, and decide() drops it -- but the team still counts as answered for the write
    scope. On a club split two and two the club count then told the anchor to swap sides,
    the exact shape (IMP-161) the record was bought to settle. Only the record's own
    decisions apply in these modes; anything else waits for a person."""
    teams = [
        team(team_id_master="ca1", club_name="RSL-AZ Yuma", state_code="CA"),
        team(team_id_master="ca2", club_name="RSL-AZ Yuma", state_code="CA"),
        team(team_id_master="tx1", club_name="RSL-AZ Yuma", state_code="TX"),
        team(team_id_master="tx2", club_name="RSL-AZ Yuma", state_code="TX"),
    ]
    snapshot, handed = verify(
        monkeypatch, teams, aliases={t["team_id_master"] for t in teams}, answers={"ca1": "AL"}
    )

    assert handed["probed"] == ["ca1"]
    (decision,) = snapshot["decisions"]
    assert (decision["team_id"], decision["tier"], decision["action"]) == ("ca1", "B", "queue")
    assert decision["reason"].endswith("provider gave no usable answer")


def test_a_named_team_ignores_the_anchor_flags_and_reports_as_a_normal_run(monkeypatch):
    """``--team`` wins over either population flag, as it does over the audit's: the run
    probes the one team, keeps every tier's answer, and stops on a blocked probe."""
    teams = quiet_unanchored() + [team(team_id_master="named", club_name="Named FC", state_code="OH")]
    for flag in ("anchor_clubs", "probe_unclubbed"):
        snapshot, handed = verify(
            monkeypatch,
            teams,
            aliases={t["team_id_master"] for t in teams},
            mode=flag,
            only_team="named",
        )

        assert handed["probed"] == ["named"]
        assert snapshot["mode"] == "normal"
        assert "candidates_selected" not in snapshot


def test_a_selected_team_answered_before_without_a_state_is_reported_as_skipped(monkeypatch):
    """``skipped_durable`` from the run itself: the lone unclubbed team answered on an
    earlier run with no association, so it is selected, not re-bought, and counted."""
    teams = [team(team_id_master="lone", club_name="", state_code="CA")]
    snapshot, handed = verify(
        monkeypatch,
        teams,
        aliases={"lone"},
        mode="probe_unclubbed",
        recent={"lone": ("no association in payload", None)},
    )

    assert "probed" not in handed
    assert snapshot["candidates_selected"] == 1
    assert snapshot["skipped_durable"] == 1


def confirm_of(team_id, state):
    return {
        "team_id": team_id, "pre_image": state, "proposed": state, "tier": "A",
        "confidence": 0.95, "action": "confirm", "reason": f"provider confirms {state}",
    }


class RpcSpy:
    """A Supabase client that records the one RPC ``apply_decision`` makes."""

    def __init__(self):
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return self

    def execute(self):
        return type("Result", (), {"data": True})()


def test_a_confirm_reaches_the_rpc_with_the_stored_state_as_predicate_and_value():
    """Same value on both sides, so the row is stamped without moving; the ledger logs the
    provenance change under its own action, which migration 20260902210000 admits."""
    spy = RpcSpy()

    assert assign.apply_decision(spy, confirm_of("q", "WA"), "why") is True
    ((name, params),) = spy.calls
    assert name == "apply_team_state"
    assert (params["p_expected_state_code"], params["p_state_code"]) == ("WA", "WA")
    assert (params["p_source"], params["p_action"]) == ("tier_a", "confirm")


def replay_with_mirror(monkeypatch, decisions, reverts=frozenset(), sources=None, refuse=frozenset(), **kwargs):
    """``_replay`` for the confirm path: the applies, the mirrored rows, and the call order."""
    captured = _replay(monkeypatch, decisions, reverts=reverts, sources=sources, refuse=refuse, **kwargs)
    return captured["applied"], [d["team_id"] for d in captured["mirrored"]], captured["order"]


def test_a_confirm_is_written_but_never_mirrored(monkeypatch, capsys):
    applied, mirrored, _ = replay_with_mirror(
        monkeypatch, [confirm_of("q", "WA"), proposal("r", None)], limit=None
    )

    assert sorted(applied) == ["q", "r"]
    assert mirrored == ["r"]
    assert "Confirmed 1" in re.sub(r"\s+", " ", capsys.readouterr().out)


def test_fills_only_withholds_confirms_and_says_so_apart_from_corrections(monkeypatch, capsys):
    applied, _, _ = replay_with_mirror(
        monkeypatch, [confirm_of("q", "WA"), proposal("r", None), proposal("s", "NV")],
        limit=None, fills_only=True,
    )

    assert applied == ["r"]
    assert "withholding 1 corrections and 1 confirms" in re.sub(r"\s+", " ", capsys.readouterr().out)


def test_the_limit_bounds_confirms_as_their_own_outcome(monkeypatch):
    decisions = [confirm_of(f"c{i}", "WA") for i in range(3)] + [proposal(f"f{i}", None) for i in range(3)]
    applied, _, _ = replay_with_mirror(monkeypatch, decisions, limit=2)

    assert sorted(applied) == ["c0", "c1", "f0", "f1"]


def test_a_reverted_confirm_is_not_replayed(monkeypatch, capsys):
    """The revert ledger binds confirms as it binds applies: the pre-image of a confirm is
    the value a revert restored, so the RPC predicate would always pass."""
    applied, _, _ = replay_with_mirror(
        monkeypatch, [confirm_of("q", "WA"), confirm_of("r", "WA")], reverts={("q", "WA")}, limit=None
    )

    assert applied == ["r"]
    assert "1 reverted before" in re.sub(r"\s+", " ", capsys.readouterr().out)


def test_a_club_correction_is_skipped_when_the_record_landed_since_the_snapshot(monkeypatch, capsys):
    """The hold script read provenance before the split; this is the read beside the write.
    A confirm between the two changes provenance without moving the state, so the RPC's
    state-only predicate would let the club count overwrite the record's own stamp."""
    applied, _, _ = replay_with_mirror(
        monkeypatch,
        [
            proposal("q", "WA"),
            proposal("r", "WA"),
            {**proposal("s", "WA"), "tier": "A"},
            proposal("byhand", "WA"),
            {**proposal("record", "WA"), "tier": "A"},
            {**proposal("refresh", "WA"), "tier": "A"},
        ],
        sources={
            "q": "tier_a", "r": None, "s": "tier_b", "byhand": "operator",
            "record": "operator", "refresh": "tier_a",
        },
        limit=None,
    )

    # Tier B over tier_a: outranked. Tier A over tier_b: the record wins. Anything over an
    # operator's own answer, Tier A included: outranked. Tier A over tier_a: the record
    # refreshing itself, so a club that re-registers elsewhere can still be corrected.
    assert sorted(applied) == ["r", "refresh", "s"]
    assert "3 decisions outranked since the snapshot" in re.sub(r"\s+", " ", capsys.readouterr().out)


def test_a_revert_landing_mid_replay_still_blocks_the_confirm(monkeypatch, capsys):
    """Confirms run last, so the ledger read at the top of the replay is the stalest thing
    in it; the confirm phase reads again and honours what it finds."""
    applied, _, _ = replay_with_mirror(
        monkeypatch,
        [proposal("f", None), confirm_of("c", "WA")],
        reverts=[set(), {("c", "WA")}],
        limit=None,
    )

    assert applied == ["f"]
    assert "1 reverted before" in re.sub(r"\s+", " ", capsys.readouterr().out)


def test_the_confirm_phase_reads_provenance_for_its_own_teams(monkeypatch):
    """Confirms and applies never name the same team, so a confirm phase reusing the
    applies' read would find no provenance at all and re-stamp everything it was given."""
    captured = _replay(
        monkeypatch, [proposal("f", None), confirm_of("c", "WA")], sources={"c": "tier_a"}, limit=None
    )

    assert captured["sources_read"] == [["f"], ["c"]]
    assert captured["applied"] == ["f"]


def test_an_agreeing_audit_answer_is_confirmed_so_the_dissenter_leaves_the_pool(monkeypatch):
    """An agreement changes no state, so only the confirm's provenance stamp lets the team
    leave ``contradiction_candidates``; without it an agreeing dissenter is re-bought after
    the window with nothing to show for it."""
    snapshot, _ = audit(
        monkeypatch, audit_teams(), aliases={"wrong1", "wrong2"}, answers={"wrong1": "WA", "wrong2": "OH"}
    )
    by_team = {d["team_id"]: d for d in snapshot["decisions"]}

    assert by_team["wrong1"]["action"] == "confirm"
    assert (by_team["wrong2"]["action"], by_team["wrong2"]["proposed"]) == ("apply", "OH")


def test_a_population_mode_without_an_argument_is_refused_not_truncated(monkeypatch):
    """A plain ``zip`` stops at the shorter side, so a fourth entry in the table with no
    matching argument would be a mode every run silently reports as normal; the strict one
    refuses it, and unlike an assert it is not stripped under ``-O``."""
    monkeypatch.setattr(assign, "POPULATION_MODES", assign.POPULATION_MODES + (("--fourth", "fourth"),))

    with pytest.raises(ValueError):
        assign.chosen_populations(False, False, False)


def test_the_passed_over_line_names_its_unit(capsys):
    """The anchor pass counts clubs and the unclubbed pass counts teams; the same line
    without a unit invites adding the two."""
    snapshot = {
        "tier_d_available": False, "candidates_selected": 1, "probed": [], "aliases_found": 0,
        "probes_answered": 0, "cached_answers": 0, "skipped_durable": 0, "budget_applied": False,
        "passed_over": {"no alias": 3, assign.FALLBACK_REASON: 2}, "decisions": [],
    }
    assign.summarize({**snapshot, "mode": "anchor"})
    assign.summarize({**snapshot, "mode": "unclubbed"})
    out = re.sub(r"\s+", " ", capsys.readouterr().out)

    # A club asked through a club-mate was selected, not passed over: its own line.
    assert "passed over (clubs): 3 no alias" in out
    assert "passed over (teams): 3 no alias" in out
    assert "2 clubs asked a club-mate" in out


def test_a_confirm_whose_state_moved_is_counted_as_moved(monkeypatch, capsys):
    applied, _, _ = replay_with_mirror(
        monkeypatch, [confirm_of("c", "WA"), confirm_of("d", "WA")], refuse={"c"}, limit=None
    )

    assert applied == ["d"]
    assert "Confirmed 1 provider agreements, skipped 1 that moved" in re.sub(
        r"\s+", " ", capsys.readouterr().out
    )



@pytest.mark.parametrize("flag", ["--anchor-clubs", "--probe-unclubbed"])
def test_a_budgeted_anchoring_run_passes_validation(monkeypatch, capsys, flag):
    """The budget and the window are accepted beside either population flag, not only the
    audit's. ``run_cli`` clears the credentials, so this stops at the credential guard."""
    code, out = run_cli(monkeypatch, capsys, flag, "--probe-limit", "5000", "--reprobe-after-days", "30")

    assert code == 1
    assert "Missing SUPABASE_URL" in out


def test_the_anchor_report_counts_confirms_beside_the_corrections(capsys):
    snapshot = {
        "mode": "anchor",
        "tier_d_available": False,
        "candidates_selected": 3,
        "probed": ["a", "b", "c"],
        "aliases_found": 3,
        "probes_answered": 2,
        "cached_answers": 0,
        "skipped_durable": 0,
        "budget_applied": False,
        "passed_over": {"anchored": 4, "no alias": 1},
        "decisions": [
            confirm_of("a", "WA"),
            {"team_id": "b", "pre_image": "WA", "proposed": "OH", "tier": "A",
             "confidence": 0.95, "action": "apply", "reason": "correct WA -> OH from tier A"},
        ],
    }
    assign.summarize(snapshot)
    out = re.sub(r"\s+", " ", capsys.readouterr().out)

    assert "1 to apply" in out and "1 corrections" in out
    assert "1 confirmed" in out
    assert "3 clubs" in out and "4 anchored" in out


def test_the_anchor_report_names_its_own_budget_rule(capsys):
    snapshot = {
        "mode": "anchor",
        "tier_d_available": False,
        "candidates_selected": 3,
        "probed": ["a"],
        "aliases_found": 1,
        "probes_answered": 1,
        "cached_answers": 0,
        "skipped_durable": 0,
        "budget_applied": True,
        "passed_over": {},
        "decisions": [],
    }
    assign.summarize(snapshot)
    out = re.sub(r"\s+", " ", capsys.readouterr().out)

    assert "largest clubs first" in out
    assert "lowest ids first" not in out


def test_the_unclubbed_report_names_its_own_population_and_budget(capsys):
    """The non-anchoring half of the verify report, with both lines the anchor test leaves
    dark: the budget note and the answered-without-a-state line."""
    snapshot = {
        "mode": "unclubbed",
        "tier_d_available": False,
        "candidates_selected": 40,
        "probed": ["a"],
        "aliases_found": 1,
        "probes_answered": 1,
        "cached_answers": 2,
        "skipped_durable": 5,
        "budget_applied": True,
        "passed_over": {},
        "decisions": [],
    }
    assign.summarize(snapshot)
    out = re.sub(r"\s+", " ", capsys.readouterr().out)

    assert "Unclubbed: 40 teams selected" in out
    assert "5 skipped: answered before" in out
    assert "lowest ids first" in out
    assert "Undecidable teams are not examined in unclubbed mode" in out


def test_confirms_are_written_after_the_queue_and_the_mirror(monkeypatch):
    """Whatever refuses a confirm must find the queue rows and the mirror already done: a
    confirm the ledger refuses would otherwise strand applied corrections unmirrored on the
    boards."""
    decisions = [confirm_of("c", "WA"), proposal("f", None), proposal("q", "NV", action="queue")]
    _, _, order = replay_with_mirror(monkeypatch, decisions, limit=None)

    assert order == ["apply", "queue", "mirror", "confirm"]


def test_a_confirm_for_a_team_the_provider_already_vouched_for_is_not_rewritten(monkeypatch, capsys):
    """Step 4 replays the same snapshot after a --limit batch. The batch's confirms are
    already stamped, and stamping them again writes a second ledger row per team. An
    operator's hand mark is left alone for the stronger reason."""
    decisions = [confirm_of("done", "WA"), confirm_of("byhand", "WA"), confirm_of("fresh", "WA")]
    applied, _, _ = replay_with_mirror(
        monkeypatch, decisions, sources={"done": "tier_a", "byhand": "operator", "fresh": None}, limit=None
    )

    assert applied == ["fresh"]
    assert "2 already vouched for" in re.sub(r"\s+", " ", capsys.readouterr().out)


class _HandSet:
    """A client for ``assign_by_hand``: one stored team row, and every RPC captured."""

    def __init__(self, row):
        self.row = row
        self.rpcs = []
        self.projection = None

    def table(self, name):
        return self

    def select(self, columns):
        # Recorded rather than applied: the real client returns only what was asked for,
        # so the projection is the guard and a double that ignores it hides a trimmed one.
        self.projection = columns
        return self

    def eq(self, column, value):
        return self

    def limit(self, n):
        return self

    def rpc(self, name, params):
        self.rpcs.append(params)
        return self

    def execute(self):
        return type("R", (), {"data": [self.row]})()


def test_the_provenance_set_by_hand_is_the_one_every_gate_defers_to(monkeypatch, capsys):
    """``--set`` is the only writer of the operator's provenance and every gate reads
    ``OPERATOR_SOURCE``; two literals held equal by nothing is the drift that would let
    the next anchor pass overwrite a hand-set value in silence. An agreeing ``--set`` is
    written too, as a confirm, so the stamp lands whether or not the value moves -- a held
    row the operator agreed with is otherwise unprotected. Only a value already set by hand
    is left alone, which is what a retry after a committed write looks like."""
    mirrored = []
    monkeypatch.setattr(
        assign, "mirror_rankings", lambda sb, rows: mirrored.append([d["team_id"] for d in rows]) or len(rows)
    )
    stored = {
        "team_id_master": "t", "team_name": "T", "state_code": "WA",
        "state_source": "tier_b", "is_deprecated": False,
    }

    corrected = _HandSet(stored)
    assign.assign_by_hand(corrected, "t", "OH", None, execute=True)
    confirmed = _HandSet(stored)
    assign.assign_by_hand(confirmed, "t", "WA", None, execute=True)
    retried = _HandSet({**stored, "state_source": assign.OPERATOR_SOURCE})
    assign.assign_by_hand(retried, "t", "WA", None, execute=True)
    previewed = _HandSet(stored)
    assign.assign_by_hand(previewed, "t", "WA", None, execute=False)

    def stamped(client):
        return [
            (c["p_source"], c["p_action"], c["p_expected_state_code"], c["p_state_code"])
            for c in client.rpcs
        ]

    assert stamped(corrected) == [(assign.OPERATOR_SOURCE, "correct", "WA", "OH")]
    assert stamped(confirmed) == [(assign.OPERATOR_SOURCE, assign.CONFIRM_ACTION, "WA", "WA")]
    assert stamped(retried) == []
    assert stamped(previewed) == []
    # The retry guard reads a column the query has to ask for; every path mirrors, the
    # retry included, since a committed write with no mirror is what a retry is for.
    assert "state_source" in corrected.projection.split(",")
    assert mirrored == [["t"], ["t"], ["t"]]
    assert "Would confirm T: WA → WA" in re.sub(r"\s+", " ", capsys.readouterr().out)


def test_a_hand_set_team_named_like_markup_is_printed_not_rendered(monkeypatch, capsys):
    """Team names are provider-written and Rich reads square brackets as markup: a name
    shaped like a closing tag raised MarkupError between the RPC and the mirror, so the
    write committed and the retry died at the same line (IMP-160)."""
    monkeypatch.setattr(assign, "mirror_rankings", lambda sb, rows: 0)
    stored = {
        "team_id_master": "t", "team_name": "Rush [/dim] 07B", "state_code": "WA",
        "state_source": assign.OPERATOR_SOURCE, "is_deprecated": False,
    }

    assign.assign_by_hand(_HandSet(stored), "t", "WA", None, execute=True)
    assign.assign_by_hand(_HandSet({**stored, "state_source": "tier_b"}), "t", "WA", None, execute=False)
    assign.assign_by_hand(_HandSet({**stored, "state_source": "tier_b"}), "t", "OH", None, execute=True)

    out = capsys.readouterr().out
    assert out.count("Rush [/dim] 07B") == 3


def test_a_single_team_apply_defers_to_the_provenance_it_finds(monkeypatch, capsys):
    """``--team --execute`` is the one write that bypasses the snapshot replay, so it
    carries the same gate itself: a hand-set value is left alone and said so, an
    unvouched one is written and mirrored."""
    written = []
    monkeypatch.setattr(assign, "apply_decision", lambda sb, d, reason: written.append(d["team_id"]) or True)
    monkeypatch.setattr(assign, "mirror_rankings", lambda sb, rows: len(rows))
    snapshot = {"created_at": "now", "decisions": [proposal("byhand", "WA"), proposal("fresh", "WA")]}

    monkeypatch.setattr(assign, "fetch_state_sources", lambda sb, ids: {"byhand": assign.OPERATOR_SOURCE})
    assign.report_team(None, snapshot, "byhand", execute=True)
    monkeypatch.setattr(assign, "fetch_state_sources", lambda sb, ids: {"fresh": None})
    assign.report_team(None, snapshot, "fresh", execute=True)

    out = re.sub(r"\s+", " ", capsys.readouterr().out)
    assert written == ["fresh"]
    assert "Not applied: the stored value carries operator provenance" in out
    assert "Mirrored 1 ranking rows" in out


class TableSpy:
    """A Supabase client that records each ``.in_()`` batch a reader sends."""

    def __init__(self, rows):
        self.rows = rows
        self.batches = []

    def table(self, name):
        return self

    def select(self, columns):
        return self

    def in_(self, column, ids):
        self.batches.append(list(ids))
        self.pending = [r for r in self.rows if r["team_id_master"] in ids]
        return self

    def execute(self):
        return type("Result", (), {"data": self.pending})()


def test_fetch_state_sources_reads_in_batches_and_reports_what_it_found():
    """The reader the confirm and the outranked-apply guards rest on, driven for real: one
    batch per hundred ids, and a team the read does not return stays absent rather than
    inventing a provenance."""
    rows = [{"team_id_master": f"t{i}", "state_source": "tier_a" if i % 2 else None} for i in range(150)]
    spy = TableSpy(rows)

    sources = assign.fetch_state_sources(spy, [f"t{i}" for i in range(150)] + ["missing"])

    assert [len(b) for b in spy.batches] == [100, 51]
    assert sources["t1"] == "tier_a" and sources["t0"] is None
    assert "missing" not in sources
