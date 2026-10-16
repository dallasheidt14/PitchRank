"""A scored game whose re-scrape reports a different score must take the new score.

GotSport edits scores after posting them, and a stored score that was only the first one seen
(a 0-0 placeholder, a mid-tournament entry) otherwise stays for good: the importer filed the
re-scrape as a plain duplicate, and a raw UPDATE on an immutable row is rejected by the trigger.
"""

from types import SimpleNamespace

from tests.unit.test_enhanced_pipeline_fixture_score_fill import (
    _DB,
    AFC,
    GREMIO,
    RESULT_UID,
    _import_pipeline,
    _incoming,
    _row,
)


class _Corrections:
    """game_corrections double: records at execute(), and refuses what production refuses."""

    def __init__(self, db, op, payload=None):
        self._db = db
        self._op = op
        self._payload = payload
        self._match = None
        self._status = None

    def eq(self, field, value):
        assert field in ("id", "status"), field
        if field == "id":
            self._match = value
        else:
            self._status = value
        return self

    def execute(self):
        if self._op == "insert":
            row = {"id": f"corr-{len(self._db.corrections) + 1}", "status": "pending", **self._payload}
            self._db.corrections.append(row)
            return SimpleNamespace(data=[row])
        rows = [
            c for c in self._db.corrections if c["id"] == self._match and self._status in (None, c["status"])
        ]
        for row in rows:
            row.update(self._payload)
        return SimpleNamespace(data=rows)


class _ApplyCorrection:
    """Mirrors apply_game_correction: only a pending row, a score type writes home, away and result."""

    def __init__(self, db, params):
        self._db = db
        self._params = params

    def execute(self):
        if self._db.apply_error:
            raise self._db.apply_error
        [row] = [c for c in self._db.corrections if c["id"] == self._params["correction_id"]]
        if row["status"] != "pending":
            raise RuntimeError(f"Correction not found or not pending: {row['id']}")
        [game] = [g for g in self._db.games if g["game_uid"] == row["original_game_uid"]]
        game["home_score"] = row["corrected_values"]["home_score"]
        game["away_score"] = row["corrected_values"]["away_score"]
        game["result"] = row["corrected_values"]["result"]
        row["status"] = "approved"
        if self._db.error_after_apply:
            raise self._db.error_after_apply
        return SimpleNamespace(data=None)


class _CorrectionsDB(_DB):
    def __init__(self, games):
        super().__init__(games)
        self.corrections = []
        self.apply_error = None
        self.error_after_apply = None

    def table(self, name):
        if name == "game_corrections":
            return _CorrectionsTable(self)
        return super().table(name)

    def rpc(self, name, params):
        if name == "batch_backfill_null_scores":
            return super().rpc(name, params)
        assert name == "apply_game_correction", name
        return _ApplyCorrection(self, params)


class _CorrectionsTable:
    def __init__(self, db):
        self._db = db

    def insert(self, payload):
        return _Corrections(self._db, "insert", payload)

    def update(self, payload):
        return _Corrections(self._db, "update", payload)


def _stored(home, away, home_score, away_score):
    return _row(RESULT_UID, home, away, home_score, away_score)


def test_a_changed_score_replaces_the_stored_one_and_leaves_the_old_on_record(monkeypatch):
    game = _stored(GREMIO, AFC, 0, 0)
    db = _CorrectionsDB([game])

    inserted, pipeline = _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 3, 1)], uid_check=True)

    assert inserted == []
    assert (game["home_score"], game["away_score"], game["result"]) == (3, 1, "W")
    [correction] = db.corrections
    assert correction["original_values"] == {"home_score": 0, "away_score": 0}
    assert correction["corrected_values"] == {"home_score": 3, "away_score": 1, "result": "W"}
    assert correction["status"] == "approved"
    assert (pipeline.metrics.scores_corrected, pipeline.metrics.scores_correct_failed) == (1, 0)


def test_a_changed_score_read_from_the_other_side_lands_on_the_stored_sides(monkeypatch):
    game = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([game])

    _import_pipeline(monkeypatch, db, [_incoming(AFC, GREMIO, 4, 0)], uid_check=True)

    assert (game["home_score"], game["away_score"]) == (0, 4)


def test_the_same_score_read_from_the_other_side_is_not_a_change(monkeypatch):
    game = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([game])

    _, pipeline = _import_pipeline(monkeypatch, db, [_incoming(AFC, GREMIO, 0, 2)], uid_check=True)

    assert db.corrections == []
    assert pipeline.metrics.scores_corrected == 0


def test_an_unscored_fixture_is_filled_not_corrected(monkeypatch):
    game = _stored(GREMIO, AFC, None, None)
    db = _CorrectionsDB([game])

    _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 3, 1)], uid_check=True)

    assert db.corrections == []
    assert (game["home_score"], game["away_score"]) == (3, 1)


def test_a_provider_outside_the_correction_list_keeps_its_stored_score(monkeypatch):
    game = _row(RESULT_UID.replace("gotsport:", "tgs:"), GREMIO, AFC, 0, 0)
    db = _CorrectionsDB([game])
    incoming = {**_incoming(GREMIO, AFC, 3, 1), "provider": "tgs"}

    _, pipeline = _import_pipeline(monkeypatch, db, [incoming], provider="tgs", uid_check=True)

    assert pipeline.metrics.duplicates_found == 1
    assert db.corrections == []
    assert (game["home_score"], game["away_score"]) == (0, 0)


def test_a_dry_run_writes_nothing(monkeypatch):
    game = _stored(GREMIO, AFC, 0, 0)
    db = _CorrectionsDB([game])

    _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 3, 1)], dry_run=True, uid_check=True)

    assert db.corrections == []
    assert (game["home_score"], game["away_score"]) == (0, 0)


def test_a_correction_that_fails_to_apply_is_rejected_and_counted(monkeypatch):
    game = _stored(GREMIO, AFC, 0, 0)
    db = _CorrectionsDB([game])
    db.apply_error = RuntimeError("Game not found")

    _, pipeline = _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 3, 1)], uid_check=True)

    [correction] = db.corrections
    assert correction["status"] == "rejected"
    assert (game["home_score"], game["away_score"]) == (0, 0)
    assert (pipeline.metrics.scores_corrected, pipeline.metrics.scores_correct_failed) == (0, 1)


def test_a_correction_applied_before_the_client_saw_an_error_stays_approved(monkeypatch):
    game = _stored(GREMIO, AFC, 0, 0)
    db = _CorrectionsDB([game])
    db.error_after_apply = TimeoutError("response lost")

    _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 3, 1)], uid_check=True)

    [correction] = db.corrections
    assert correction["status"] == "approved"
    assert (game["home_score"], game["away_score"]) == (3, 1)


def test_two_meetings_of_the_same_teams_in_one_batch_are_not_read_as_a_changed_score(monkeypatch):
    game = _stored(GREMIO, AFC, 2, 0)
    db = _CorrectionsDB([game])
    pool_game, final = _incoming(GREMIO, AFC, 2, 0), _incoming(GREMIO, AFC, 1, 3)

    _import_pipeline(monkeypatch, db, [pool_game, final], uid_check=True)

    assert db.corrections == []
    assert (game["home_score"], game["away_score"]) == (2, 0)


def test_both_perspectives_of_one_changed_game_give_one_correction(monkeypatch):
    game = _stored(GREMIO, AFC, 0, 0)
    db = _CorrectionsDB([game])

    _, pipeline = _import_pipeline(
        monkeypatch, db, [_incoming(GREMIO, AFC, 3, 1), _incoming(AFC, GREMIO, 1, 3, result="L")], uid_check=True
    )

    assert len(db.corrections) == 1
    assert (game["home_score"], game["away_score"]) == (3, 1)
    assert pipeline.metrics.scores_corrected == 1


def test_a_changed_score_without_a_result_is_counted_and_not_written(monkeypatch):
    game = _stored(GREMIO, AFC, 0, 0)
    db = _CorrectionsDB([game])
    incoming = _incoming(GREMIO, AFC, 3, 1)
    incoming["result"] = None

    _, pipeline = _import_pipeline(monkeypatch, db, [incoming], uid_check=True)

    assert db.corrections == []
    assert (game["home_score"], game["away_score"]) == (0, 0)
    assert pipeline.metrics.scores_correct_failed == 1
