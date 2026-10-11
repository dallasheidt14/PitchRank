"""Tests for the weekly team-data health report: its definitions, its rendering, and main() end to end."""

import csv
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup import health  # noqa: E402

SINCE = datetime(2026, 10, 7, tzinfo=timezone.utc)
UNTIL = SINCE + timedelta(days=7)
OLD, NEW = "2026-09-01T12:00:00+00:00", "2026-10-10T12:00:00+00:00"


def _team(
    team_id,
    state="AZ",
    club="Phoenix Rising",
    name="Phoenix Rising 2014B",
    *,
    deprecated=False,
    created=OLD,
    provider="p-gs",
):
    return {
        "team_id_master": team_id,
        "state_code": state,
        "club_name": club,
        "team_name": name,
        "is_deprecated": deprecated,
        "created_at": created,
        "provider_id": provider,
    }


def _game(game_id, home, away):
    return {"id": game_id, "home_team_master_id": home, "away_team_master_id": away}


def _measure(teams, merge_map=None, games=()):
    return health.measure(teams, merge_map or {}, games, {"p-gs": "gotsport", "p-tgs": "tgs"}, SINCE, UNTIL)


# --- definitions ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, bucket",
    [
        ("AZ", "AZ"),
        (" AZ ", "AZ"),
        ("DC", "DC"),
        (None, "(no state)"),
        ("", "(no state)"),
        ("  ", "(no state)"),
        ("ON", "(non-US)"),
        ("BC", "(non-US)"),
        ("13", "(malformed)"),
        ("az", "(malformed)"),
        ("SJ", "(malformed)"),
    ],
    ids=["state", "padded-state", "dc", "null", "empty", "spaces", "ontario", "bc", "digits", "lowercase", "sj"],
)
def test_a_team_s_bucket_is_its_us_state_or_why_it_has_none(code, bucket):
    assert health.state_bucket(code) == bucket


@pytest.mark.parametrize(
    "club, blank, placeholder",
    [
        (None, 1, 0),
        ("", 1, 0),
        ("   ", 1, 0),
        ("No Club Selection", 0, 1),
        (" no club selection ", 0, 1),
        ("AYSO", 0, 1),
        ("AYSO United", 0, 0),
        ("Phoenix Rising", 0, 0),
    ],
    ids=["null", "empty", "spaces", "placeholder", "padded-placeholder", "ayso", "named-ayso", "real-club"],
)
def test_a_blank_club_is_null_or_empty_after_trimming_and_is_never_also_a_placeholder(club, blank, placeholder):
    counts = _measure([_team("t1", club=club)])
    assert (counts[("AZ", "blank_club")], counts[("AZ", "placeholder_club")]) == (blank, placeholder)


@pytest.mark.parametrize(
    "name, unknown",
    [
        ("unknown_688297", True),
        (" Unknown_12 ", True),
        ("UNKNOWN_3", True),
        ("unknown_FC Dallas 2014", False),
        ("unknown_12 Blue", False),
        ("unknown_", False),
        ("Phoenix Rising 2014B", False),
        (None, False),
    ],
    ids=["plain", "padded-capital", "upper", "named", "id-then-name", "no-id", "real-name", "null"],
)
def test_an_unknown_name_is_unknown_and_a_provider_id_as_the_siblings_read_it(name, unknown):
    assert health.is_unknown_name(name) is unknown


def test_only_live_teams_are_counted_as_live_or_by_club():
    counts = _measure([_team("t1"), _team("t2", club=None, deprecated=True)])
    assert (counts[("AZ", "live_teams")], counts[("AZ", "blank_club")]) == (1, 0)


def test_a_live_team_still_in_the_merge_map_is_counted_and_a_merged_one_is_not():
    teams = [_team("live-merged"), _team("gone", deprecated=True), _team("clean")]
    counts = _measure(teams, {"live-merged": "clean", "gone": "clean"})
    assert counts[("AZ", "merged_but_live")] == 1


def test_self_play_follows_merge_chains_and_counts_excluded_games_as_the_scans_do():
    teams = [_team("a", deprecated=True), _team("b", deprecated=True), _team("c", state="NV"), _team("d")]
    games = [
        _game(1, "a", "c"),  # a -> b -> c: c against itself
        _game(2, "c", "c"),  # raw self-play
        {**_game(3, "a", "c"), "is_excluded": True},  # still a fused row
        _game(4, "c", "d"),
        _game(5, None, None),
    ]
    counts = _measure(teams, {"a": "b", "b": "c"}, games)
    assert (counts[("NV", "self_play_games")], counts[("ALL", "self_play_games")]) == (3, 3)


def test_the_week_s_new_teams_are_counted_by_source_with_what_they_lack():
    teams = [
        _team("n1", state=None, club=None, name="unknown_688297", created=NEW),
        _team("n2", state="AZ", club="", created=NEW),
        _team("n3", created=NEW, provider="p-tgs", deprecated=True),
        _team("n4", created=NEW, provider=None),
        _team("n5", state="ON", club="No Club Selection", created=NEW),
        _team("old", state=None, club=None, name="unknown_1"),
    ]
    counts = _measure(teams)

    gotsport = {m: counts[("source:gotsport", m)] for m in health.INFLOW_METRICS}
    assert gotsport == {"new_teams": 3, "new_no_state": 1, "new_no_club": 3, "new_unknown_name": 1}
    assert (counts[("source:tgs", "new_teams")], counts[("source:(none)", "new_teams")]) == (1, 1)
    assert (counts[("ALL", "new_teams")], counts[("AZ", "new_teams")], counts[("(no state)", "new_teams")]) == (5, 3, 1)


@pytest.mark.parametrize(
    "created, new",
    [
        ("2026-10-06T23:59:59+00:00", 0),
        ("2026-10-07T00:00:00+00:00", 1),
        ("2026-10-13T23:59:59+00:00", 1),
        ("2026-10-14T00:00:00+00:00", 0),
        ("2026-10-14T09:00:00+00:00", 0),
    ],
    ids=["before-the-week", "week-starts", "last-second", "report-day-starts", "report-day"],
)
def test_the_week_is_the_seven_days_before_the_report_date(created, new):
    assert _measure([_team("t", created=created)])[("ALL", "new_teams")] == new


def test_open_problems_count_stateless_teams_and_the_national_total_sums_every_bucket():
    teams = [
        _team("s1", state=None),
        _team("s2", state="13"),
        _team("ca", state="ON", club=None),
        _team("az", club=None),
        _team("ok"),
    ]
    rows = health.history_rows("2026-10-14", _measure(teams))
    problems = {r["bucket"]: r["value"] for r in rows if r["metric"] == "open_problems"}

    assert problems == {"(no state)": 1, "(malformed)": 1, "(non-US)": 1, "AZ": 1, "ALL": 4}


def test_the_special_buckets_and_the_national_metrics_are_written_even_at_zero():
    rows = health.history_rows("2026-10-14", _measure([_team("ok")]))
    written = {(r["bucket"], r["metric"]): r["value"] for r in rows}

    assert [written[(b, "live_teams")] for b in ("(no state)", "(non-US)", "(malformed)")] == [0, 0, 0]
    assert (written[("ALL", "self_play_games")], written[("ALL", "new_unknown_name")]) == (0, 0)


# --- the report ----------------------------------------------------------------------------


def _history(*weeks):
    """weeks: (date, {bucket: {metric: value}})"""
    return [
        {"date": day, "bucket": bucket, "metric": metric, "value": str(value)}
        for day, buckets in weeks
        for bucket, metrics in buckets.items()
        for metric, value in metrics.items()
    ]


def _row(report, bucket):
    return next(line for line in report.splitlines() if line.startswith(f"| {bucket} |"))


def _section(report, heading):
    return report.split(f"## {heading}")[1].split("##")[0]


def _table(report, heading):
    """A section's table rows, header and divider left out."""
    rows = [line for line in _section(report, heading).splitlines() if line.startswith("| ")]
    return rows[1:]


def test_states_are_ordered_by_open_problems_with_the_change_on_last_week_and_a_trend():
    history = _history(
        ("2026-09-23", {"AZ": {"open_problems": 10}, "NV": {"open_problems": 5}}),
        ("2026-09-30", {"AZ": {"open_problems": 9}, "NV": {"open_problems": 6}}),
        ("2026-10-07", {"AZ": {"open_problems": 8}, "NV": {"open_problems": 7}}),
        ("2026-10-14", {"AZ": {"open_problems": 4}, "NV": {"open_problems": 9}, "ALL": {"open_problems": 13}}),
    )
    report = health.render("2026-10-14", history)

    assert report.index("| NV |") < report.index("| AZ |")
    assert _row(report, "NV").startswith("| NV | 9 | +2 | ↑ |")
    assert _row(report, "AZ").startswith("| AZ | 4 | -4 | ↓ |")


def test_the_trend_spans_four_reports_not_the_last_two():
    history = _history(
        ("2026-09-23", {"AZ": {"open_problems": 10}}),
        ("2026-09-30", {"AZ": {"open_problems": 13}}),
        ("2026-10-07", {"AZ": {"open_problems": 12}}),
        ("2026-10-14", {"AZ": {"open_problems": 11}}),
    )

    assert _row(health.render("2026-10-14", history), "AZ").startswith("| AZ | 11 | -1 | ↑ |")


def test_a_bucket_new_this_week_shows_its_rise_from_zero():
    history = _history(
        ("2026-10-07", {"AZ": {"open_problems": 2}}),
        ("2026-10-14", {"AZ": {"open_problems": 2}, "NV": {"open_problems": 3}}),
    )

    assert _row(health.render("2026-10-14", history), "NV").startswith("| NV | 3 | +3 | ↑ |")


def test_rising_lists_problem_counts_that_rose_twice_including_from_zero_but_not_growth():
    history = _history(
        ("2026-09-30", {"AZ": {"blank_club": 5, "placeholder_club": 5, "live_teams": 10, "open_problems": 5}}),
        (
            "2026-10-07",
            {
                "AZ": {
                    "blank_club": 6,
                    "placeholder_club": 5,
                    "live_teams": 11,
                    "open_problems": 4,
                    "self_play_games": 1,
                }
            },
        ),
        (
            "2026-10-14",
            {
                "AZ": {
                    "blank_club": 8,
                    "placeholder_club": 6,
                    "live_teams": 12,
                    "open_problems": 9,
                    "self_play_games": 2,
                }
            },
        ),
    )
    rising = _section(health.render("2026-10-14", history), "Rising two weeks running")

    assert [line for line in rising.splitlines() if line.startswith("- ")] == [
        "- AZ, blank_club: 5 → 6 → 8",
        "- AZ, self_play_games: 0 → 1 → 2",
    ]


def test_a_first_report_has_no_change_or_trend_and_says_why_nothing_is_rising():
    report = health.render("2026-10-14", _history(("2026-10-14", {"AZ": {"open_problems": 3}})))

    assert _row(report, "AZ").startswith("| AZ | 3 |  |  |")
    assert "Needs three weeks of history." in report


# --- main() end to end ---------------------------------------------------------------------

COLUMNS = {
    "teams": {"team_id_master", "team_name", "club_name", "state_code", "provider_id", "created_at", "is_deprecated"},
    "games": {"id", "home_team_master_id", "away_team_master_id"},
    "team_merge_map": {"id", "deprecated_team_id", "canonical_team_id"},
    "providers": {"id", "code"},
}
ROW_CAP = 3


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records each request at execute(), where the real builder sends it. Like the hosted PostgREST
    it answers at most ROW_CAP rows however many were asked for, so a read that does not page comes
    back short; and it refuses a range or limit with no order, which PostgREST would serve in an
    arbitrary order."""

    def __init__(self, db, table, columns):
        unknown = set(columns) - COLUMNS[table]
        assert not unknown, f"PostgREST refuses unknown columns on {table}: {unknown}"
        self._db, self._table, self._columns = db, table, columns
        self._order, self._gt, self._range, self._limit = None, None, None, None

    def order(self, column):
        assert column in COLUMNS[self._table]
        self._order = column
        return self

    def gt(self, column, value):
        assert column in COLUMNS[self._table]
        self._gt = (column, value)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        assert self._order or (self._range is None and self._limit is None), "a page with no order is arbitrary"
        self._db.executes.append((self._table, self._gt, self._range, self._limit))
        rows = list(self._db.tables[self._table])
        if self._order:
            rows.sort(key=lambda r: r[self._order])
        if self._gt:
            rows = [r for r in rows if r[self._gt[0]] > self._gt[1]]
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Result([{c: r[c] for c in self._columns} for r in rows[:ROW_CAP]])


class _Db:
    def __init__(self, teams, games, merges, providers):
        self.tables = {"teams": teams, "games": games, "team_merge_map": merges, "providers": providers}
        self.executes = []

    def table(self, name):
        db = self

        class _T:
            def select(self, columns):
                return _Query(db, name, [c.strip() for c in columns.split(",")])

        return _T()


def _db():
    teams = [
        _team("nv1", state="NV"),
        _team("az1", club=None),
        _team("new-old-edge", created="2026-10-06T23:59:59+00:00"),
        _team("az2", club="No Club Selection"),
        _team("new1", state=None, club=None, name="unknown_9", created="2026-10-12T08:00:00+00:00"),
        _team("gone", state="NV", deprecated=True),
        _team("today", created="2026-10-14T09:00:00+00:00"),
        _team("week-start", created="2026-10-07T00:00:00+00:00"),
        _team("wa1", state="WA", created="2026-10-10T00:00:00+00:00", provider="p-af"),
    ]
    # Stored out of id order, so a scan that orders by anything but its id cursor skips or repeats games.
    games = [_game(f"g{i}", "nv1", "gone" if i % 2 else "az1") for i in (3, 0, 4, 1, 2)]
    merges = [{"id": 1, "deprecated_team_id": "gone", "canonical_team_id": "nv1"}]
    providers = [{"id": "p-gs", "code": "gotsport"}, {"id": "p-af", "code": "affinity_wa"}]
    return _Db(teams, games, merges, providers)


def _run(monkeypatch, capsys, db, *argv):
    monkeypatch.setattr(health, "get_client", lambda: db)
    monkeypatch.setattr(health, "GAMES_PAGE", 2)
    monkeypatch.setattr(sys, "argv", ["health.py", *argv])
    code = health.main()
    return code, capsys.readouterr().out


def _history_file(store):
    with (store / "health" / "health_history.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_main_writes_the_week_s_report_and_history_reading_every_team_and_game(monkeypatch, capsys, tmp_path):
    store, db = tmp_path / "store", _db()

    code, out = _run(monkeypatch, capsys, db, "--store", str(store), "--date", "2026-10-14")

    report = (store / "health" / "2026-10-14.md").read_text(encoding="utf-8")
    assert code == 0 and "Wrote" in out
    assert "Live teams: 8. Open problems: 6." in report
    assert _table(report, "States by open problems") == [
        "| (no state) | 2 |  |  | 1 | 1 | 0 | 0 | 0 | 1 |",
        "| AZ | 2 |  |  | 5 | 1 | 1 | 0 | 0 | 1 |",
        "| NV | 2 |  |  | 1 | 0 | 0 | 0 | 2 | 0 |",
        "| (malformed) | 0 |  |  | 0 | 0 | 0 | 0 | 0 | 0 |",
        "| (non-US) | 0 |  |  | 0 | 0 | 0 | 0 | 0 | 0 |",
        "| WA | 0 |  |  | 1 | 0 | 0 | 0 | 0 | 1 |",
    ]
    assert _table(report, "New teams this week by source") == [
        "| gotsport | 2 | 1 | 1 | 1 |",
        "| affinity_wa | 1 | 0 | 0 | 0 |",
    ]
    assert [e for e in db.executes if e[0] == "games"] == [
        ("games", None, None, 2),
        ("games", ("id", "g1"), None, 2),
        ("games", ("id", "g3"), None, 2),
        ("games", ("id", "g4"), None, 2),
    ]


def test_a_week_with_a_change_says_by_how_much_in_the_header(monkeypatch, capsys, tmp_path):
    store = tmp_path / "store"
    _run(monkeypatch, capsys, _db(), "--store", str(store), "--date", "2026-10-07")
    db = _db()
    db.tables["teams"].append(_team("extra", club=None))
    _run(monkeypatch, capsys, db, "--store", str(store), "--date", "2026-10-14")

    report = (store / "health" / "2026-10-14.md").read_text(encoding="utf-8")
    assert "Live teams: 9. Open problems: 7 (+1 since 2026-10-07)." in report


def test_a_second_run_of_the_same_date_replaces_that_week_s_rows(monkeypatch, capsys, tmp_path):
    store = tmp_path / "store"
    _run(monkeypatch, capsys, _db(), "--store", str(store), "--date", "2026-10-07")
    _run(monkeypatch, capsys, _db(), "--store", str(store), "--date", "2026-10-14")
    first = _history_file(store)
    _run(monkeypatch, capsys, _db(), "--store", str(store), "--date", "2026-10-14")

    assert _history_file(store) == first
    assert Counter(r["date"] for r in first).keys() == {"2026-10-07", "2026-10-14"}
    report = (store / "health" / "2026-10-14.md").read_text(encoding="utf-8")
    assert _row(report, "NV").startswith("| NV | 2 | 0 | → |")
    assert "Open problems: 6 (unchanged since 2026-10-07)." in report


def test_re_running_an_earlier_week_keeps_later_weeks_and_compares_with_the_week_before(monkeypatch, capsys, tmp_path):
    store = tmp_path / "store"
    for day in ("2026-09-30", "2026-10-07", "2026-10-14"):
        _run(monkeypatch, capsys, _db(), "--store", str(store), "--date", day)
    later = [r for r in _history_file(store) if r["date"] == "2026-10-14"]
    db = _db()
    db.tables["teams"].append(_team("extra", club=None))
    _run(monkeypatch, capsys, db, "--store", str(store), "--date", "2026-10-07")

    assert later and [r for r in _history_file(store) if r["date"] == "2026-10-14"] == later
    report = (store / "health" / "2026-10-07.md").read_text(encoding="utf-8")
    assert "Open problems: 7 (+1 since 2026-09-30)." in report


def test_a_dry_run_prints_the_report_and_writes_nothing(monkeypatch, capsys, tmp_path):
    store = tmp_path / "store"

    code, out = _run(monkeypatch, capsys, _db(), "--store", str(store), "--date", "2026-10-14", "--dry-run")

    assert code == 0 and "# Team data health, 2026-10-14" in out and "DRY RUN" in out
    assert not store.exists()


@pytest.mark.parametrize(
    "argv, message",
    [(["--store", "rel"], "absolute path"), (["--date", "2026-13-01"], "--date: month must be in 1..12")],
    ids=["relative-store", "bad-date"],
)
def test_a_bad_store_or_date_exits_with_a_message(monkeypatch, capsys, tmp_path, argv, message):
    with pytest.raises(SystemExit) as stopped:
        _run(monkeypatch, capsys, _db(), *argv)
    assert message in str(stopped.value.code)
