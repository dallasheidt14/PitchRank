"""Tests for carrying the owner's Keep-separate choices off the old review pages.

The double records an insert at execute(), not at insert(), so a write built and never sent
does not count as written. A table it was not given raises the way PostgREST does for a table
missing from its schema cache, with code PGRST205.
"""

import json
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup import carry_forward as cf  # noqa: E402
from tests.unit.test_find_cross_provider_duplicates import _Supabase, _Table  # noqa: E402

OLDER, NEWER = "20260925T063742Z-6df533", "20261001T120000Z-a1b2c3"


class _ApiError(Exception):
    """Stands in for postgrest's APIError: the code is what callers branch on."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class _Insert:
    def __init__(self, log, table, rows):
        self._log, self._table, self._rows = log, table, rows

    def execute(self):
        self._log.append((self._table, list(self._rows)))


URL_BUDGET = 4000  # characters of filter values one request can carry, well inside an ~8KB URL


class _WritableTable(_Table):
    def __init__(self, name, rows, cap, log):
        super().__init__(name, rows, cap)
        self._log = log

    def in_(self, column, values):
        values = list(values)
        if sum(len(str(v)) + 1 for v in values) > URL_BUDGET:
            raise AssertionError(f"{self.name}: .in_() on {column} would overflow the request URL")
        return super().in_(column, values)

    def insert(self, rows):
        return _Insert(self._log, self.name, rows)


class _Writable(_Supabase):
    def __init__(self, tables, *, failure=None):
        super().__init__(tables, cap=1000)
        self.inserted = []
        self._failure = failure

    def table(self, name):
        if self._failure:
            raise self._failure
        if name not in self._tables:
            raise _ApiError("PGRST205", f"Could not find the table 'public.{name}' in the schema cache")
        return _WritableTable(name, self._tables[name], self._cap, self.inserted)


def write_page(pages_dir, slug, run, pairs, choices, *, collection=None, builder=False, saved=True, repeat=()):
    """One saved page: `pairs` maps a pair tag to (merge_id, keep_id); `choices` maps it to a
    decision, or to (decision, note). `builder` writes the manifest as build_review_page.py does,
    keyed on `run`; otherwise as the saved copies do, keyed on the `decisions-<run>` collection.
    `repeat` lists tags whose document is saved twice; `saved=False` writes no decisions file."""
    doc_id = {tag: f"{run}_{tag}" for tag in pairs}
    stamp = {"run": run} if builder else {"collection": collection if collection is not None else f"decisions-{run}"}
    manifest = {
        **stamp,
        "title": slug,
        "pairs": {
            doc_id[t]: {"merge_id": m, "keep_id": k, "merge_name": m, "keep_name": k} for t, (m, k) in pairs.items()
        },
    }
    documents = []
    for tag, choice in [*choices.items(), *((t, choices[t]) for t in repeat)]:
        decision, note = choice if isinstance(choice, tuple) else (choice, "")
        data = {"decision": decision, "swap": False, "note": note}
        documents.append({"id": doc_id.get(tag, f"{run}_{tag}"), "data": data})
    (pages_dir / f"{slug}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if saved:
        (pages_dir / f"{slug}.decisions.json").write_text(json.dumps(documents), encoding="utf-8")
    with (pages_dir / "index.tsv").open("a", encoding="utf-8") as index:
        index.write(f"{slug}\t{slug} title\thttps://claude.ai/artifact/{slug.upper()}id\n")


def run_main(monkeypatch, pages_dir, *extra, sb=None, env_key="service"):
    if env_key:
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", env_key)
    else:
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(cf, "get_client", lambda: sb if sb is not None else _Writable({"team_cleanup_decisions": []}))
    monkeypatch.setattr(sys, "argv", ["prog", "--pages-dir", str(pages_dir), *extra])
    return cf.main()


def planned_rows(monkeypatch, tmp_path, pages_dir, *extra):
    out = tmp_path / "plan.json"
    assert run_main(monkeypatch, pages_dir, "--out", str(out), *extra) == 0
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture
def pages(tmp_path):
    folder = tmp_path / "pages"
    folder.mkdir()
    return folder


def test_a_keep_separate_choice_becomes_a_decision_carrying_its_page_and_note(monkeypatch, tmp_path, pages):
    write_page(pages, "co2", OLDER, {"p": ("a", "b")}, {"p": ("separate", "two squads")})

    rows = planned_rows(monkeypatch, tmp_path, pages)

    assert rows == [
        {
            "stage": "merges",
            "subject_key": "a|b",
            "team_id_master": "a",
            "other_team_id": "b",
            "decision": "keep_separate",
            "note": "two squads",
            "decided_at": "2026-09-25T06:37:42+00:00",
            "source": "carried:CO2id",
        }
    ]


def test_a_manifest_as_the_page_builder_writes_it_is_read(monkeypatch, tmp_path, pages):
    """build_review_page.py records the build as `run`; only saved copies carry `collection`."""
    write_page(pages, "co3", OLDER, {"p": ("a", "b")}, {"p": "separate"}, builder=True)

    rows = planned_rows(monkeypatch, tmp_path, pages)

    assert [r["decided_at"] for r in rows] == ["2026-09-25T06:37:42+00:00"]


@pytest.mark.parametrize("decision", ["merge", "unsure"])
def test_only_keep_separate_is_carried(monkeypatch, tmp_path, pages, decision):
    write_page(pages, "co2", OLDER, {"p": ("a", "b")}, {"p": decision})

    assert planned_rows(monkeypatch, tmp_path, pages) == []


def test_a_newer_page_s_merge_overrules_an_older_page_s_keep_separate(monkeypatch, tmp_path, pages):
    write_page(pages, "az", OLDER, {"p": ("a", "b")}, {"p": "separate"})
    write_page(pages, "az2", NEWER, {"p": ("b", "a")}, {"p": "merge"})

    assert planned_rows(monkeypatch, tmp_path, pages) == []


def test_a_newer_page_s_keep_separate_overrules_an_older_page_s_merge(monkeypatch, tmp_path, pages):
    write_page(pages, "al2", NEWER, {"p": ("a", "b")}, {"p": "separate"})
    write_page(pages, "al", OLDER, {"p": ("a", "b")}, {"p": "merge"})

    rows = planned_rows(monkeypatch, tmp_path, pages)

    assert [(r["subject_key"], r["source"]) for r in rows] == [("a|b", "carried:AL2id")]


def test_a_build_time_given_in_another_zone_is_ordered_by_the_instant_it_names(monkeypatch, tmp_path, pages):
    """17:00 at UTC-7 is midnight UTC on the 25th, four hours after the other page's 20:00 UTC
    build, so its Keep separate is the newer choice -- though it sorts first as text."""
    write_page(pages, "old", "", {"p": ("a", "b")}, {"p": "separate"}, collection="decisions")
    write_page(pages, "new", "20260924T200000Z-abcdef", {"p": ("a", "b")}, {"p": "merge"})

    rows = planned_rows(monkeypatch, tmp_path, pages, "--built-at", "old=2026-09-24T17:00:00-07:00")

    assert [(r["source"], r["decided_at"]) for r in rows] == [("carried:OLDid", "2026-09-25T00:00:00+00:00")]


def test_one_instant_written_in_two_zones_is_the_same_second(monkeypatch, pages, capsys):
    write_page(pages, "old", "", {"p": ("a", "b")}, {"p": "separate"}, collection="decisions")
    write_page(pages, "new", "20260924T200000Z-abcdef", {"p": ("a", "b")}, {"p": "merge"})

    assert run_main(monkeypatch, pages, "--built-at", "old=2026-09-24T13:00:00-07:00") == 1

    assert "built in the same second and disagree" in capsys.readouterr().out


def test_a_cleared_choice_is_not_a_choice(monkeypatch, tmp_path, pages):
    write_page(pages, "ga2", OLDER, {"p": ("a", "b")}, {"p": None})

    assert planned_rows(monkeypatch, tmp_path, pages) == []


@pytest.mark.parametrize(
    "build, refusal",
    [
        (
            lambda p: write_page(p, "x", OLDER, {"p": ("a", "b")}, {"stranger": "separate"}),
            "not on the page's manifest",
        ),
        (lambda p: write_page(p, "x", OLDER, {"p": ("a", "b")}, {"p": "maybe"}), "holds decision 'maybe'"),
        (
            lambda p: write_page(p, "x", OLDER, {"p": ("a", "b")}, {"p": "separate"}, collection="decisions"),
            "carries no build time",
        ),
        (
            lambda p: (
                write_page(p, "x", OLDER, {"p": ("a", "b")}, {"p": "separate"}),
                write_page(p, "y", OLDER, {"p": ("a", "b")}, {"p": "merge"}),
            ),
            "built in the same second and disagree",
        ),
        (
            lambda p: write_page(p, "x", OLDER, {"p": ("a", "b")}, {"p": "separate"}, repeat=("p",)),
            "is listed twice",
        ),
        (
            lambda p: write_page(p, "x", OLDER, {"p": ("a", "b")}, {"p": "separate"}, saved=False),
            "no x.decisions.json",
        ),
    ],
)
def test_choices_it_cannot_trust_refuse_the_whole_run(monkeypatch, pages, capsys, build, refusal):
    build(pages)
    sb = _Writable({"team_cleanup_decisions": []})

    assert run_main(monkeypatch, pages, "--execute", sb=sb) == 1

    assert refusal in capsys.readouterr().out
    assert sb.inserted == []


def test_a_page_without_a_build_time_is_read_once_given_one(monkeypatch, tmp_path, pages):
    write_page(pages, "co_orig", "", {"p": ("a", "b")}, {"p": "separate"}, collection="decisions")

    rows = planned_rows(monkeypatch, tmp_path, pages, "--built-at", "co_orig=2026-09-24T00:00:00+00:00")

    assert [r["decided_at"] for r in rows] == ["2026-09-24T00:00:00+00:00"]


def test_a_build_time_without_a_zone_is_refused(monkeypatch, pages):
    write_page(pages, "co_orig", "", {"p": ("a", "b")}, {"p": "separate"}, collection="decisions")

    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, pages, "--built-at", "co_orig=2026-09-24T00:00:00")

    assert exc.value.code == 2


def test_execute_writes_every_new_decision_and_prints_its_undo(monkeypatch, pages, capsys):
    write_page(pages, "co2", OLDER, {"p": ("a", "b"), "q": ("c", "d")}, {"p": "separate", "q": "separate"})
    sb = _Writable({"team_cleanup_decisions": []})

    assert run_main(monkeypatch, pages, "--execute", sb=sb) == 0

    assert [(table, [r["subject_key"] for r in rows]) for table, rows in sb.inserted] == [
        ("team_cleanup_decisions", ["a|b", "c|d"])
    ]
    assert (
        "Undo, every carried decision at once: UPDATE team_cleanup_decisions SET superseded_at = now() "
        "WHERE source LIKE 'carried:%' AND superseded_at IS NULL;"
    ) in capsys.readouterr().out


def test_execute_leaves_a_pair_that_already_holds_an_active_decision(monkeypatch, pages):
    """An answer given since the page outranks the page."""
    write_page(pages, "co2", OLDER, {"p": ("a", "b"), "q": ("c", "d")}, {"p": "separate", "q": "separate"})
    existing = [
        {"id": "d1", "stage": "merges", "subject_key": "a|b", "superseded_at": None},
        {"id": "d2", "stage": "merges", "subject_key": "c|d", "superseded_at": "2026-10-02T00:00:00+00:00"},
    ]
    sb = _Writable({"team_cleanup_decisions": existing})

    assert run_main(monkeypatch, pages, "--execute", sb=sb) == 0

    assert [r["subject_key"] for _, rows in sb.inserted for r in rows] == ["c|d"]


def test_looking_up_many_pairs_keeps_each_request_url_short(monkeypatch, pages):
    """A pair key is two uuids long, so a batch sized for ids would double the URL."""
    ids = [f"{i:08d}-0000-4000-8000-000000000000" for i in range(160)]
    pairs = {f"p{i}": (ids[2 * i], ids[2 * i + 1]) for i in range(80)}
    write_page(pages, "big", OLDER, pairs, {tag: "separate" for tag in pairs})
    sb = _Writable({"team_cleanup_decisions": []})

    assert run_main(monkeypatch, pages, "--execute", sb=sb) == 0

    assert sum(len(rows) for _, rows in sb.inserted) == 80


@pytest.mark.parametrize("flags", [(), ("--execute", "--dry-run")])
def test_a_dry_run_writes_nothing(monkeypatch, pages, flags):
    write_page(pages, "co2", OLDER, {"p": ("a", "b")}, {"p": "separate"})
    sb = _Writable({"team_cleanup_decisions": []})

    assert run_main(monkeypatch, pages, *flags, sb=sb) == 0

    assert sb.inserted == []


def test_execute_refuses_without_the_service_role_key(monkeypatch, pages):
    write_page(pages, "co2", OLDER, {"p": ("a", "b")}, {"p": "separate"})
    sb = _Writable({"team_cleanup_decisions": []})

    with pytest.raises(SystemExit, match="SUPABASE_SERVICE_ROLE_KEY"):
        run_main(monkeypatch, pages, "--execute", sb=sb, env_key=None)

    assert sb.inserted == []


def test_execute_refuses_while_the_table_does_not_exist(monkeypatch, pages):
    write_page(pages, "co2", OLDER, {"p": ("a", "b")}, {"p": "separate"})
    sb = _Writable({})

    with pytest.raises(SystemExit, match="Apply the team_cleanup_decisions migration"):
        run_main(monkeypatch, pages, "--execute", sb=sb)

    assert sb.inserted == []


def test_a_dry_run_reports_rather_than_fails_while_the_table_does_not_exist(monkeypatch, pages, capsys):
    write_page(pages, "co2", OLDER, {"p": ("a", "b")}, {"p": "separate"})

    assert run_main(monkeypatch, pages, sb=_Writable({})) == 0

    assert "every row above would be new" in capsys.readouterr().out


@pytest.mark.parametrize("flags", [(), ("--execute",)])
def test_any_other_read_failure_stops_the_run_naming_it(monkeypatch, pages, capsys, flags):
    """Only a missing table means "nothing decided yet"; a refused or failed read says nothing
    about what was decided, so the run stops."""
    write_page(pages, "co2", OLDER, {"p": ("a", "b")}, {"p": "separate"})
    sb = _Writable({"team_cleanup_decisions": []}, failure=_ApiError("42501", "permission denied for table"))

    assert run_main(monkeypatch, pages, *flags, sb=sb) == 1

    out = capsys.readouterr().out
    assert "permission denied for table" in out
    assert "would be new" not in out
    assert sb.inserted == []
