"""The English-team exclusion must grow only from English associations, and --execute must replay the
reviewed snapshot rather than recompute it."""

import json
import sys
from collections import Counter
from types import SimpleNamespace

import pytest

import scripts.exclude_english_teams as exclusion
from scripts.exclude_english_teams import classify, grow, latest_answers, qualifies

LISTED = "team-listed"
NO_ASSOC = "team-no-assoc"
NO_ASSOC_2 = "team-no-assoc-2"
US = "team-us"
UNKNOWN = "team-unknown"
UNKNOWN_2 = "team-unknown-2"
CANDIDATE = "team-candidate"


def _probe(team_id, outcome, probed_at, state=None):
    return {
        "team_id_master": team_id,
        "outcome": outcome,
        "probed_at": probed_at,
        "reported_state_code": state,
    }


def test_a_failed_request_does_not_hide_an_earlier_answer():
    rows = [
        _probe(CANDIDATE, "request failed (ReadTimeout)", "2026-09-10T00:00:00+00:00"),
        _probe(CANDIDATE, "mapped", "2026-09-01T00:00:00+00:00", "OH"),
    ]

    assert latest_answers(rows) == {CANDIDATE: ("mapped", "OH")}


def test_the_newest_answer_wins():
    rows = [
        _probe(CANDIDATE, "unmapped code Kent", "2026-09-01T00:00:00+00:00"),
        _probe(CANDIDATE, "mapped", "2026-09-10T00:00:00+00:00", "OH"),
    ]

    assert latest_answers(rows) == {CANDIDATE: ("mapped", "OH")}


def test_only_english_associations_seed_the_list():
    seeds, no_association, confirmed_us, other = classify(
        {
            "team-kent": ("unmapped code Kent", None),
            "team-gbr": ("unmapped code GBR", None),
            "team-mexico": ("unmapped code MEX", None),
            NO_ASSOC: ("no association in payload", None),
            US: ("mapped", "OH"),
        }
    )

    assert seeds == {"team-kent": "Kent", "team-gbr": "GBR"}
    assert no_association == {NO_ASSOC}
    assert confirmed_us == {US}
    assert other == Counter({"MEX": 1})


def test_the_national_association_is_a_us_team_even_though_it_names_no_state():
    _, _, confirmed_us, other = classify({US: ("unmapped code USA", None)})

    assert confirmed_us == {US}
    assert other == Counter()


def test_gotsports_unset_default_state_confirms_nothing():
    seeds, no_association, confirmed_us, other = classify({CANDIDATE: ("mapped", "AL")})

    assert (seeds, no_association, confirmed_us, other) == ({}, set(), set(), Counter())


def _qualifies(opponents, team_id=CANDIDATE):
    return qualifies(team_id, opponents, {LISTED}, {NO_ASSOC, NO_ASSOC_2}, {US})


def test_a_team_meeting_every_condition_qualifies():
    assert _qualifies([LISTED, NO_ASSOC, UNKNOWN]) is True


def test_a_confirmed_us_team_never_qualifies():
    assert _qualifies([LISTED, NO_ASSOC, UNKNOWN], team_id=US) is False


def test_a_team_with_no_listed_opponent_does_not_qualify():
    assert _qualifies([NO_ASSOC, NO_ASSOC_2, UNKNOWN]) is False


def test_a_team_with_fewer_than_half_english_like_opponents_does_not_qualify():
    assert _qualifies([LISTED, UNKNOWN, UNKNOWN_2]) is False


def test_exactly_half_english_like_opponents_qualifies():
    assert _qualifies([LISTED, UNKNOWN]) is True


def test_a_fifth_of_opponents_confirmed_us_does_not_qualify():
    assert _qualifies([LISTED, NO_ASSOC, NO_ASSOC_2, UNKNOWN, US]) is False


def _games_loader(games, loaded):
    def load(team_ids):
        loaded.extend(team_ids)
        out = {t: Counter() for t in team_ids}
        for home, away in games:
            if home in out:
                out[home][away] += 1
            if away in out:
                out[away][home] += 1
        return out

    return load


def test_grow_reaches_a_second_ring_and_leaves_an_unconnected_island_out():
    games = [
        ("seed", "ring-1"),
        ("ring-1", "ring-2"),
        ("ring-2", "no-assoc-far"),
        ("island-a", "island-b"),
        ("seed", US),
        (US, "us-2"),
    ]
    no_association = {"no-assoc-far", "island-a", "island-b"}
    loaded = []

    listed, _ = grow({"seed": "Kent"}, _games_loader(games, loaded), no_association, {US})

    assert set(listed) == {"seed", "ring-1", "ring-2", "no-assoc-far"}
    assert listed["seed"] == {"association": "Kent"}
    assert listed["ring-1"]["round"] == 1
    assert listed["ring-2"]["round"] == 2
    assert listed["no-assoc-far"]["round"] == 3
    assert US not in loaded


class _Query:
    """PostgREST builder double: applies the filters main() sends and records only at execute()."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._op = "select"
        self._predicates = []
        self._window = None
        self._order = None
        self._payload = None
        self._columns = None

    def select(self, columns):
        # PostgREST ignores the whitespace callers put after a comma.
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def insert(self, rows):
        self._op = "insert"
        self._payload = rows
        return self

    def eq(self, field, value):
        self._predicates.append(lambda r: r.get(field) == value)
        return self

    def in_(self, field, values):
        self._predicates.append(lambda r: r.get(field) in values)
        return self

    def order(self, field, desc=False):
        self._order = (field, desc)
        return self

    def range(self, start, end):
        self._window = (start, end)
        return self

    def __getattr__(self, name):
        raise AssertionError(f"unmodeled builder method {name!r}")

    def execute(self):
        self._db.executed.append((self._table, self._op))
        table = self._db.rows.setdefault(self._table, [])
        if self._op == "insert":
            present = {r["team_id_master"] for r in table}
            for row in self._payload:
                if row["team_id_master"] in present:
                    raise AssertionError("23505: duplicate key value violates unique constraint")
            table.extend(dict(r) for r in self._payload)
            return SimpleNamespace(data=[dict(r) for r in self._payload])
        rows = [r for r in table if all(p(r) for p in self._predicates)]
        if self._order:
            field, desc = self._order
            rows = sorted(rows, key=lambda r: r[field], reverse=desc)
        if self._window:
            rows = rows[self._window[0] : self._window[1] + 1]
        return SimpleNamespace(data=[{c: r[c] for c in self._columns} for r in rows])


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def table(self, name):
        return _Query(self, name)


def _team(team_id, state="UT", deprecated=False):
    return {"team_id_master": team_id, "team_name": "U16", "club_name": f"{team_id} FC", "state_code": state,
            "is_deprecated": deprecated}


def _game(game_id, home, away, excluded=False):
    return {"id": game_id, "home_team_master_id": home, "away_team_master_id": away, "is_excluded": excluded}


def _league_db(extra_games=(), extra_teams=(), extra_probes=(), merges=()):
    return _DB(
        {
            "team_state_probe_log": [
                {"id": 1, **_probe("seed", "unmapped code Kent", "2026-09-01T00:00:00+00:00")},
                {"id": 2, **_probe(US, "mapped", "2026-09-01T00:00:00+00:00", "MI")},
                *({"id": 10 + i, **p} for i, p in enumerate(extra_probes)),
            ],
            "games": [
                _game("g1", "seed", "ring-1"),
                _game("g2", "seed", US),
                _game("g3", "ring-1", "us-2"),
                _game("g4", "us-2", US),
                _game("g5", "us-2", "us-3"),
                _game("g6", "seed", "us-3", excluded=True),
                *extra_games,
            ],
            "teams": [_team("seed"), _team("ring-1"), _team(US, state="MI"), _team("us-2", state="MI"),
                      _team("us-3", state="MI"), *extra_teams],
            "rankings_full": [{"team_id": "seed"}],
            "team_merge_map": [{"deprecated_team_id": d, "canonical_team_id": c} for d, c in merges],
            "team_ranking_exclusions": [],
        }
    )


def _run_main(monkeypatch, db, argv):
    monkeypatch.setattr(exclusion, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["exclude_english_teams.py", *argv])
    return exclusion.main()


def test_default_run_writes_the_snapshot_and_nothing_to_the_database(monkeypatch, tmp_path):
    db = _league_db()
    snapshot = tmp_path / "snapshot.json"

    assert _run_main(monkeypatch, db, ["--snapshot", str(snapshot)]) == 0

    assert [call for call in db.executed if call[1] != "select"] == []
    teams = {t["team_id_master"]: t for t in json.loads(snapshot.read_text(encoding="utf-8"))["teams"]}
    assert set(teams) == {"seed", "ring-1"}
    assert teams["seed"]["ranked"] is True
    assert teams["ring-1"]["ranked"] is False
    assert teams["seed"]["games_against_unlisted_teams"] == 1
    assert teams["ring-1"]["games_against_unlisted_teams"] == 1
    assert teams["ring-1"]["evidence"] == {
        "round": 1,
        "opponents": 2,
        "listed_opponents": 1,
        "english_like_opponents": 1,
        "confirmed_us_opponents": 0,
    }


def test_a_deprecated_team_is_listed_under_the_team_that_absorbed_it(monkeypatch, tmp_path):
    """The loader compares merge-resolved ids, so the surviving team is what must be listed."""
    db = _league_db(
        extra_games=[_game("g7", "seed", "old-ring")],
        extra_teams=[_team("old-ring", deprecated=True), _team("new-ring")],
        merges=[("old-ring", "new-ring")],
    )
    snapshot = tmp_path / "snapshot.json"

    assert _run_main(monkeypatch, db, ["--snapshot", str(snapshot)]) == 0

    written = json.loads(snapshot.read_text(encoding="utf-8"))
    assert {t["team_id_master"] for t in written["teams"]} == {"seed", "ring-1", "new-ring"}
    assert written["skipped_deprecated_or_missing"] == 0


def test_a_us_answer_filed_under_a_merged_away_id_still_vetoes_the_survivor(monkeypatch, tmp_path):
    """The dangerous half of the same fault: a veto lost to a merge lists a confirmed US team."""
    db = _league_db(
        extra_probes=[_probe("old-us", "mapped", "2026-09-01T00:00:00+00:00", "CA")],
        # Two games against the seed and nothing else: without the veto it would qualify.
        extra_games=[_game("g7", "seed", "new-us"), _game("g8", "new-us", "seed")],
        extra_teams=[_team("old-us", state="CA", deprecated=True), _team("new-us", state="CA")],
        merges=[("old-us", "new-us")],
    )
    snapshot = tmp_path / "snapshot.json"

    assert _run_main(monkeypatch, db, ["--snapshot", str(snapshot)]) == 0

    listed = {t["team_id_master"] for t in json.loads(snapshot.read_text(encoding="utf-8"))["teams"]}
    assert listed == {"seed", "ring-1"}


def test_games_stored_under_an_absorbed_alias_count_for_the_surviving_team(monkeypatch, tmp_path):
    """Games keep the id they were stored with, so a survivor's record spans both ids."""
    db = _league_db(
        extra_games=[_game("g7", "old-ring", "seed"), _game("g8", "new-ring", "us-2")],
        extra_teams=[_team("old-ring", deprecated=True), _team("new-ring")],
        merges=[("old-ring", "new-ring")],
    )
    snapshot = tmp_path / "snapshot.json"

    assert _run_main(monkeypatch, db, ["--snapshot", str(snapshot)]) == 0

    teams = {t["team_id_master"]: t for t in json.loads(snapshot.read_text(encoding="utf-8"))["teams"]}
    assert set(teams) == {"seed", "ring-1", "new-ring"}
    assert teams["new-ring"]["evidence"]["opponents"] == 2
    assert teams["new-ring"]["games_against_unlisted_teams"] == 1


def test_the_dry_run_reads_every_page_and_every_batch(monkeypatch, tmp_path):
    """Fixtures under one page or one 100-id batch cannot see a loop that stops after the first."""
    extra_probes = [
        _probe(f"filler-{i:04d}", "no association in payload", "2026-08-01T00:00:00+00:00") for i in range(1000)
    ]
    extra_probes.append(_probe("late-seed", "unmapped code Kent", "2026-09-02T00:00:00+00:00"))
    ring = [f"late-ring-{i:03d}" for i in range(120)]
    db = _league_db(
        extra_probes=extra_probes,
        extra_games=[_game(f"lg{i}", "late-seed", t) for i, t in enumerate(ring)],
        extra_teams=[_team("late-seed", state="CA"), *(_team(t, state="CA") for t in ring)],
    )
    snapshot = tmp_path / "snapshot.json"

    assert _run_main(monkeypatch, db, ["--snapshot", str(snapshot)]) == 0

    listed = {t["team_id_master"] for t in json.loads(snapshot.read_text(encoding="utf-8"))["teams"]}
    assert "late-seed" in listed, "the seed sits past the first page of the probe ledger"
    assert set(ring) <= listed, "the ring spans more than one 100-id batch"
    assert len(listed) == 123


def test_a_dry_run_refuses_to_overwrite_an_existing_snapshot(monkeypatch, tmp_path):
    snapshot = tmp_path / "reviewed.json"
    snapshot.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit, match="may hold a reviewed list"):
        _run_main(monkeypatch, _league_db(), ["--snapshot", str(snapshot)])

    assert snapshot.read_text(encoding="utf-8") == "{}"


def test_execute_inserts_only_the_reviewed_rows_not_yet_excluded(monkeypatch, tmp_path):
    db = _league_db()
    db.rows["team_ranking_exclusions"] = [
        {"team_id_master": "already", "reason": "x", "evidence": None, "excluded_by": "earlier"}
    ]
    snapshot = tmp_path / "reviewed.json"
    snapshot.write_text(
        json.dumps({"teams": [{"team_id_master": "ring-1", "evidence": {"round": 1}},
                              {"team_id_master": "already", "evidence": {"round": 1}}]}),
        encoding="utf-8",
    )
    log = tmp_path / "log.json"

    assert _run_main(monkeypatch, db, ["--execute", "--snapshot", str(snapshot), "--out", str(log)]) == 0

    assert [r["team_id_master"] for r in db.rows["team_ranking_exclusions"]] == ["already", "ring-1"]
    assert db.rows["team_ranking_exclusions"][1] == {
        "team_id_master": "ring-1",
        "reason": "English youth league team, not a US team",
        "evidence": {"round": 1},
        "excluded_by": "exclude_english_teams",
    }
    assert json.loads(log.read_text(encoding="utf-8")) == {
        "applied": True,
        "planned": ["ring-1"],
        "team_ids": ["ring-1"],
    }
    assert ("games", "select") not in db.executed


def test_a_failed_batch_leaves_a_log_naming_only_the_rows_this_run_wrote(monkeypatch, tmp_path):
    """Undo reads team_ids, so a row another run owns must never appear there."""
    db = _league_db()
    db.rows["team_ranking_exclusions"] = []
    written_by_another_run = {"team_id_master": "team-0100", "reason": "x", "evidence": None, "excluded_by": "other"}
    mine = [{"team_id_master": f"team-{i:04d}", "evidence": {"round": 1}} for i in range(152)]
    snapshot = tmp_path / "reviewed.json"
    snapshot.write_text(json.dumps({"teams": mine}), encoding="utf-8")
    log = tmp_path / "log.json"

    # The other run's row lands between this run's two batches, so the second one collides.
    original_execute = _Query.execute

    def execute(self):
        result = original_execute(self)
        if self._table == "team_ranking_exclusions" and self._op == "insert":
            db.rows["team_ranking_exclusions"].append(dict(written_by_another_run))
        return result

    monkeypatch.setattr(_Query, "execute", execute)

    with pytest.raises(AssertionError, match="23505"):
        _run_main(monkeypatch, db, ["--execute", "--snapshot", str(snapshot), "--out", str(log)])

    recorded = json.loads(log.read_text(encoding="utf-8"))
    assert recorded["applied"] is True
    assert recorded["team_ids"] == [f"team-{i:04d}" for i in range(100)]
    assert len(recorded["planned"]) == 152
    assert written_by_another_run["team_id_master"] not in recorded["team_ids"]


def test_execute_refuses_to_overwrite_an_existing_rollback_log(monkeypatch, tmp_path):
    db = _league_db()
    snapshot = tmp_path / "reviewed.json"
    snapshot.write_text(json.dumps({"teams": [{"team_id_master": "ring-1", "evidence": {}}]}), encoding="utf-8")
    log = tmp_path / "log.json"
    log.write_text('{"applied": true, "team_ids": ["earlier-run"]}', encoding="utf-8")

    with pytest.raises(SystemExit, match="only rollback record"):
        _run_main(monkeypatch, db, ["--execute", "--snapshot", str(snapshot), "--out", str(log)])

    assert json.loads(log.read_text(encoding="utf-8"))["team_ids"] == ["earlier-run"]
    assert [call for call in db.executed if call[1] == "insert"] == []
