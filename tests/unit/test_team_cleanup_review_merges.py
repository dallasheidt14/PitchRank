"""Tests for the weekly cleanup's unattended review of its duplicate pairs, and the lookups its reviewers run."""

import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup import pages  # noqa: E402
from scripts.team_cleanup import review_lookup as lookup  # noqa: E402
from scripts.team_cleanup import review_merges as rm  # noqa: E402
from scripts.team_cleanup.run_store import MANIFEST_FILE, MERGE_REVIEW_KEYS, check_reviews, write_run  # noqa: E402
from tests.unit import test_team_cleanup_pages as pt  # noqa: E402

CLAUDE = "claude"
SEASON = int(rm.SEASON_START[:4])


def _day(month, day, year=SEASON):
    return f"{year}-{month:02d}-{day:02d}"


def _rows(*pairs):
    return [
        {"pair": f"P{n:04d}", "merge_id": m, "keep_id": k, "merge_name": f"Team {m}", "keep_name": f"Team {k}"}
        for n, (m, k) in enumerate(pairs, 1)
    ]


def _answer(row, verdict="merge", swap=False, reason="same squad"):
    return {"pair": row["pair"], "merge_id": row["merge_id"], "keep_id": row["keep_id"], "verdict": verdict,
            "swap": swap, "reason": reason}  # fmt: skip


def _slice(tmp_path, rows, name="slice_01"):
    """A queued slice as queue() leaves it: its pairs, its evidence and both briefs."""
    review = tmp_path / "review"
    (review / rm.ANSWERS_DIR).mkdir(parents=True)
    (review / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    (review / f"{name}.md").write_text(f"## evidence of {name}", encoding="utf-8")
    for brief in rm.BRIEFS:
        (review / brief).write_text(f"brief {brief}", encoding="utf-8")
    return review


def _allowed(command):
    """The one file a reviewer command lets the reviewer write, read from its Edit rule."""
    return next(arg[len("Edit(/") : -1] for arg in command if arg.startswith("Edit(/"))


class _Reviewers:
    """Stands in for headless Claude in its own folder: records each command, refuses a write to any file but the
    one the command allows, as Claude Code does, and writes the next answer in ``answers`` there, or nothing."""

    def __init__(self, answers):
        self.answers, self.commands, self.folders = list(answers), [], []

    def __call__(self, command, cwd, log):
        self.commands.append(command)
        self.folders.append(Path(cwd))
        log.write_text("ran", encoding="utf-8")
        target = re.search(r"Write your \w+ to (\S+) in this folder", command[2]).group(1)
        assert target == _allowed(command), "Claude Code refuses a write the command does not allow"
        answer = self.answers.pop(0) if self.answers else None
        if answer is not None:
            (Path(cwd) / target).write_text(json.dumps(answer), encoding="utf-8")
        return 0

    def kinds(self):
        return ["recheck" if "RECHECK.md" in c[2] else "review" for c in self.commands]


def _final(review, name="slice_01"):
    return json.loads((review / f"{name}{rm.REVIEW_SUFFIX}").read_text(encoding="utf-8"))


def test_a_reviewer_loads_no_settings_reads_only_its_folder_writes_its_answer_and_runs_only_the_lookup():
    assert rm.reviewer_command(CLAUDE, "go", "verdicts.json") == [
        "claude",
        "-p",
        "go",
        "--model",
        "opus",
        "--setting-sources",
        "",
        "--settings",
        '{"permissions": {"blockReadsOutsideWorkingDirectories": true}}',
        "--permission-mode",
        "dontAsk",
        "--tools",
        "Read,Write,Bash",
        "--allowedTools",
        "Read(./**)",
        "Edit(/verdicts.json)",
        f"Bash(python {rm.LOOKUP}:*)",
        "--add-dir",
        rm.LOOKUP.rsplit("/", 1)[0],
        "--strict-mcp-config",
        "--no-session-persistence",
        "--output-format",
        "text",
    ]
    assert rm.LOOKUP.endswith("scripts/team_cleanup/review_lookup.py") and "\\" not in rm.LOOKUP


def test_a_reviewer_runs_in_its_folder_s_full_path_with_no_input_and_no_secret(tmp_path, monkeypatch):
    """Claude Code matches the write permission against the full path, so a dotted or short one refuses every write;
    and the reviewer's environment holds the public key the lookups read with, never a private one."""
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rm.subprocess, "run", run)
    for key, value in {"SUPABASE_URL": "u", "SUPABASE_KEY": "public", "SUPABASE_SERVICE_ROLE_KEY": "private",
                       "STRIPE_SECRET_KEY": "stripe", "RESEND_API_KEY": "resend",
                       "SOME_TOKEN_NOBODY_LISTED": "canary"}.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    (tmp_path / "review").mkdir()

    assert rm.run_reviewer(["claude"], tmp_path / "review" / ".." / "review", tmp_path / "log.txt") == 0
    assert seen["cwd"] == os.path.realpath(tmp_path / "review") and seen["stdin"] is rm.subprocess.DEVNULL
    assert (seen["env"].get("SUPABASE_URL"), seen["env"].get("SUPABASE_KEY")) == ("u", "public")
    assert not {"SUPABASE_SERVICE_ROLE_KEY", "STRIPE_SECRET_KEY", "RESEND_API_KEY"} & set(seen["env"])
    assert "canary" not in seen["env"].values() and seen["env"]["PATH"] == os.environ["PATH"]
    assert {key: seen["env"][key] for key in ("PYTHONUTF8", "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
                                              "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR")} == dict.fromkeys(
        ("PYTHONUTF8", "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR"), "1"
    )  # fmt: skip


@pytest.mark.parametrize(
    "spoil, message",
    [
        (lambda a: a[:-1], "one answer per pair"),
        (lambda a: [a[1], a[0]], "does not answer P0001 in its place"),
        (lambda a: [{**a[0], "keep_id": "other"}, a[1]], "does not answer P0001 in its place"),
        (lambda a: [{**a[0], "verdict": "maybe"}, a[1]], "a verdict or swap the brief does not allow"),
        (lambda a: [{**a[0], "swap": "yes"}, a[1]], "a verdict or swap the brief does not allow"),
        (lambda a: [{**a[0], "reason": "  "}, a[1]], "no reason"),
    ],
    ids=["short", "reordered", "wrong-row", "verdict", "swap", "reason"],
)
def test_an_answer_that_skips_reorders_or_invents_is_refused(tmp_path, spoil, message):
    rows = _rows(("m1", "k1"), ("m2", "k2"))
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(spoil([_answer(r) for r in rows])), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        rm.read_verdicts(path, rows)


def test_a_recheck_must_answer_the_rejects_in_order_with_a_flag_and_a_reason(tmp_path):
    path = tmp_path / "recheck.json"
    path.write_text(json.dumps([{"pair": "P0002", "upheld": True, "reason": "x"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="does not answer the rejects P0001"):
        rm.read_recheck(path, ["P0001"])
    path.write_text(json.dumps([{"pair": "P0001", "upheld": "yes", "reason": "x"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="no upheld flag"):
        rm.read_recheck(path, ["P0001"])


def test_only_an_upheld_reject_stays_a_reject_and_only_a_merge_keeps_a_swap():
    rows = _rows(("m1", "k1"), ("m2", "k2"), ("m3", "k3"), ("m4", "k4"))
    verdicts = [
        _answer(rows[0], "reject", reason="2008 vs 2009"),
        _answer(rows[1], "reject", reason="Blue vs Red"),
        _answer(rows[2], "hold", swap=True),
        _answer(rows[3], "merge", swap=True),
    ]
    recheck = {"P0001": {"pair": "P0001", "upheld": True, "reason": "x"},
               "P0002": {"pair": "P0002", "upheld": False, "reason": "colour is a kit"}}  # fmt: skip

    final = rm.final_rows(rows, verdicts, recheck)

    assert [(r["verdict"], r["swap"]) for r in final] == [
        ("reject", False), ("hold", False), ("hold", False), ("merge", True)
    ]  # fmt: skip
    assert final[1]["reason"] == (
        "one reviewer found two teams (Blue vs Red), and a second did not uphold it: colour is a kit"
    )
    assert rm.final_rows(rows[:1], verdicts[:1], {})[0]["verdict"] == "hold"


def test_each_reviewer_works_in_its_own_folder_and_the_second_never_sees_the_first_s_answer(tmp_path):
    rows = _rows(("m1", "k1"), ("m2", "k2"))
    review = _slice(tmp_path, rows)
    reviewers = _Reviewers([
        [_answer(rows[0]), _answer(rows[1], "reject", reason="2008 vs 2009")],
        [{"pair": "P0002", "upheld": True, "reason": "the bands differ"}],
    ])  # fmt: skip

    settled, failures = rm.review_slice(review, "slice_01", 0, CLAUDE, reviewers)

    first, second = reviewers.folders
    assert (settled, failures) == (True, 0)
    assert reviewers.kinds() == ["review", "recheck"]
    assert (first.name, second.name) == ("slice_01-review", "slice_01-recheck")
    assert sorted(p.name for p in first.iterdir()) == ["BRIEF.md", "slice_01.md", "verdicts.json"]
    assert sorted(p.name for p in second.iterdir()) == ["BRIEF.md", "RECHECK.md", "recheck.json", "slice_01.md"]
    assert "P0002" in reviewers.commands[1][2] and "P0001" not in reviewers.commands[1][2]
    assert [r["verdict"] for r in _final(review)] == ["merge", "reject"]
    assert check_reviews(review, MERGE_REVIEW_KEYS) == ((), ())


def test_an_answer_another_reviewer_forged_is_never_read(tmp_path):
    """A reviewer may write only into its own folder, so a recheck file it left in the review's answers folder is
    not the second reviewer's answer: the second reviewer still runs."""
    rows = _rows(("m1", "k1"))
    review = _slice(tmp_path, rows)
    forged = [{"pair": "P0001", "upheld": True, "reason": "forged"}]
    (review / rm.ANSWERS_DIR / "slice_01_recheck.json").write_text(json.dumps(forged), encoding="utf-8")
    (review / rm.ANSWERS_DIR / "recheck.json").write_text(json.dumps(forged), encoding="utf-8")
    reviewers = _Reviewers([[_answer(rows[0], "reject")], [{"pair": "P0001", "upheld": False, "reason": "no"}]])

    rm.review_slice(review, "slice_01", 0, CLAUDE, reviewers)

    assert reviewers.kinds() == ["review", "recheck"]
    assert _final(review)[0]["verdict"] == "hold"


def test_a_slice_with_no_reject_needs_no_second_reviewer(tmp_path):
    rows = _rows(("m1", "k1"))
    review = _slice(tmp_path, rows)
    reviewers = _Reviewers([[_answer(rows[0], "hold")]])

    assert rm.review_slice(review, "slice_01", 0, CLAUDE, reviewers) == (True, 0)
    assert reviewers.kinds() == ["review"]


def test_a_reviewer_that_writes_nothing_is_retried_and_after_three_failures_every_pair_is_held(tmp_path):
    rows = _rows(("m1", "k1"), ("m2", "k2"))
    review = _slice(tmp_path, rows)
    reviewers = _Reviewers([])

    assert rm.review_slice(review, "slice_01", 0, CLAUDE, reviewers) == (False, 1)
    assert not (review / f"slice_01{rm.REVIEW_SUFFIX}").exists()
    assert rm.review_slice(review, "slice_01", 2, CLAUDE, reviewers) == (True, 3)

    assert {(r["verdict"], r["reason"]) for r in _final(review)} == {("hold", "the automatic review failed 3 times")}
    assert check_reviews(review, MERGE_REVIEW_KEYS) == ((), ())


def test_an_answer_already_given_is_not_bought_again_and_a_failed_recheck_holds_the_rejects(tmp_path):
    rows = _rows(("m1", "k1"), ("m2", "k2"))
    review = _slice(tmp_path, rows)
    own = review / rm.ANSWERS_DIR / "slice_01-review"
    own.mkdir()
    (own / "verdicts.json").write_text(json.dumps([_answer(rows[0]), _answer(rows[1], "reject")]), encoding="utf-8")
    reviewers = _Reviewers([])

    assert rm.review_slice(review, "slice_01", 2, CLAUDE, reviewers) == (True, 3)

    assert reviewers.kinds() == ["recheck"]
    assert [r["verdict"] for r in _final(review)] == ["merge", "hold"]


def test_the_queue_reviews_every_waiting_slice_and_keeps_each_one_s_failures(tmp_path):
    rows = _rows(("m1", "k1"))
    review = _slice(tmp_path, rows)
    second = _rows(("m2", "k2"))
    (review / "slice_02.json").write_text(json.dumps(second), encoding="utf-8")
    reviewed = [{**second[0], "verdict": "hold", "swap": False, "reason": "x"}]
    (review / f"slice_02{rm.REVIEW_SUFFIX}").write_text(json.dumps(reviewed), encoding="utf-8")

    left = rm.review_queued(review, CLAUDE, _Reviewers([]))

    assert left == ["slice_01"]
    assert json.loads((review / rm.ANSWERS_DIR / rm.ATTEMPTS_FILE).read_text(encoding="utf-8")) == {"slice_01": 1}
    assert rm.waiting(review) == ["slice_01"]


def test_queueing_writes_slices_of_fifty_their_evidence_and_briefs_for_this_season(tmp_path, monkeypatch):
    pairs = [{"merge_id": f"m{n}", "keep_id": f"k{n}", "merge_name": "a", "keep_name": "b"} for n in range(51)]
    monkeypatch.setattr(rm, "review_pairs", lambda sb, folder, cap: (pairs[:cap], None))
    monkeypatch.setattr(rm, "evidence_blocks", lambda sb, labelled, chosen: [f"## {p['pair']}" for p in labelled])
    monkeypatch.setattr(rm, "SEASON_START", "2027-08-01")

    assert rm.queue(None, tmp_path, 1000) == 51

    review = tmp_path / rm.REVIEW_DIR
    first = json.loads((review / "slice_01.json").read_text(encoding="utf-8"))
    brief = (review / "BRIEF.md").read_text(encoding="utf-8")
    assert [len(json.loads((review / f"slice_0{n}.json").read_text())) for n in (1, 2)] == [50, 1]
    assert (first[0]["pair"], first[-1]["pair"]) == ("P0001", "P0050")
    assert (review / "slice_02.md").read_text(encoding="utf-8") == "## P0051"
    assert f"python {rm.LOOKUP} team <team id>" in brief
    assert "The 2027-28 season: birth year 2019 = U9" in brief and "`15B` is birth year 2015, boys, = U13" in brief
    assert "{lookup}" not in brief and "{cohorts}" not in brief
    assert (review / rm.ANSWERS_DIR).is_dir() and rm.waiting(review) == ["slice_01", "slice_02"]


def test_the_cohort_rules_name_this_season_s_bands():
    assert rm.cohort_rules(2026) == (
        "**Cohort.** The 2026-27 season: birth year 2018 = U9, 2017 = U10, 2016 = U11, 2015 = U12, 2014 = U13, "
        "2013 = U14, 2012 = U15, 2011 = U16, 2010 = U17, 2009 and 2008 = U19 (no U18 board), 2007 = U19.\n"
        "  `14B` is birth year 2014, boys, = U13. A two-year band is named by its YOUNGER year:\n"
        "  `2014/15`, `14/15`, `2015/2014` are all U12 (2026 - 2015 + 1); `2013/14` is U13."
    )


def test_a_review_of_no_pair_leaves_its_folder_so_the_autopilot_moves_on(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "review_pairs", lambda sb, folder, cap: ([], None))
    monkeypatch.setattr(rm, "evidence_blocks", lambda *_: [])

    assert rm.queue(None, tmp_path, 1000) == 0
    assert (tmp_path / rm.REVIEW_DIR).is_dir() and rm.waiting(tmp_path / rm.REVIEW_DIR) == []


def test_the_adjacent_days_cross_a_month_and_need_another_event():
    mine = {_day(9, 30): {"League"}, _day(10, 11): {"Cup"}}
    theirs = {_day(10, 1): {"Showcase"}, _day(10, 12): {"Cup"}}

    assert rm.adjacent_days(mine, theirs) == [_day(9, 30)]
    assert rm.adjacent_days(theirs, mine) == [_day(10, 1)]


# --- the evidence a reviewer reads --------------------------------------------------------------------

COLUMNS = {
    "providers": {"id", "code"},
    "teams": {
        "team_id_master", "team_name", "team_name_original", "club_name", "age_group", "gender", "state_code",
        "provider_id", "provider_team_id", "is_deprecated", "last_played_at",
    },
    "games": {
        "id", "game_date", "home_team_master_id", "away_team_master_id", "home_score", "away_score",
        "home_provider_id", "away_provider_id", "event_name", "competition", "division_name", "is_excluded",
    },
    "team_alias_map": {"id", "team_id_master", "provider_id", "provider_team_id", "match_method"},
    "team_merge_map": {"id", "deprecated_team_id", "canonical_team_id"},
}  # fmt: skip
ROW_CAP = 1000


class _Query:
    """A read, refusing an unknown column, a list too long for the URL and a ranged page with no order, and answering
    at most ROW_CAP rows, as PostgREST does."""

    def __init__(self, rows, table, columns):
        for column in columns:
            assert column in COLUMNS[table], f"PostgREST refuses unknown column {table}.{column}"
        self._rows, self._table, self._columns, self._tests = rows, table, columns, []
        self._order, self._range, self._limit = [], None, None

    def _where(self, column, test):
        assert column in COLUMNS[self._table], f"PostgREST refuses unknown column {self._table}.{column}"
        self._tests.append(test)
        return self

    def in_(self, column, values):
        values = list(values)
        assert len(values) <= 100, "an id list this long overflows the URL"
        return self._where(column, lambda r: r[column] in values)

    def eq(self, column, value):
        return self._where(column, lambda r: r[column] == value)

    def ilike(self, column, pattern):
        assert pattern.startswith("%") and pattern.endswith("%")
        return self._where(column, lambda r: pattern[1:-1].lower() in (r[column] or "").lower())

    def order(self, column):
        assert column in COLUMNS[self._table]
        self._order.append(column)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, size):
        self._limit = size
        return self

    def execute(self):
        assert self._order or self._range is None, "a page with no order is arbitrary"
        found = [r for r in self._rows if all(test(r) for test in self._tests)]
        found.sort(key=lambda r: tuple((r[c] is None, str(r[c] or "")) for c in self._order))
        if self._range:
            found = found[self._range[0] : self._range[1] + 1]
        if self._limit is not None:
            found = found[: self._limit]
        return SimpleNamespace(data=[{c: r[c] for c in self._columns} for r in found[:ROW_CAP]])


class _Db:
    def __init__(self, **tables):
        self.tables = tables

    def table(self, name):
        rows = self.tables.get(name, [])

        class _T:
            def select(self, columns):
                return _Query(rows, name, [c.strip() for c in columns.split(",")])

        return _T()


def _team(tid, name, *, club="Kraze", age="u11", gender="Male", original=None, deprecated=False):
    return {
        "team_id_master": tid, "team_name": name, "team_name_original": original, "club_name": club,
        "age_group": age, "gender": gender, "state_code": "FL", "provider_id": 1, "provider_team_id": f"p-{tid}",
        "is_deprecated": deprecated, "last_played_at": _day(10, 18),
    }  # fmt: skip


def _game(n, day, home, away, *, registration="1", event="League", excluded=False, score=(1, 0)):
    return {
        "id": n, "game_date": day, "home_team_master_id": home, "away_team_master_id": away, "home_score": score[0],
        "away_score": score[1], "home_provider_id": registration, "away_provider_id": "x", "event_name": event,
        "competition": None, "division_name": None, "is_excluded": excluded,
    }  # fmt: skip


def _selection(merge_map):
    return SimpleNamespace(merge_map=merge_map, canonical=lambda t: merge_map.get(t, t))


def test_the_evidence_names_rows_merged_in_days_two_registrations_played_and_the_club_s_other_rows():
    teams = [
        _team("retire", "16B Kraze Black"),
        _team("keep", "2016 Kraze Black U11"),
        _team("absorbed", "16 Kraze Black", original="B2015 Kraze Black", deprecated=True),
        _team("sister", "2016 Kraze Blue"),
        _team("opp", "Rivals 2016", club="Rivals"),
    ]
    games = [
        _game(1, _day(9, 6), "keep", "opp", registration="655599"),
        _game(2, _day(9, 6), "absorbed", "opp", registration="381917", event="Cup"),
    ]
    db = _Db(
        providers=[{"id": 1, "code": "gotsport"}],
        teams=teams,
        games=games,
        team_alias_map=[{"id": 1, "team_id_master": "keep", "provider_id": 1, "provider_team_id": "655599",
                         "match_method": "direct_id"}],  # fmt: skip
    )
    pair = {"pair": "P0001", "merge_id": "retire", "keep_id": "keep", "doorway": "D", "squad_key": "black",
            "club": "Kraze"}  # fmt: skip

    block = rm.evidence_blocks(db, [pair], _selection({"absorbed": "keep"}))[0]

    keep = block.split("KEEP: ", 1)[1]
    assert "merged into it earlier: B2015 Kraze Black" in keep
    assert f"days it played in two events: 1 {_day(9, 6)} (Cup / League)" in keep
    assert f"days two of its registrations played: 1 ['{_day(9, 6)}']" in keep
    assert "aliases: gotsport:655599" in keep
    assert "other live rows of the club in this cohort: 2016 Kraze Blue" in block
    assert "Rivals 2016 [u11 M]" in keep


def test_the_evidence_compares_the_two_rows_and_counts_as_the_card_does():
    """Each side of a head-to-head, a shared date, an adjacent day across a month in another event, an excluded game
    counted apart and a self-play game counted once: the figures the card shows and the brief's rules read."""
    teams = [_team("retire", "16B Kraze Black"), _team("keep", "2016 Kraze Black U11"),
             _team("x", "Rivals 2016", club="Rivals"), _team("y", "Hawks 2016", club="Hawks")]  # fmt: skip
    games = [
        _game(1, _day(9, 30), "retire", "x", event="Fall League"),
        _game(2, _day(10, 4), "retire", "keep", event="Cup", score=(2, 1)),
        _game(3, _day(10, 11), "retire", "x", excluded=True),
        _game(4, _day(10, 12), "retire", "retire"),
        _game(5, _day(10, 1), "keep", "y", event="Showcase"),
        _game(6, _day(10, 18), "keep", "x", event="Fall League"),
        _game(7, _day(5, 1), "keep", "x", event="Spring League"),
        _game(8, _day(10, 25), "keep", "retire", event="Friendly", excluded=True),
    ]
    db = _Db(providers=[{"id": 1, "code": "gotsport"}], teams=teams, games=games, team_alias_map=[])
    pair = {"pair": "P0001", "merge_id": "retire", "keep_id": "keep", "doorway": "D", "squad_key": "black",
            "club": "Kraze"}  # fmt: skip

    block = rm.evidence_blocks(db, [pair], _selection({}))[0]

    assert block.startswith("## P0001 merge_id=retire keep_id=keep\ndoorway D  | squad key: black | club: Kraze\n")
    assert "Friendly" not in block
    retire, keep = block.split("RETIRE: ", 1)[1].split("KEEP: ", 1)
    assert retire.startswith("16B Kraze Black |")
    assert f"games 2 (this season 2, excluded 2) {_day(9, 30)[:7]}..{_day(10, 4)[:7]} | self-play 1" in retire
    assert f"     {_day(10, 4)} vs 2016 Kraze Black U11 [u11 M] 2-1 Cup" in retire
    assert keep.startswith("2016 Kraze Black U11 |")
    assert f"games 4 (this season 3, excluded 1) {_day(5, 1)[:7]}..{_day(10, 18)[:7]} | self-play 0" in keep
    assert f"     {_day(10, 4)} vs 16B Kraze Black [u11 M] 1-2 Cup" in keep
    assert (
        f"head-to-head 1 | shared dates 1 ['{_day(10, 4)}'] | adjacent-day different events ['{_day(9, 30)}'] "
        "| opponent overlap 0.25"
    ) in block


def test_a_retiring_row_with_no_game_has_no_opponents_to_overlap():
    teams = [_team("retire", "16B Kraze Black"), _team("keep", "2016 Kraze Black U11"),
             _team("x", "Rivals 2016", club="Rivals")]  # fmt: skip
    db = _Db(providers=[{"id": 1, "code": "gotsport"}], teams=teams, games=[_game(1, _day(9, 6), "keep", "x")],
             team_alias_map=[])  # fmt: skip
    pair = {"pair": "P0001", "merge_id": "retire", "keep_id": "keep", "doorway": "D", "squad_key": "black",
            "club": "Kraze"}  # fmt: skip

    block = rm.evidence_blocks(db, [pair], _selection({}))[0]

    assert "   games 0 (this season 0, excluded 0) none | self-play 0" in block.split("KEEP: ")[0]
    assert "head-to-head 0 | shared dates 0 [] | adjacent-day different events [] | opponent overlap none" in block


# --- the review from the pairs a page shows to the lane they reach ------------------------------------


def _week_db(monkeypatch, teams, games):
    """The page tests' database, holding the columns the evidence pack reads too."""
    monkeypatch.setitem(pt.COLUMNS, "teams", pt.COLUMNS["teams"] | {"provider_team_id", "last_played_at"})
    monkeypatch.setitem(pt.COLUMNS, "games", pt.COLUMNS["games"] | COLUMNS["games"])
    monkeypatch.setitem(pt.COLUMNS, "team_alias_map", COLUMNS["team_alias_map"])
    rows = [{**pt._team(t), "provider_team_id": f"p-{t}", "last_played_at": None} for t in teams]
    played = [
        {**pt._game(n, home, away, day), "home_score": 1, "away_score": 0, "home_provider_id": "h",
         "away_provider_id": "a", "event_name": "League", "competition": None, "division_name": None}
        for n, (home, away, day) in enumerate(games, 1)
    ]  # fmt: skip
    return pt._Db(teams=rows, games=played)


def _main(monkeypatch, capsys, store, db, runner, *flags):
    monkeypatch.setattr(rm, "get_client", lambda: db)
    monkeypatch.setattr(rm.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(rm, "run_reviewer", runner)
    argv = ["review_merges.py", "--run", pt.RUN, "--stage", "merges", "--store", str(store), *flags]
    monkeypatch.setattr(sys, "argv", argv)
    try:
        code = rm.main()
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr().out


class _Panel:
    """Headless reviewers answering each pair by its retiring row: ``verdicts`` maps it to (verdict, swap), and every
    reject is upheld. Each reads only the evidence copied into its own folder and writes only the file its command
    allows there."""

    def __init__(self, verdicts):
        self.verdicts, self.folders, self.commands = verdicts, [], []

    def __call__(self, command, cwd, log):
        work = Path(cwd)
        self.folders.append(work)
        self.commands.append(command)
        log.write_text("ran", encoding="utf-8")
        name, kind = work.name.rsplit("-", 1)
        evidence = (work / f"{name}.md").read_text(encoding="utf-8")
        if kind == "review":
            answer = [
                {"pair": label, "merge_id": merge, "keep_id": keep, "verdict": self.verdicts[merge][0],
                 "swap": self.verdicts[merge][1], "reason": f"because {merge}"}
                for label, merge, keep in re.findall(r"^## (P\d{4}) merge_id=(\S+) keep_id=(\S+)$", evidence, re.M)
            ]  # fmt: skip
        else:
            labels = re.search(r"from \S+\.md: (.+)\. Write", command[2]).group(1).split(", ")
            answer = [{"pair": label, "upheld": True, "reason": "two teams"} for label in labels]
        (work / _allowed(command)).write_text(json.dumps(answer), encoding="utf-8")
        return 0


def test_the_review_takes_the_pairs_the_page_shows_and_its_verdicts_reach_the_lanes(tmp_path, monkeypatch, capsys):
    """Selection, evidence, reviewers and the page together: a provably safe pair whose retiring row holds no games
    merges unreviewed, an idle pair is left off, and a reviewed pair goes where its verdict sends it, a provably safe
    pair whose retiring row has played since the scan among them."""
    pairs = [
        pt._pair("cleared", "c-keep", doorway="D"),
        pt._pair("safe", "s-keep", tier="1_provably_safe"),
        pt._pair("idle", "i-keep", doorway="D"),
        pt._pair("played", "p-keep", tier="1_provably_safe"),
        pt._pair("held", "h-keep", doorway="D"),
    ]
    teams = [*(t for p in pairs for t in (p["merge_id"], p["keep_id"])), "o1"]
    games = [
        ("cleared", "o1", _day(9, 1)), ("c-keep", "o1", _day(9, 2)), ("s-keep", "o1", _day(9, 3)),
        ("played", "o1", _day(9, 4)), ("held", "o1", _day(9, 5)), ("h-keep", "o1", _day(9, 6)),
    ]  # fmt: skip
    store = tmp_path / "store"
    pt._reviewing(store)
    pt._merges(store, pairs)
    db = _week_db(monkeypatch, teams, games)
    panel = _Panel({"cleared": ("merge", True), "played": ("reject", False), "held": ("hold", False)})

    code, out = _main(monkeypatch, capsys, store, db, panel, "--execute")

    assert code == 0 and "reviewed: 1 merge, 1 hold, 1 reject" in out
    assert {f.name for f in panel.folders} == {"slice_01-review", "slice_01-recheck"}
    reviewed = json.loads((pt.stage_dir(store, pt.RUN, "merges") / "review" / "slice_01.json").read_text())
    assert [r["merge_id"] for r in reviewed] == ["played", "cleared", "held"]

    code, _ = pt._build(monkeypatch, capsys, store, db, stage="merges")

    manifest = pt._read(store, "merges", MANIFEST_FILE)
    auto = {p["merge_id"]: (p.get("review") or {}).get("verdict") for p in manifest["auto"].values()}
    assert code == 0
    assert auto == {"safe": None, "played": "reject", "cleared": "merge"}
    assert [p["merge_id"] for p in manifest["cards"].values()] == ["held"]
    assert [(p["merge_id"], p["why"]) for p in manifest["left_out"]] == [("idle", pages.IDLE_WHY)]
    assert manifest["overflow"] == []


def test_a_dry_run_queues_nothing_and_runs_no_reviewer(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    pt._reviewing(store)
    pt._merges(store, [pt._pair("m1", "k1", doorway="D")])
    db = _week_db(monkeypatch, ["m1", "k1", "o1"], [("m1", "o1", _day(9, 1))])
    panel = _Panel({})

    code, out = _main(monkeypatch, capsys, store, db, panel)

    assert (code, panel.folders) == (0, [])
    assert "DRY RUN -- would queue 1 pair(s) for review" in out
    assert not (pt.stage_dir(store, pt.RUN, "merges") / "review").exists()


def test_unreadable_decisions_stop_the_review_with_a_reason(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    pt._reviewing(store)
    pt._merges(store, [pt._pair("m1", "k1", doorway="D")])

    def unreadable(*args):
        raise rm.DecisionsUnavailable("could not read team_cleanup_decisions: timeout")

    monkeypatch.setattr(rm, "select", unreadable)
    code, _ = _main(monkeypatch, capsys, store, None, _Panel({}), "--execute")

    assert "could not read team_cleanup_decisions" in code and "earlier decisions can be read" in code


def test_a_queued_review_with_no_claude_on_the_path_says_so(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    pt._reviewing(store)
    folder = pt._merges(store, [pt._pair("m1", "k1", doorway="D")])
    _slice(folder, _rows(("m1", "k1")))
    monkeypatch.setattr(rm.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["review_merges.py", "--run", pt.RUN, "--stage", "merges", "--store", str(store),
                                      "--execute"])  # fmt: skip

    with pytest.raises(SystemExit, match="the claude command is not on PATH"):
        rm.main()


def test_a_slice_left_for_a_retry_exits_1_and_a_run_not_in_review_is_refused(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    pt._reviewing(store)
    folder = pt._merges(store, [pt._pair("m1", "k1", doorway="D")])
    _slice(folder, _rows(("m1", "k1")))

    code, out = _main(monkeypatch, capsys, store, None, _Reviewers([]), "--execute")

    assert code == 1 and "1 slice(s) wait for a retry: slice_01" in out

    write_run(store, {"run_id": pt.RUN, "scope": {"states": ["NV"]}, "status": "applying", "budgets": {}, "stages": {}})
    code, _ = _main(monkeypatch, capsys, store, None, _Reviewers([]), "--execute")

    assert isinstance(code, str) and "is applying" in code


# --- the lookups ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["team", "not-a-uuid"],
        ["club", "ab", "u11", "Male"],
        ["club", "a%b", "u11", "Male"],
        ["name", "Kraze,Blue", "u11", "Male"],
        ["name", "Kraze", "U11", "Male"],
        ["name", "Kraze", "u11", "Boys"],
        ["name", "Kraze"],
    ],
    ids=["id", "short", "wildcard", "list", "age", "gender", "missing"],
)
def test_a_lookup_refuses_anything_but_an_id_or_a_plain_fragment_of_a_cohort(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["review_lookup.py", *argv])
    monkeypatch.setattr(lookup, "public_client", lambda: pytest.fail("a refused lookup opens no client"))

    with pytest.raises(SystemExit) as exited:
        lookup.main()

    assert exited.value.code == 2


KEEP_ID = "11111111-1111-1111-1111-111111111111"
GONE_ID = "22222222-2222-2222-2222-222222222222"


def _lookup(monkeypatch, capsys, db, *argv):
    monkeypatch.setattr(sys, "argv", ["review_lookup.py", *argv])
    monkeypatch.setattr(lookup, "public_client", lambda: db)
    assert lookup.main() == 0
    return capsys.readouterr().out


def test_a_team_lookup_reads_a_merged_away_id_as_its_survivor_newest_game_first_from_its_own_side(
    monkeypatch, capsys
):
    db = _Db(
        providers=[{"id": 1, "code": "gotsport"}],
        teams=[_team(KEEP_ID, "2016 Kraze Black U11"), _team(GONE_ID, "16 Kraze Black", deprecated=True),
               _team("opp", "Rivals 2016", club="Rivals")],  # fmt: skip
        team_merge_map=[{"id": 1, "deprecated_team_id": GONE_ID, "canonical_team_id": KEEP_ID}],
        games=[_game(1, _day(9, 6), "opp", GONE_ID, score=(3, 1)), _game(2, _day(10, 4), KEEP_ID, "opp")],
    )
    read, table = [], db.table
    monkeypatch.setattr(db, "table", lambda name: read.append(name) or table(name))
    monkeypatch.setattr(lookup, "GAMES_SHOWN", 1)

    lines = _lookup(monkeypatch, capsys, db, "team", GONE_ID).splitlines()

    assert lines[0] == f"{GONE_ID} was merged into {KEEP_ID}; showing that row"
    # The public key reads no row of team_alias_map, so the lookup says it shows none rather than listing none.
    assert lines[2] == "  aliases: not readable with the public key; the slice's evidence lists each pair's"
    assert "team_alias_map" not in read
    assert lines[3].startswith(f"  merged into it: {GONE_ID} | 16 Kraze Black")
    assert lines[4:] == [
        "  games: 2, newest first; the oldest 1 are not shown",
        f"    {_day(10, 4)} as 1 vs Rivals 2016 [u11 M] 1-0 League",
    ]

    monkeypatch.setattr(lookup, "GAMES_SHOWN", 5)
    away = _lookup(monkeypatch, capsys, db, "team", KEEP_ID)
    assert f"    {_day(9, 6)} as x vs Rivals 2016 [u11 M] 1-3 League" in away


def test_a_club_lookup_says_when_it_shows_only_the_first_rows(monkeypatch, capsys):
    teams = [_team(f"t{n:02d}", f"Kraze {n:02d}") for n in range(3)] + [_team("girls", "Kraze G", gender="Female")]
    db = _Db(providers=[{"id": 1, "code": "gotsport"}], teams=teams)
    monkeypatch.setattr(lookup, "ROWS_SHOWN", 2)

    out = _lookup(monkeypatch, capsys, db, "club", "kraze", "u11", "Male").splitlines()

    assert [line.split(" | ")[1] for line in out[:-1]] == ["Kraze 00", "Kraze 01"]
    assert out[-1] == "more than 2 rows hold the text; the first 2 by club and name are shown"


def test_a_name_lookup_cuts_across_both_names_by_club_with_a_blank_club_last(monkeypatch, capsys):
    teams = [
        _team("a", "Blue A"),
        _team("b", "Blue B", club=None),
        _team("c", "Red C", club="Arsenal", original="Blue C"),
    ]
    db = _Db(providers=[{"id": 1, "code": "gotsport"}], teams=teams)
    monkeypatch.setattr(lookup, "ROWS_SHOWN", 2)

    out = _lookup(monkeypatch, capsys, db, "name", "blue", "u11", "Male").splitlines()

    assert [line.split(" | ")[1] for line in out[:-1]] == ["Red C", "Blue A"]
    assert out[-1] == "more than 2 rows hold the text; the first 2 by club and name are shown"


def test_a_lookup_reads_with_the_public_key_whatever_else_the_environment_holds(monkeypatch, capsys):
    opened = []
    db = _Db(providers=[{"id": 1, "code": "gotsport"}], teams=[_team("a", "Kraze Blue")])
    monkeypatch.setattr(lookup, "create_client", lambda url, key: opened.append((url, key)) or db)
    monkeypatch.setattr(sys, "argv", ["review_lookup.py", "club", "Kraze", "u11", "Male"])
    for key, value in {"SUPABASE_URL": "u", "SUPABASE_KEY": "public", "SUPABASE_SERVICE_ROLE_KEY": "private"}.items():
        monkeypatch.setenv(key, value)

    assert lookup.main() == 0
    assert opened == [("u", "public")]

    monkeypatch.delenv("SUPABASE_KEY")
    with pytest.raises(SystemExit, match="SUPABASE_URL and SUPABASE_KEY must be set"):
        lookup.main()
    assert opened == [("u", "public")]
