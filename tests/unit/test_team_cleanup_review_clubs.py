"""The weekly review of club-name guesses: which changes it takes, the evidence a reviewer reads, the answers
it accepts, and how its verdicts reach the page's lanes."""

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.team_cleanup import review_clubs as rc  # noqa: E402
from scripts.team_cleanup import review_lookup as lookup  # noqa: E402
from scripts.team_cleanup import review_merges as rm  # noqa: E402
from scripts.team_cleanup.run_store import CHANGE_REVIEW_KEYS, MANIFEST_FILE, check_reviews  # noqa: E402
from tests.unit import test_team_cleanup_pages as pt  # noqa: E402
from tests.unit.test_team_cleanup_review_merges import CLAUDE, _allowed, _Reviewers  # noqa: E402
from tests.unit.test_team_cleanup_review_merges import _Db as _LookupDb  # noqa: E402
from tests.unit.test_team_cleanup_review_merges import _team as _lookup_team  # noqa: E402


def _row(item, tid, old, new, tier="capital"):
    return {
        "item": item, "team_id_master": tid, "team_name": f"Team {tid}", "field": "club_name", "old_value": old,
        "new_value": new, "tier": tier, "source": "abbreviation", "needs_review": False, "approved": False,
    }  # fmt: skip


def _answer(item, old, new, verdict="apply", reason="the club writes it so"):
    return {"item": item, "old_value": old, "new_value": new, "verdict": verdict, "reason": reason}


ROWS = [
    _row("C0001", "t1", "United Socal", "United SoCal"),
    _row("C0001", "t2", "United Socal", "United SoCal"),
    _row("C0002", "t3", "Lonestar", "LSC White", tier="recased"),
]


def _slice(tmp_path, rows=ROWS, name="slice_01"):
    review = tmp_path / "review"
    (review / rm.ANSWERS_DIR).mkdir(parents=True, exist_ok=True)
    (review / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    (review / f"{name}.md").write_text(f"## evidence of {name}", encoding="utf-8")
    for brief in rc.BRIEFS:
        (review / brief).write_text(f"brief {brief}", encoding="utf-8")
    return review


# --- answers --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answers, message",
    [
        ([_answer("C0001", "United Socal", "United SoCal")], "one answer per change"),
        ([_answer("C0002", "Lonestar", "LSC White"), _answer("C0001", "United Socal", "United SoCal")], "C0001 in its"),
        ([_answer("C0001", "United socal", "United SoCal"), _answer("C0002", "Lonestar", "LSC White")], "C0001 in its"),
        ([_answer("C0001", "United Socal", "United SOCAL"), _answer("C0002", "Lonestar", "LSC White")], "C0001 in its"),
        ([_answer("C0001", "United Socal", "United SoCal", "merge"), _answer("C0002", "Lonestar", "LSC White")],
         "a verdict the brief"),
        ([_answer("C0001", "United Socal", "United SoCal", reason=" "), _answer("C0002", "Lonestar", "LSC White")],
         "no reason"),
        ([_answer("C0001", "United Socal", "United SoCal")] * 2 + [_answer("C0002", "Lonestar", "LSC White")],
         "one answer per change"),
    ],
    ids=["short", "reordered", "old-value", "new-value", "merge-verdict", "blank-reason", "one-per-team"],
)
def test_an_answer_must_judge_each_change_once_in_order_with_a_verdict_and_a_reason(tmp_path, answers, message):
    path = tmp_path / "verdicts.json"
    path.write_text(json.dumps(answers), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        rc.read_verdicts(path, ROWS)


def test_each_change_s_verdict_reaches_every_team_and_an_unupheld_reject_is_a_hold():
    verdicts = [_answer("C0001", "United Socal", "United SoCal"), _answer("C0002", "Lonestar", "LSC White", "reject",
                                                                         "a squad label")]  # fmt: skip

    upheld = rc.final_rows(ROWS, verdicts, {"C0002": {"item": "C0002", "upheld": True, "reason": "LSC is a squad"}})
    doubted = rc.final_rows(ROWS, verdicts, {"C0002": {"item": "C0002", "upheld": False, "reason": "LSC is the club"}})
    unread = rc.final_rows(ROWS, verdicts, {})

    assert [(r["team_id_master"], r["verdict"]) for r in upheld] == [("t1", "apply"), ("t2", "apply"), ("t3", "reject")]
    assert doubted[2]["verdict"] == unread[2]["verdict"] == "hold"
    assert doubted[2]["reason"] == (
        "one reviewer found the stored club right (a squad label), and a second did not uphold it: LSC is the club"
    )
    assert unread[2]["reason"] == (
        "one reviewer found the stored club right (a squad label), and a second did not uphold it"
    )


def test_a_slice_s_review_copies_its_rows_and_the_second_reviewer_rechecks_only_the_rejects(tmp_path):
    review = _slice(tmp_path)
    verdicts = [_answer("C0001", "United Socal", "United SoCal"), _answer("C0002", "Lonestar", "LSC White", "reject")]
    reviewers = _Reviewers([verdicts, [{"item": "C0002", "upheld": True, "reason": "a squad label"}]])

    left = rm.review_queued(review, CLAUDE, reviewers, rc.ITEMS)

    assert left == [] and rm.waiting(review, CHANGE_REVIEW_KEYS) == []
    assert check_reviews(review, CHANGE_REVIEW_KEYS) == ((), ())
    assert reviewers.commands[1][2].startswith("Read RECHECK.md in this folder and follow it. Recheck these changes "
                                               "from slice_01.md: C0002.")  # fmt: skip
    assert [f.name for f in reviewers.folders] == ["slice_01-review", "slice_01-recheck"]
    final = json.loads((review / f"slice_01{rm.REVIEW_SUFFIX}").read_text(encoding="utf-8"))
    assert [(r["item"], r["verdict"]) for r in final] == [("C0001", "apply"), ("C0001", "apply"), ("C0002", "reject")]


def test_three_failed_reviews_hold_every_team_of_the_slice(tmp_path):
    review = _slice(tmp_path)

    for _ in range(3):
        rm.review_queued(review, CLAUDE, _Reviewers([]), rc.ITEMS)

    final = json.loads((review / f"slice_01{rm.REVIEW_SUFFIX}").read_text(encoding="utf-8"))
    assert {r["verdict"] for r in final} == {"hold"} and len(final) == 3
    assert final[0]["reason"] == "the automatic review failed 3 times"


# --- choosing the changes ---------------------------------------------------------------------------


def _week(tmp_path, rows, teams, **tables):
    store = tmp_path / "store"
    pt._reviewing(store)
    pt._clubs(store, rows, tmp_path)
    return store, pt._Db(teams=teams, **tables)


GUESSES = [
    pt._scan_row("swapped", "LAS VEGAS SPORTS ACADEMY", "Las Vegas Sports Academy"),
    pt._scan_row("cap1", "United Socal", "United SoCal", tier="capital"),
    pt._scan_row("cap2", "United Socal", "United SoCal", tier="capital"),
    pt._scan_row("rec", "Lonestar", "LSC White", tier="recased"),
    pt._scan_row("unc", "Concorde Fire", "CF", tier="unclear"),
    pt._scan_row("blank", "Club Ohio", "", tier="unclear"),
    pt._scan_row("dec", "Solar SC", "SOLAR", tier="unclear"),
]
TEAMS = [pt._team(r["team_id_master"], club=r["stored_club"]) for r in GUESSES]
DECLINED = [pt._declined("dec", "SOLAR", stage="clubs", field="club_name")]
UNDONE = {"id": 1, "stage": "clubs", "team_id_master": "undone", "field": "club_name", "new_value": "LSC Blue",
          "reverted_at": "2026-10-10T00:00:00+00:00"}  # fmt: skip


def test_the_review_takes_each_guess_once_never_one_settled_blank_declined_undone_stale_gone_or_moved(tmp_path):
    late = [pt._scan_row(tid, "Lonestar", f"LSC {tid}", tier="recased") for tid in ("stale", "gone", "moved")]
    rows = [*GUESSES, pt._scan_row("undone", "Lonestar", "LSC Blue", tier="recased"), *late]
    teams = [*TEAMS, pt._team("undone", club="Lonestar"), pt._team("stale", club="Lonestar"),
             pt._team("moved", club="Lonestar FC")]  # fmt: skip
    store, db = _week(tmp_path, rows, teams, team_cleanup_decisions=DECLINED, team_cleanup_changes=[UNDONE])
    folder = pt.stage_dir(store, pt.RUN, "clubs")
    pt.write_json(folder / pt.STALE_FILE, [{"team_id_master": "stale", "field": "club_name", "changed": "renamed"}])

    taken, _ = rc.review_changes(db, folder, 100)

    assert [(r["item"], r["team_id_master"]) for r in taken] == [
        ("C0001", "cap1"), ("C0001", "cap2"), ("C0002", "rec"), ("C0003", "unc"),
    ]  # fmt: skip
    assert [r["item"] for r in rc.review_changes(db, folder, 1)[0]] == ["C0001", "C0001"]


def test_a_team_whose_sources_disagree_is_a_change_of_its_own(tmp_path, capsys):
    """The offers come back from what the club scan printed into the log of the stage's one proposal step."""
    store, db = _week(tmp_path, GUESSES[1:3], TEAMS[1:3])
    folder = pt.stage_dir(store, pt.RUN, "clubs")
    offers = [{"source": "abbreviation", "proposed_club": "United SoCal"},
              {"source": "team_name", "proposed_club": "United"}]  # fmt: skip
    stats = {"playmetrics_unlisted": 0, "team_name_outcomes": {}, "abbreviation_renames": {"word": 0, "bracket": 0,
             "capital": 0}, "conflicts": [("cap2", offers)]}  # fmt: skip
    pt.swapped.print_summary([], stats)
    assert [command[0] for command in pt.pw.stage_commands("clubs", folder, ["NV"], store)] == [pt.pw.SWAPPED_CLUBS]
    log = pt.pw.step_log(folder, 1, pt.pw.SWAPPED_CLUBS)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(capsys.readouterr().out, encoding="utf-8")

    taken, _ = rc.review_changes(db, folder, 100)

    assert [(r["item"], r["team_id_master"]) for r in taken] == [("C0001", "cap1"), ("C0002", "cap2")]
    blocks = rc.evidence_blocks(db, taken, rc.review_changes(db, folder, 100)[1], folder)
    assert (
        "two sources disagree on cap2: abbreviation proposes 'United SoCal'; team_name proposes 'United'"
    ) in blocks[1]


def test_a_change_never_splits_across_slices_and_the_briefs_name_the_lookup(tmp_path, monkeypatch):
    store, db = _week(tmp_path, GUESSES, TEAMS)
    folder = pt.stage_dir(store, pt.RUN, "clubs")
    monkeypatch.setattr(rc, "SLICE_ITEMS", 1)

    assert rc.queue(db, folder, 100) == (4, 5)

    review = folder / "review"
    first = json.loads((review / "slice_01.json").read_text(encoding="utf-8"))
    assert [r["team_id_master"] for r in first] == ["cap1", "cap2"]
    assert [p.name for p in sorted(review.glob("slice_*.json"))] == [f"slice_0{n}.json" for n in range(1, 5)]
    brief = (review / "BRIEF.md").read_text(encoding="utf-8")
    assert f"python {rm.LOOKUP} spellings <text> [<state>]" in brief and "{lookup}" not in brief
    assert rm.waiting(review, CHANGE_REVIEW_KEYS) == ["slice_01", "slice_02", "slice_03", "slice_04"]


def test_the_evidence_shows_each_spelling_s_live_teams_by_state_and_what_the_change_covers(tmp_path):
    teams = [*TEAMS, pt._team("ca1", club="United Socal", state="CA"), pt._team("ca2", club="United SoCal", state="CA"),
             pt._team("old", club="United Socal", state="CA", deprecated=True)]  # fmt: skip
    store, db = _week(tmp_path, GUESSES, teams)
    folder = pt.stage_dir(store, pt.RUN, "clubs")
    taken, chosen = rc.review_changes(db, folder, 100)

    block = rc.evidence_blocks(db, taken, chosen, folder)[0]

    assert block.splitlines()[:5] == [
        '## C0001 "United Socal" -> "United SoCal"',
        "2 team(s): NV 2 | tier capital (team_name) x2 | needs review: no",
        "how it was proposed: " + rc.HOW["capital"],
        'live teams holding "United Socal": NV 2, CA 1 (this change covers 2 of 3)',
        'live teams already holding "United SoCal": CA 1',
    ]
    assert "   gotsport NV u12 Male | 'Team cap1' | registered: None" in block


def test_the_evidence_header_holds_each_name_as_the_json_string_the_answer_copies(tmp_path):
    odd = 'Club "Elite"\u00a0\\ It\'s'
    rows = [pt._scan_row("odd", "Club Elite", odd, tier="recased")]
    store, db = _week(tmp_path, rows, [pt._team("odd", club="Club Elite")])
    folder = pt.stage_dir(store, pt.RUN, "clubs")
    taken, chosen = rc.review_changes(db, folder, 100)

    header = rc.evidence_blocks(db, taken, chosen, folder)[0].splitlines()[0]

    old, new = re.fullmatch(r"## C0001 (.+) -> (.+)", header).groups()
    assert (json.loads(old), json.loads(new)) == ("Club Elite", odd)


def test_a_spelling_count_asks_for_a_name_holding_a_quote_or_a_backslash_alone_and_counts_live_teams():
    db = pt._Db(teams=[pt._team("q", club='Club "Elite"'), pt._team("b", club="Back\\slash", state="CA"),
                       pt._team("p", club="Plain"), pt._team("old", club="Plain", deprecated=True)])  # fmt: skip

    counts = rc.spelling_counts(db, ['Club "Elite"', "Back\\slash", "Plain", ""])

    assert counts == {'Club "Elite"': Counter(NV=1), "Back\\slash": Counter(CA=1), "Plain": Counter(NV=1)}


# --- the review, the page and the automatic lane together -------------------------------------------


class _ClubPanel:
    """Headless reviewers answering each change by its proposed name from the evidence copied into their own
    folder: ``verdicts`` maps it to a verdict, and every reject is upheld."""

    def __init__(self, verdicts):
        self.verdicts, self.folders = verdicts, []

    def __call__(self, command, cwd, log):
        work = Path(cwd)
        self.folders.append(work)
        log.write_text("ran", encoding="utf-8")
        name, kind = work.name.rsplit("-", 1)
        evidence = (work / f"{name}.md").read_text(encoding="utf-8")
        if kind == "review":
            answer = []
            for label, old, new in re.findall(r"^## (C\d{4}) (.+) -> (.+)$", evidence, re.M):
                old, new = json.loads(old), json.loads(new)
                answer.append(_answer(label, old, new, self.verdicts[new], f"because {new}"))
        else:
            labels = re.search(r"from \S+\.md: (.+)\. Write", command[2]).group(1).split(", ")
            answer = [{"item": label, "upheld": True, "reason": "a squad label"} for label in labels]
        (work / _allowed(command)).write_text(json.dumps(answer), encoding="utf-8")
        return 0


def _main(monkeypatch, capsys, store, db, runner, *flags):
    monkeypatch.setattr(rc, "get_client", lambda: db)
    monkeypatch.setattr(rm.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(rm, "run_reviewer", runner)
    argv = ["review_clubs.py", "--run", pt.RUN, "--stage", "clubs", "--store", str(store), *flags]
    monkeypatch.setattr(sys, "argv", argv)
    try:
        code = rc.main()
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr().out


def test_the_review_s_verdicts_reach_the_lanes_and_a_found_wrong_guess_is_recorded_declined(
    tmp_path, monkeypatch, capsys
):
    """Selection, evidence, reviewers, the page and the automatic lane's collect together: an approved change
    and an approved tier apply on their own, an upheld reject goes to the lane kept as it is and is recorded
    Don't apply, a hold is a card, and a blank or declined guess never reaches a reviewer."""
    store, db = _week(tmp_path, GUESSES, TEAMS, team_cleanup_decisions=DECLINED)
    panel = _ClubPanel({"United SoCal": "apply", "LSC White": "reject", "CF": "hold"})

    code, out = _main(monkeypatch, capsys, store, db, panel, "--execute")

    assert code == 0 and "reviewed changes: 1 apply, 1 hold, 1 reject" in out
    assert {f.name for f in panel.folders} == {"slice_01-review", "slice_01-recheck"}

    code, _ = pt._publish(monkeypatch, capsys, store, db, "--publish", "--execute", stage="clubs")

    manifest = pt._read(store, "clubs", MANIFEST_FILE)
    assert code == 0
    assert sorted(p["team_id_master"] for p in manifest["auto"].values()) == ["cap1", "cap2", "rec", "swapped"]
    assert [p["team_id_master"] for p in manifest["cards"].values()] == ["unc"]
    assert {p["team_id_master"]: p["why"] for p in manifest["left_out"]} == {
        "blank": "the scan proposes no club",
        "dec": "declined on 2026-10-01",
    }
    kept = {r["card"]["change"]["new"]: r["card"]["keep_as_is"] for r in db.cards(lane="auto")}
    assert kept == {"United SoCal": False, "LSC White": True, "Las Vegas Sports Academy": False}
    assert {r["decision"] for r in db.cards(lane="auto")} == {"apply"}
    held = db.cards(lane="owner")[0]["card"]
    assert held["why"] == "Reviewers held it: because CF"

    code, _ = pt._collect_auto(monkeypatch, capsys, store, "clubs")

    lane = pt.stage_dir(store, pt.RUN, "clubs") / "auto"
    decided = {r["team_id_master"]: r["decision"] for r in json.loads((lane / "decisions.json").read_text())}
    assert code == 0
    assert decided == {"swapped": "apply", "cap1": "apply", "cap2": "apply", "rec": "dont_apply"}
    vetted = (lane / "vetted.csv").read_text(encoding="utf-8")
    assert "cap1" in vetted and "swapped" in vetted and "rec" not in vetted


def test_a_listed_guess_the_review_did_not_reach_stays_off_both_lanes(tmp_path, monkeypatch, capsys):
    rows = [*GUESSES, pt._scan_row("undone", "Lonestar", "LSC Blue", tier="recased")]
    teams = [*TEAMS, pt._team("undone", club="Lonestar")]
    store, db = _week(tmp_path, rows, teams, team_cleanup_decisions=DECLINED, team_cleanup_changes=[UNDONE])
    panel = _ClubPanel({"United SoCal": "apply", "LSC White": "apply", "CF": "apply"})
    _main(monkeypatch, capsys, store, db, panel, "--execute")

    code, _ = pt._publish(monkeypatch, capsys, store, db, "--publish", "--execute", stage="clubs")

    manifest = pt._read(store, "clubs", MANIFEST_FILE)
    assert code == 0
    assert "undone" not in {p["team_id_master"] for lane in ("auto", "cards") for p in manifest[lane].values()}
    assert {p["team_id_master"]: p["why"] for p in manifest["left_out"]}["undone"] == (
        "the scan lists recased guesses without approving them"
    )


def test_a_clubs_scan_that_proposed_nothing_queues_an_empty_review_and_its_page_builds(tmp_path, monkeypatch, capsys):
    store, db = tmp_path / "store", pt._Db(teams=[])
    pt._reviewing(store)
    pt._folder(store, "clubs", [])  # with no applier input, as the propose step leaves a scan that found nothing

    code, out = _main(monkeypatch, capsys, store, db, _ClubPanel({}), "--execute")

    assert code == 0 and "queued 0 change(s) of 0 team(s) for review" in out
    code, _ = pt._publish(monkeypatch, capsys, store, db, "--publish", "--execute", stage="clubs")
    assert code == 0


def test_a_dry_run_queues_nothing_and_says_what_it_would_review(tmp_path, monkeypatch, capsys):
    store, db = _week(tmp_path, GUESSES, TEAMS, team_cleanup_decisions=DECLINED)

    code, out = _main(monkeypatch, capsys, store, db, _ClubPanel({}))

    assert code == 0 and "DRY RUN -- would queue 3 change(s) of 4 team(s) for review" in out
    assert not (pt.stage_dir(store, pt.RUN, "clubs") / "review").exists()


def test_slices_past_the_run_s_budget_wait_for_the_next_run(tmp_path, monkeypatch, capsys):
    store, db = _week(tmp_path, GUESSES, TEAMS, team_cleanup_decisions=DECLINED)
    monkeypatch.setattr(rc, "SLICE_ITEMS", 1)
    monkeypatch.setattr(rm, "RUN_SLICES", 1)
    panel = _ClubPanel({"United SoCal": "apply", "LSC White": "reject", "CF": "hold"})

    code, out = _main(monkeypatch, capsys, store, db, panel, "--execute")

    assert code == 75 and "2 slice(s) wait for the next run: slice_02, slice_03" in out


def test_the_clubs_page_waits_for_its_review(tmp_path, monkeypatch, capsys):
    store, db = _week(tmp_path, GUESSES, TEAMS)

    with pytest.raises(SystemExit, match="its guesses are not reviewed yet: run review_clubs.py --execute"):
        pt._build(monkeypatch, capsys, store, db, stage="clubs")


# --- the spellings lookup ---------------------------------------------------------------------------


def test_the_spellings_lookup_counts_each_spelling_s_teams_by_state_with_the_public_key(monkeypatch, capsys):
    opened = []
    db = _LookupDb(providers=[{"id": 1, "code": "gotsport"}], teams=[
        _lookup_team("a", "A 2014", club="United SoCal"), _lookup_team("b", "B 2014", club="United Socal"),
        {**_lookup_team("c", "C 2014", club="United SoCal"), "state_code": "CA"},
        _lookup_team("d", "D 2014", club="Real United SoCal", deprecated=True),
    ])  # fmt: skip
    monkeypatch.setattr(lookup, "create_client", lambda url, key: opened.append(key) or db)
    monkeypatch.setenv("SUPABASE_URL", "u")
    monkeypatch.setenv("SUPABASE_KEY", "public")
    monkeypatch.setattr(sys, "argv", ["review_lookup.py", "spellings", "socal"])

    assert lookup.main() == 0

    assert capsys.readouterr().out.splitlines() == [
        "    2  'United SoCal'  (CA 1, FL 1)",
        "    1  'United Socal'  (FL 1)",
        "2 spelling(s), 3 team(s)",
    ]
    assert opened == ["public"]


def test_the_spellings_lookup_keeps_to_a_state_and_says_when_it_read_only_part(monkeypatch, capsys):
    db = _LookupDb(providers=[{"id": 1, "code": "gotsport"}], teams=[
        _lookup_team("a", "A 2014", club="United SoCal"), {**_lookup_team("b", "B 2014", club="United SoCal"),
        "state_code": "CA"}, {**_lookup_team("c", "C 2014", club="United Socal"), "state_code": "CA"},
    ])  # fmt: skip
    monkeypatch.setattr(lookup, "create_client", lambda url, key: db)
    monkeypatch.setenv("SUPABASE_URL", "u")
    monkeypatch.setenv("SUPABASE_KEY", "public")
    monkeypatch.setattr(sys, "argv", ["review_lookup.py", "spellings", "socal", "CA"])

    assert lookup.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "    1  'United SoCal'  (CA 1)",
        "    1  'United Socal'  (CA 1)",
        "2 spelling(s), 2 team(s)",
    ]

    monkeypatch.setattr(lookup, "SPELLINGS_READ", 2)
    monkeypatch.setattr(sys, "argv", ["review_lookup.py", "spellings", "socal"])

    assert lookup.main() == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "more than 2 teams hold the text; the counts cover the first 2 by id"
    )


@pytest.mark.parametrize("argv", [["spellings", "so"], ["spellings", "Socal", "California"],
                                  ["spellings", "Socal", "CA", "Male"]], ids=["short", "state", "gender"])  # fmt: skip
def test_the_spellings_lookup_refuses_anything_but_a_plain_text_and_a_state(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["review_lookup.py", *argv])
    monkeypatch.setattr(lookup, "public_client", lambda: pytest.fail("a refused lookup opens no client"))

    with pytest.raises(SystemExit) as exited:
        lookup.main()

    assert exited.value.code == 2
