"""The weekly review of state changes: which changes it takes, what a reviewer may answer on each, the evidence a
reviewer reads, the answers it accepts, and how its verdicts reach the page's lanes."""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.team_cleanup import pages  # noqa: E402
from scripts.team_cleanup import review_merges as rm  # noqa: E402
from scripts.team_cleanup import review_states as rs  # noqa: E402
from scripts.team_cleanup.run_store import CHANGE_REVIEW_KEYS, MANIFEST_FILE, check_reviews  # noqa: E402
from tests.unit import test_team_cleanup_pages as pt  # noqa: E402
from tests.unit.test_team_cleanup_review_merges import CLAUDE, _allowed, _Reviewers  # noqa: E402

QUEUED_APPLY = "the rules only queued it, and an approval given unattended would count as the owner's"
FILL_DECLINE = "the weekly fill job writes a blank state the rules fill, whatever is declined"
UNNAMED = "nothing in its own name or its club's name places it in NV"


def _row(item, tid, old, new, *, tier="B", action="apply", not_allowed=None):
    return {
        "item": item, "team_id_master": tid, "team_name": f"Team {tid}", "field": "state_code", "old_value": old,
        "new_value": new, "tier": tier, "action": action, "reason": "club-mates", "not_allowed": not_allowed or {},
    }  # fmt: skip


def _answer(row, verdict="apply", reason="the club name says so"):
    return {"item": row["item"], "team_id_master": row["team_id_master"], "verdict": verdict, "reason": reason}


ROWS = [
    _row("S0001", "t1", "UT", "NV"),
    _row("S0002", "t2", "NV", "UT", tier="E", action="queue", not_allowed={"apply": QUEUED_APPLY}),
    _row("S0003", "t3", None, "NV", not_allowed={"reject": FILL_DECLINE}),
]


def _slice(tmp_path, rows=ROWS, name="slice_01"):
    review = tmp_path / "review"
    (review / rm.ANSWERS_DIR).mkdir(parents=True, exist_ok=True)
    (review / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    (review / f"{name}.md").write_text(f"## evidence of {name}", encoding="utf-8")
    for brief in rs.BRIEFS:
        (review / brief).write_text(f"brief {brief}", encoding="utf-8")
    return review


# --- what a reviewer may answer -------------------------------------------------------------------


@pytest.mark.parametrize(
    "proposal, reading, barred",
    [
        (_row("", "t", "UT", "NV"), ("NV", "club"), {}),
        (_row("", "t", "UT", "NV"), ("NV", "team"), {}),
        (_row("", "t", "UT", "NV"), ("NV", "town"), {"apply": UNNAMED}),
        (_row("", "t", "UT", "NV"), ("UT", "club"), {"apply": UNNAMED}),
        (_row("", "t", "UT", "NV", action="queue"), ("NV", "club"), {"apply": QUEUED_APPLY}),
        (_row("", "t", "NV", "NV", tier="R9", action="queue"), ("NV", "club"), {"apply": QUEUED_APPLY}),
        (_row("", "t", None, "NV"), ("NV", "club"), {"reject": FILL_DECLINE}),
        (_row("", "t", "  ", "NV"), ("UT", "none"), {"apply": UNNAMED, "reject": FILL_DECLINE}),
        (_row("", "t", None, "NV", tier="E", action="queue"), ("NV", "town"), {"apply": QUEUED_APPLY}),
    ],
    ids=["club-name", "team-name", "town-word", "name-elsewhere", "queued", "flag", "fill", "padded-fill",
         "queued-fill"],
)  # fmt: skip
def test_a_reviewer_may_apply_only_what_its_own_name_settles_and_the_rules_would_apply(proposal, reading, barred):
    assert rs.not_allowed(proposal, reading) == barred


# --- answers --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spoil, message",
    [
        (lambda a: a[:-1], "one answer per change"),
        (lambda a: [a[1], a[0], a[2]], "does not answer S0001 in its place"),
        (lambda a: [{**a[0], "team_id_master": "t9"}, a[1], a[2]], "does not answer S0001 in its place"),
        (lambda a: [{**a[0], "verdict": "merge"}, a[1], a[2]], "a verdict the brief does not allow"),
        (lambda a: [{**a[0], "reason": " "}, a[1], a[2]], "no reason"),
    ],
    ids=["short", "reordered", "wrong-team", "verdict", "reason"],
)
def test_an_answer_must_judge_each_change_once_in_order_with_a_verdict_and_a_reason(tmp_path, spoil, message):
    path = tmp_path / "verdicts.json"
    path.write_text(json.dumps(spoil([_answer(r, "hold") for r in ROWS])), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        rs.read_verdicts(path, ROWS)


def test_an_answer_a_change_does_not_allow_is_read_as_a_hold_saying_why(tmp_path):
    path = tmp_path / "verdicts.json"
    answers = [_answer(ROWS[0]), _answer(ROWS[1], reason="the club's own name says Utah"),
               _answer(ROWS[2], "reject", "nothing places it")]  # fmt: skip
    path.write_text(json.dumps(answers), encoding="utf-8")

    read = rs.read_verdicts(path, ROWS)

    assert [a["verdict"] for a in read] == ["apply", "hold", "hold"]
    assert read[1]["reason"] == f"reviewers would apply it (the club's own name says Utah), but {QUEUED_APPLY}"
    assert read[2]["reason"] == f"reviewers would reject it (nothing places it), but {FILL_DECLINE}"


def test_only_a_reject_the_second_reviewer_upholds_stays_a_reject():
    verdicts = [_answer(ROWS[0]), _answer(ROWS[1], "reject", "a town word only"), _answer(ROWS[2], "hold", "unclear")]

    upheld = rs.final_rows(ROWS, verdicts, {"S0002": {"item": "S0002", "upheld": True, "reason": "nothing says UT"}})
    doubted = rs.final_rows(
        ROWS, verdicts, {"S0002": {"item": "S0002", "upheld": False, "reason": "the owner chose UT"}}
    )

    assert [r["verdict"] for r in upheld] == ["apply", "reject", "hold"]
    assert doubted[1]["verdict"] == "hold"
    assert doubted[1]["reason"] == (
        "one reviewer found the stored state right (a town word only), and a second did not agree: the owner chose UT"
    )
    assert rs.final_rows(ROWS, verdicts, {})[1]["verdict"] == "hold"


def test_a_reject_the_change_does_not_allow_goes_to_no_second_reviewer(tmp_path):
    review = _slice(tmp_path)
    verdicts = [_answer(ROWS[0], "hold"), _answer(ROWS[1], "reject"), _answer(ROWS[2], "reject")]
    reviewers = _Reviewers([verdicts, [{"item": "S0002", "upheld": True, "reason": "nothing says UT"}]])

    left = rm.review_queued(review, CLAUDE, reviewers, rs.CHANGES)

    assert left == [] and check_reviews(review, CHANGE_REVIEW_KEYS) == ((), ())
    assert reviewers.kinds() == ["review", "recheck"]
    assert reviewers.commands[1][2].startswith(
        "Read RECHECK.md in this folder and follow it. Recheck these changes from slice_01.md: S0002."
    )
    final = json.loads((review / f"slice_01{rm.REVIEW_SUFFIX}").read_text(encoding="utf-8"))
    assert [(r["item"], r["verdict"]) for r in final] == [("S0001", "hold"), ("S0002", "reject"), ("S0003", "hold")]


# --- a week's changes from selection to the lanes -------------------------------------------------

EXTRA_COLUMNS = {
    "team_cleanup_decisions": {"source", "note"},
    "team_state_review_queue": {"id", "team_id_master", "current_state_code", "proposed_state_code", "status",
                                "reviewed_at"},
    "team_state_audit": {"id", "team_id_master", "action", "old_state_code", "new_state_code", "applied_at",
                         "applied_by", "reason"},
}  # fmt: skip
DECISIONS = [
    pt._decision("named", "UT", "NV"),
    pt._decision("weak", "NV", "UT", action="queue", tier="E"),
    pt._decision("flag", "NV", "NV", action="queue", tier="R9"),
    pt._decision("queued", "NV", "UT", action="queue"),
    pt._decision("held", "NV", "UT", action="queue", tier="E"),
    pt._decision("fill", None, "NV"),
]
TEAMS = [
    pt._team("named", state="UT", club="Nevada Elite FC"),
    pt._team("weak", club="Desert Club"),
    pt._team("flag", club="Desert Club"),
    pt._team("queued", club="Desert Club"),
    pt._team("held", club="Desert Club"),
    pt._team("fill", state=None),
    pt._team("mate", club="Desert Club"),
]


def _week(tmp_path, monkeypatch, decisions=DECISIONS, teams=TEAMS, **tables):
    for table, columns in EXTRA_COLUMNS.items():
        monkeypatch.setitem(pt.COLUMNS, table, pt.COLUMNS.get(table, set()) | columns)
    store = tmp_path / "store"
    pt._reviewing(store)
    pt._states(store, decisions)
    return store, pt._Db(teams=teams, **tables)


class _StatePanel:
    """Headless reviewers answering each change by its team from the evidence copied into their own folder:
    ``verdicts`` maps it to a verdict, and every reject is upheld."""

    def __init__(self, verdicts):
        self.verdicts, self.folders = verdicts, []

    def __call__(self, command, cwd, log):
        work = Path(cwd)
        self.folders.append(work)
        log.write_text("ran", encoding="utf-8")
        name, kind = work.name.rsplit("-", 1)
        evidence = (work / f"{name}.md").read_text(encoding="utf-8")
        if kind == "review":
            answer = [
                {"item": item, "team_id_master": tid, "verdict": self.verdicts[tid], "reason": f"because {tid}"}
                for item, tid in re.findall(r"^## (S\d{4}) team_id=(\S+)$", evidence, re.M)
            ]
        else:
            labels = re.search(r"from \S+\.md: (.+)\. Write", command[2]).group(1).split(", ")
            answer = [{"item": label, "upheld": True, "reason": "nothing places it there"} for label in labels]
        (work / _allowed(command)).write_text(json.dumps(answer), encoding="utf-8")
        return 0


def _main(monkeypatch, capsys, store, db, runner, *flags):
    monkeypatch.setattr(rs, "get_client", lambda: db)
    monkeypatch.setattr(rm.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(rm, "run_reviewer", runner)
    argv = ["review_states.py", "--run", pt.RUN, "--stage", "states", "--store", str(store), *flags]
    monkeypatch.setattr(sys, "argv", argv)
    try:
        code = rs.main()
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr().out


def test_the_review_s_verdicts_reach_the_lanes_and_a_found_right_state_is_recorded_declined(
    tmp_path, monkeypatch, capsys
):
    """Selection, evidence, reviewers, the page and the automatic lane's collect together: a change its club's own
    name settles applies, an upheld reject and a flag found wrong go to the lane kept as they are and are recorded
    Don't apply, an approval of a change the rules only queued is a card, a hold is a card, and a fill the rules
    settle applies unreviewed."""
    store, db = _week(tmp_path, monkeypatch)
    panel = _StatePanel({"named": "apply", "weak": "reject", "flag": "reject", "queued": "apply", "held": "hold"})

    code, out = _main(monkeypatch, capsys, store, db, panel, "--execute")

    assert code == 0 and "reviewed state changes: 1 apply, 2 hold, 2 reject, judged by assigning-team-states at " in out
    assert {f.name for f in panel.folders} == {"slice_01-review", "slice_01-recheck"}
    reviewed = json.loads((pt.stage_dir(store, pt.RUN, "states") / "review" / "slice_01.json").read_text())
    assert sorted(r["team_id_master"] for r in reviewed) == ["flag", "held", "named", "queued", "weak"]

    code, _ = pt._publish(monkeypatch, capsys, store, db, "--publish", "--execute", stage="states")

    manifest = pt._read(store, "states", MANIFEST_FILE)
    assert code == 0
    assert sorted(p["team_id_master"] for p in manifest["auto"].values()) == ["fill", "flag", "named", "weak"]
    assert sorted(p["team_id_master"] for p in manifest["cards"].values()) == ["held", "queued"]
    kept = {r["card"]["team"]["name"]: r["card"]["keep_as_is"] for r in db.cards(lane="auto")}
    assert kept == {"Team named": False, "Team weak": True, "Team flag": True, "Team fill": False}
    auto_why = {r["card"]["team"]["name"]: r["card"]["why"] for r in db.cards(lane="auto")}
    assert auto_why["Team named"] == "Reviewers found its own name settles it: because named"
    assert auto_why["Team weak"] == "Reviewers found the stored state right: because weak"
    why = {r["card"]["team"]["name"]: r["card"]["why"] for r in db.cards(lane="owner")}
    assert why == {
        "Team queued": f"Reviewers held it: reviewers would apply it (because queued), but {QUEUED_APPLY}",
        "Team held": "Reviewers held it: because held",
    }

    code, _ = pt._collect_auto(monkeypatch, capsys, store, "states")

    lane = pt.stage_dir(store, pt.RUN, "states") / "auto"
    decided = {r["team_id_master"]: r["decision"] for r in json.loads((lane / "decisions.json").read_text())}
    assert code == 0
    assert decided == {"named": "apply", "weak": "dont_apply", "flag": "dont_apply", "fill": "apply"}
    vetted = json.loads((lane / "vetted.json").read_text(encoding="utf-8"))
    assert sorted(d["team_id"] for d in vetted["decisions"]) == ["fill", "named"]


def test_the_evidence_shows_what_settles_a_state_and_leaves_out_where_the_team_played(tmp_path, monkeypatch):
    teams = [{**t, "state_source": "operator"} if t["team_id_master"] == "mate" else t for t in TEAMS]
    store, db = _week(
        tmp_path, monkeypatch, teams=teams,
        team_state_probe_log=[pt._probe("weak", "UT", n=1), pt._probe("weak", None, outcome="no_association", n=2)],
        team_cleanup_decisions=[
            {**pt._declined("weak", "UT", decision="apply", n=1), "source": "page:2026-10-21", "note": "club says UT"},
            {**pt._declined("mate", "NV", decision="apply", n=2), "source": "page:2026-10-21", "note": None},
        ],
        team_state_review_queue=[{"id": 1, "team_id_master": "weak", "current_state_code": "NV",
                                  "proposed_state_code": "UT", "status": "pending", "reviewed_at": None}],
        team_state_audit=[{"id": 1, "team_id_master": "weak", "action": "apply", "old_state_code": None,
                           "new_state_code": "NV", "applied_at": "2026-09-02T10:00:00+00:00",
                           "applied_by": "assign_team_states", "reason": "fill from tier B"}],
    )  # fmt: skip
    folder = pt.stage_dir(store, pt.RUN, "states")
    rows, chosen, evidence = rs.review_changes(db, folder, 100)

    block = next(b for b in rs.evidence_blocks(db, rows, chosen, evidence, folder) if "team_id=weak" in b)

    lines = block.splitlines()
    assert lines[1] == '"Team weak" | registered: null | club: "Desert Club" | gotsport | u12 Male'
    assert lines[2] == (
        'stored: NV (written by nothing recorded) | proposed: UT, tier E, the rules would only queue it '
        '| their reason: "club-mates"'
    )
    assert lines[3] == f"you may answer: hold, reject; not apply, since {QUEUED_APPLY}"
    assert lines[4] == "its name: nothing in its name places it"
    assert lines[5].startswith("GotSport's own record: no state (no_association), asked ")
    assert lines[6] == "club registry: not listed"
    assert lines[7] == "club-mates' stored states (4 teams): NV 4 (unstamped 3, operator 1)"
    assert lines[8] == "the owner's earlier choices on this club's teams: apply NV x1"
    assert lines[9] == 'earlier choices on this team: 2026-10-01 the owner: apply UT "club says UT"'
    assert lines[10] == "review queue: pending UT from NV"
    assert lines[11] == 'state history: 2026-09-02 assign_team_states apply -- -> NV "fill from tier B"'
    assert lines[12] == "hold check: passes"
    assert "opponent" not in block.lower()


def test_a_state_change_the_review_did_not_reach_stays_a_card_while_a_club_guess_is_left_off():
    state = {"team_id_master": "s", "field": "state_code", "old_value": "UT", "new_value": "NV", "tier": "B"}
    guess = {"team_id_master": "c", "field": "club_name", "old_value": "Lonestar", "new_value": "LSC",
             "tier": "recased"}  # fmt: skip

    assert pages.with_change_reviews("states", [state], {}) == ([state], [])
    assert pages.with_change_reviews("clubs", [guess], {}) == (
        [], [{**guess, "why": "the scan lists recased guesses without approving them"}]
    )


def test_the_states_page_waits_for_its_review_and_a_dry_run_queues_nothing(tmp_path, monkeypatch, capsys):
    store, db = _week(tmp_path, monkeypatch)

    with pytest.raises(SystemExit, match="its state changes are not reviewed yet: run review_states.py --execute"):
        pt._build(monkeypatch, capsys, store, db, stage="states")

    code, out = _main(monkeypatch, capsys, store, db, _StatePanel({}))

    assert code == 0 and "DRY RUN -- would queue 5 state change(s) for review, 50 a reviewer" in out
    assert not (pt.stage_dir(store, pt.RUN, "states") / "review").exists()


def test_the_review_packs_the_states_skill_and_its_briefs_name_the_lookup(tmp_path, monkeypatch, capsys):
    store, db = _week(tmp_path, monkeypatch)
    panel = _StatePanel(dict.fromkeys(("named", "weak", "flag", "queued", "held"), "hold"))
    _main(monkeypatch, capsys, store, db, panel, "--execute")

    review = pt.stage_dir(store, pt.RUN, "states") / "review"
    brief = (review / "BRIEF.md").read_text(encoding="utf-8")
    assert f"python {rm.LOOKUP} spellings <text> [<state>]" in brief and "{lookup}" not in brief
    assert (review / "skill" / "SKILL.md").read_bytes() == (rm.SKILLS / rs.STATE_SKILL / "SKILL.md").read_bytes()
    assert rm.skill_version(review).startswith(f"{rs.STATE_SKILL} at ")


def test_every_section_the_states_brief_sends_a_reviewer_to_is_in_the_skill():
    brief = rs.BRIEFS["BRIEF.md"].read_text(encoding="utf-8")
    reading = brief.split("before your slice:\n", 1)[1].split("\n\n", 1)[0]
    named = re.findall(r"`skill/([^`]+)`: (.+?)(?=\n- `|\Z)", reading, re.S)
    skill = rm.SKILLS / rs.STATE_SKILL

    assert [path for path, _ in named] == ["SKILL.md", "references/evidence-tiers.md", "references/failure-modes.md"]
    for path, sections in named:
        headings = re.findall(r"^#+ (.+)$", (skill / path).read_text(encoding="utf-8"), re.M)
        for section in re.findall(r'"([^"]+)"', sections):
            assert section in headings, f"{path} has no section {section!r}"
