"""Tests for the weekly cleanup's rules for which proposed changes the evidence already settles, and
the replay that checks them against the owner's own decisions."""

import ast
import os
import sys

import pytest
from postgrest.exceptions import APIError

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.assign_team_states import build_locality_index  # noqa: E402
from scripts.team_cleanup import replay_sure, sure  # noqa: E402
from scripts.team_cleanup.collect import DECISIONS_FILE  # noqa: E402
from scripts.team_cleanup.decisions import DecisionsUnavailable  # noqa: E402
from scripts.team_cleanup.propose_week import AGE_EVIDENCE, AGE_REVIEW_FILE, ROOT  # noqa: E402
from scripts.team_cleanup.run_store import MANIFEST_FILE, stage_dir, write_run  # noqa: E402
from src.tournaments.storage._io import write_json  # noqa: E402
from tests.unit.test_team_cleanup_pages import RUN, _Db, _decision, _merged, _reviewing, _states, _team  # noqa: E402

# The age review's own tier names, as its write-plan step writes them into the plan.
BAND, ULABEL, PLAYS_UP = "A_own_name_band", "U_own_name_ulabel_opponent_confirmed", "U_own_name_ulabel_plays_up"
SAME = lambda team: team  # noqa: E731 -- no team merged


def _change(tid, field, old, new, **extra):
    change = {"team_id_master": tid, "team_name": f"Team {tid}", "field": field, "old_value": old, "new_value": new}
    return {**change, **extra}


def _club(tid, *, approved=True, tier="swap"):
    return _change(tid, "club_name", "colorado edge", "Colorado EDGE", tier=tier, approved=approved, needs_review=False)


def _state(tid, old, new, *, tier="B", action="apply"):
    return _change(tid, "state_code", old, new, tier=tier, action=action, reason="club-mates")


def _age(tid, old, new, tier=ULABEL, **evidence):
    return _change(tid, "age_group", old, new, tier=tier, **{key: evidence.get(key) for key in AGE_EVIDENCE})


def _signals(teams=(), answers=None, held=(), reverted=(), index=None):
    teams = list(teams)
    by_id = {t["team_id_master"]: t for t in teams}
    evidence = sure.StateEvidence(answers or {}, by_id, build_locality_index(teams) if index is None else index)
    return sure.Signals(set(reverted), set(held), evidence)


@pytest.mark.parametrize(
    "proposal, settled",
    [
        (_club("trusted"), True),
        (_club("disputed", approved=False), False),
        (_club("listed", approved=False, tier="recased"), False),
    ],
    ids=["approved", "two-sources-disagree", "listed-guess"],
)
def test_a_club_change_is_sure_only_when_the_scan_approves_it(proposal, settled):
    assert bool(sure.sure_because("clubs", proposal, sure.Signals())) is settled


def test_a_blank_state_filled_from_the_club_is_sure():
    signals = _signals([_team("fill", state=None)])

    assert sure.sure_because("states", _state("fill", None, "NV"), signals)


@pytest.mark.parametrize(
    "proposal, team, answers, held",
    [
        (_state("titans", "UT", "CA"), _team("titans", state="UT", club="Titans FC", name="U18"), {}, ()),
        (
            _state("leahi", "HI", "CA", action="queue"),
            _team("leahi", state="HI", club="Legends FC (CA)"),
            {"leahi": "HI"},
            (),
        ),
        (_state("held", None, "NV"), _team("held", state=None), {}, ("held",)),
        (_state("gotsport", None, "NV"), _team("gotsport", state=None), {"gotsport": "UT"}, ()),
        (_state("named", None, "NV"), _team("named", state=None, name="California Storm 2012"), {}, ()),
        (_state("unplaced", None, "NV"), _team("unplaced", state=None, name="Sporting Kansas City 2012"), {}, ()),
        (_state("queued", None, "NV", action="queue"), _team("queued", state=None), {}, ()),
        (_state("town", None, "CA", tier="E"), _team("town", state=None), {}, ()),
        (_state("gone", None, "NV"), None, {}, ()),
    ],
    ids=[
        "correction-by-club-count",
        "correction-gotsport-disputes",
        "fill-the-hold-check-holds",
        "fill-gotsport-names-another-state",
        "fill-the-name-places-elsewhere",
        "fill-the-name-cannot-be-placed",
        "fill-the-rules-only-queue",
        "fill-from-a-town-word",
        "fill-for-a-team-no-longer-live",
    ],
)
def test_every_state_correction_and_every_disputed_fill_is_the_owner_s(proposal, team, answers, held):
    """A correction is never sure, however many club-mates back it, and a fill is sure only when
    nothing disputes it."""
    signals = _signals([team] if team else [], answers, held)

    assert sure.sure_because("states", proposal, signals) is None


def test_a_fill_whose_name_points_two_ways_is_the_owner_s():
    """Town words for two states in one name read as no state at all, which is not agreement."""
    signals = _signals([_team("split", state=None, name="Reno Provo 2012")], index={"reno": "NV", "provo": "UT"})

    assert sure.sure_because("states", _state("split", None, "NV"), signals) is None


def test_a_fill_gotsport_agrees_with_is_sure():
    signals = _signals([_team("fill", state=None)], {"fill": "NV"})

    assert sure.sure_because("states", _state("fill", None, "NV"), signals)


@pytest.mark.parametrize(
    "proposal, settled",
    [
        (_age("band", "u14", "u13", tier=BAND), True),
        (_age("opponents", "u17", "u9", band_opps_say="u9", year_witness="A 3:0"), True),
        (_age("division", "u17", "u9", div_says="u9"), True),
        (_age("gotsport", "u17", "u9", gotsport_age="u9"), True),
        (_age("near", "u11", "u9", year_witness="A 2:0"), True),
        (_age("lone-year", "u17", "u9", year_witness="A 3:0"), False),
        (_age("three-groups", "u12", "u9", year_witness="A 4:0"), False),
        (_age("other-witness", "u17", "u9", band_opps_say="u10", gotsport_age="u12"), False),
        (_age("plays-up", "u13", "u12", tier=PLAYS_UP, gotsport_age="u12"), False),
        (_age("blank", None, "u12"), False),
    ],
    ids=[
        "band-in-own-name",
        "u-label-opponents-confirm",
        "u-label-division-confirms",
        "u-label-gotsport-confirms",
        "u-label-two-groups",
        "u-label-on-a-lone-year-witness",
        "u-label-three-groups",
        "u-label-witnesses-name-other-ages",
        "u-label-plays-up",
        "no-stored-age",
    ],
)
def test_an_age_move_is_sure_from_its_own_band_or_a_confirmed_near_u_label(proposal, settled):
    """A far U-label move resting on the opponents' birth years alone stays the owner's: they turned
    down a U17 team moved to U9 that way."""
    assert bool(sure.sure_because("ages", proposal, sure.Signals())) is settled


def test_the_age_evidence_names_are_columns_the_age_review_writes():
    """The review writes its columns from a list inside its review step; a renamed column would leave
    every proposal carrying no evidence, and no U-label move would read as confirmed."""
    script = ROOT / ".claude" / "skills" / "correcting-team-age-groups" / "scripts" / "review_age_labels.py"
    review = next(
        node
        for node in ast.walk(ast.parse(script.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name == "review"
    )
    fields = next(
        ast.literal_eval(node.value)
        for node in ast.walk(review)
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "fields" for t in node.targets)
    )

    assert {"team_id", *AGE_EVIDENCE} <= set(fields)


@pytest.mark.parametrize(
    "stage, proposal",
    [
        ("clubs", _club("t")),
        ("states", _state("t", None, "NV")),
        ("ages", _age("t", "u14", "u13", tier=BAND)),
    ],
)
def test_a_change_an_undo_reversed_is_never_sure_again(stage, proposal):
    signals = _signals([_team("t", state=None)], reverted=[("t", proposal["field"], proposal["new_value"])])

    assert sure.sure_because(stage, proposal, signals) is None


def _ledgered(n, tid, new, *, reverted=None, stage="ages", field="age_group"):
    return {"id": n, "stage": stage, "team_id_master": tid, "field": field, "new_value": new, "reverted_at": reverted}


def test_only_the_stage_s_reverted_changes_are_read_back_keyed_on_the_surviving_team():
    """An undo outlives a merge of its team: the survivor is proposed the same change next."""
    undone = "2026-10-12T00:00:00+00:00"
    db = _Db(
        team_cleanup_changes=[
            _ledgered(1, "undone", "u13", reverted=undone),
            _ledgered(2, "kept", "u13"),
            _ledgered(3, "other", "NV", reverted=undone, stage="states", field="state_code"),
            _ledgered(4, "merged-away", "u12", reverted=undone),
        ]
    )
    canonical = {"merged-away": "survivor"}.get

    assert sure.reverted_changes(db, "ages", lambda t: canonical(t, t)) == {
        ("undone", "age_group", "u13"),
        ("survivor", "age_group", "u12"),
    }


def test_an_unreadable_ledger_stops_rather_than_reads_every_undo_as_none():
    db = _Db()
    db.broken["team_cleanup_changes"] = APIError({"code": "PGRST205", "message": "not found"})

    with pytest.raises(DecisionsUnavailable, match="team_cleanup_changes"):
        sure.reverted_changes(db, "ages", SAME)


def test_the_hold_check_reads_each_fill_against_the_provenance_its_team_carries(tmp_path):
    """A fill over a team an operator answered is held, as the applier's own hold step holds it."""
    store = tmp_path / "store"
    _reviewing(store)
    _states(store, [_decision("answered", None, "NV"), _decision("open", None, "NV"), _decision("moved", "UT", "NV")])
    db = _Db(teams=[{**_team("answered", state=None), "state_source": "operator"}, _team("open", state=None)])
    proposals = [_state("answered", None, "NV"), _state("open", None, "NV"), _state("moved", "UT", "NV")]

    assert sure.held_fills(db, stage_dir(store, RUN, "states"), proposals) == {"answered"}


def test_a_page_of_lock_cards_reads_no_state_evidence():
    db = _Db()
    db.broken["team_state_probe_log"] = APIError({"code": "PGRST205", "message": "not found"})

    assert sure.state_evidence(db, "states", [_state("lock", "NV", "NV")]) is None
    assert sure.state_evidence(db, "ages", [_age("a", "u14", "u13")]) is None
    assert db.executes == []


# --- the replay against the owner's decisions --------------------------------------------------

OTHER_RUN = "2026-10-14-az"


def _replay_run(store, run_id, cards, decisions, *, stage="ages", review=None):
    """A finished run's page and collected choices, as the build and the collector leave them."""
    write_run(store, {"run_id": run_id, "scope": {"states": ["NV"]}, "status": "done", "budgets": {}, "stages": {}})
    folder = stage_dir(store, run_id, stage)
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / MANIFEST_FILE, {"run": f"page-{run_id}", "cards": cards})
    if decisions is not None:
        write_json(folder / DECISIONS_FILE, [{**cards[c], "decision": d} for c, d in decisions.items()])
    if stage == "ages":
        header = "team_id," + ",".join(AGE_EVIDENCE)
        rows = [f"{tid}," + ",".join(e.get(k, "") for k in AGE_EVIDENCE) for tid, e in (review or {}).items()]
        (folder / AGE_REVIEW_FILE).write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return folder


def _two_age_cards():
    return {"c1": _age("band", "u14", "u13", tier=BAND), "c2": _age("lone", "u17", "u9", year_witness="A 3:0")}


def _replay(monkeypatch, capsys, store, db, runs=RUN):
    monkeypatch.setattr(replay_sure, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["replay_sure.py", "--runs", runs, "--store", str(store)])
    code = replay_sure.main()
    return code, capsys.readouterr().out


def _row(out, stage, kind):
    lines = out.splitlines()
    return lines[lines.index(stage) + (1 if kind == "sure" else 2)].strip()


def test_the_replay_passes_when_the_owner_wanted_every_sure_change(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _replay_run(store, RUN, _two_age_cards(), {"c1": "apply", "c2": "dont_apply"})

    code, out = _replay(monkeypatch, capsys, store, _Db())

    assert code == 0
    assert _row(out, "ages", "sure") == "sure: apply=1  dont_apply=0  unsure=0  undecided=0"
    assert _row(out, "ages", "conflict") == "conflict: apply=0  dont_apply=1  unsure=0  undecided=0"


@pytest.mark.parametrize("decision", ["dont_apply", "unsure"])
def test_the_replay_fails_on_a_sure_change_the_owner_turned_down_or_doubted(tmp_path, monkeypatch, capsys, decision):
    store = tmp_path / "store"
    _replay_run(store, RUN, _two_age_cards(), {"c1": decision})

    code, out = _replay(monkeypatch, capsys, store, _Db())

    assert code == 1
    assert f"{RUN} ages: 'Team band' u14 -> u13 ({decision})" in out


def test_a_sure_card_left_undecided_is_counted_and_passes(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _replay_run(store, RUN, _two_age_cards(), {})

    code, out = _replay(monkeypatch, capsys, store, _Db())

    assert code == 0
    assert _row(out, "ages", "sure") == "sure: apply=0  dont_apply=0  unsure=0  undecided=1"


def test_the_replay_adds_up_every_run_and_names_an_unwanted_card_from_any_of_them(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _replay_run(store, RUN, _two_age_cards(), {"c1": "dont_apply"})
    _replay_run(store, OTHER_RUN, _two_age_cards(), {"c1": "apply"})

    code, out = _replay(monkeypatch, capsys, store, _Db(), runs=f"{RUN},{OTHER_RUN}")

    assert code == 1
    assert _row(out, "ages", "sure") == "sure: apply=1  dont_apply=1  unsure=0  undecided=0"
    assert f"{RUN} ages: 'Team band' u14 -> u13 (dont_apply)" in out


def test_each_decision_is_matched_to_its_own_team_not_to_another_card_with_the_same_change(
    tmp_path, monkeypatch, capsys
):
    store = tmp_path / "store"
    cards = {"c1": _age("kept", "u14", "u13", tier=BAND), "c2": _age("declined", "u14", "u13", tier=BAND)}
    _replay_run(store, RUN, cards, {"c1": "apply", "c2": "dont_apply"})

    code, out = _replay(monkeypatch, capsys, store, _Db())

    assert code == 1
    assert "'Team declined'" in out and "'Team kept'" not in out


def test_a_run_proposed_before_proposals_carried_the_evidence_takes_it_from_its_review(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    older = {"c1": _change("old", "age_group", "u17", "u9", tier=ULABEL)}
    _replay_run(store, RUN, older, {"c1": "apply"}, review={"old": {"band_opps_say": "u9", "year_witness": "A 3:0"}})

    code, out = _replay(monkeypatch, capsys, store, _Db())

    assert code == 0
    assert _row(out, "ages", "sure") == "sure: apply=1  dont_apply=0  unsure=0  undecided=0"


def test_a_states_replay_reads_the_evidence_and_the_hold_check(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    cards = {"c1": _state("fill", None, "NV"), "c2": _state("operator", None, "NV")}
    folder = _replay_run(store, RUN, cards, {"c1": "apply", "c2": "dont_apply"}, stage="states")
    write_json(
        folder / "snapshot.json",
        {"decisions": [_decision("fill", None, "NV"), _decision("operator", None, "NV")]},
    )
    teams = [_team("fill", state=None), {**_team("operator", state=None), "state_source": "operator"}]

    code, out = _replay(monkeypatch, capsys, store, _Db(teams=teams))

    assert code == 0
    assert _row(out, "states", "sure") == "sure: apply=1  dont_apply=0  unsure=0  undecided=0"
    assert _row(out, "states", "conflict") == "conflict: apply=0  dont_apply=1  unsure=0  undecided=0"


def test_an_undo_on_a_team_since_merged_keeps_the_survivor_s_change_off_the_sure_list(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _replay_run(store, RUN, {"c1": _age("survivor", "u14", "u13", tier=BAND)}, {"c1": "dont_apply"})
    db = _Db(
        team_merge_map=[_merged("merged-away", "survivor")],
        team_cleanup_changes=[_ledgered(1, "merged-away", "u13", reverted="2026-10-12T00:00:00+00:00")],
    )

    code, out = _replay(monkeypatch, capsys, store, db)

    assert code == 0
    assert _row(out, "ages", "conflict") == "conflict: apply=0  dont_apply=1  unsure=0  undecided=0"


def test_a_card_whose_team_was_merged_since_its_run_reads_the_survivor_s_undo(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _replay_run(store, RUN, {"c1": _age("merged-away", "u14", "u13", tier=BAND)}, {"c1": "dont_apply"})
    db = _Db(
        team_merge_map=[_merged("merged-away", "survivor")],
        team_cleanup_changes=[_ledgered(1, "survivor", "u13", reverted="2026-10-12T00:00:00+00:00")],
    )

    code, out = _replay(monkeypatch, capsys, store, db)

    assert code == 0
    assert _row(out, "ages", "conflict") == "conflict: apply=0  dont_apply=1  unsure=0  undecided=0"


def test_a_fill_the_hold_check_held_stays_held_after_its_team_is_merged(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    folder = _replay_run(store, RUN, {"c1": _state("merged-away", None, "NV")}, {"c1": "dont_apply"}, stage="states")
    write_json(folder / "snapshot.json", {"decisions": [_decision("merged-away", None, "NV")]})
    teams = [
        {**_team("merged-away", state=None, deprecated=True), "state_source": "operator"},
        _team("survivor", state=None),
    ]
    db = _Db(teams=teams, team_merge_map=[_merged("merged-away", "survivor")])

    code, out = _replay(monkeypatch, capsys, store, db)

    assert code == 0
    assert _row(out, "states", "conflict") == "conflict: apply=0  dont_apply=1  unsure=0  undecided=0"


@pytest.mark.parametrize(
    "setup, runs, message",
    [
        (lambda store: None, RUN, "Cannot replay .*run.json"),
        (lambda store: _reviewing(store), RUN, "built no page to replay"),
        (lambda store: _replay_run(store, RUN, _two_age_cards(), None), RUN, "was never collected"),
        (lambda store: None, " , ", "Name at least one run"),
    ],
    ids=["unknown-run", "run-with-no-page", "page-never-collected", "no-run-named"],
)
def test_a_replay_that_would_read_nothing_refuses_rather_than_passes(
    tmp_path, monkeypatch, capsys, setup, runs, message
):
    store = tmp_path / "store"
    store.mkdir()
    setup(store)

    with pytest.raises(SystemExit, match=message):
        _replay(monkeypatch, capsys, store, _Db(), runs=runs)


def test_an_unreadable_ledger_ends_the_replay_with_a_message(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _replay_run(store, RUN, _two_age_cards(), {"c1": "apply"})
    db = _Db()
    db.broken["team_cleanup_changes"] = APIError({"code": "PGRST205", "message": "not found"})

    with pytest.raises(SystemExit, match="Cannot replay .*team_cleanup_changes"):
        _replay(monkeypatch, capsys, store, db)
