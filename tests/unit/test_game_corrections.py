"""The shared score-correction write must never raise, and must say what it did."""

from types import SimpleNamespace

import pytest

from src.etl.game_corrections import apply_score_correction, moves_both_sides

ORIGINAL = {"home_score": 2, "away_score": 0}
CORRECTED = {"home_score": 3, "away_score": 0, "result": "W"}


class _Table:
    """game_corrections double: records at execute(), raising what the test asks it to."""

    def __init__(self, db):
        self._db = db
        self._call = None

    def insert(self, payload):
        self._call = ("insert", payload)
        return self

    def update(self, payload):
        self._call = ("update", payload)
        return self

    def select(self, columns):
        self._call = ("select", columns)
        return self

    def eq(self, field, value):
        self._call = (*self._call, (field, value))
        return self

    def execute(self):
        self._db.calls.append(self._call)
        if self._call[0] in self._db.fail:
            raise RuntimeError(f"{self._call[0]} refused")
        if self._call[0] == "select":
            return SimpleNamespace(data=[{"status": self._db.status}])
        return SimpleNamespace(data=[{"id": "corr-1"}])


class _Rpc:
    def __init__(self, db, name, params):
        self._db = db
        self._call = ("rpc", name, params)

    def execute(self):
        self._db.calls.append(self._call)
        if "rpc" in self._db.fail:
            raise RuntimeError("Correction not found or not pending")
        return SimpleNamespace(data=None)


class _Db:
    def __init__(self, fail=(), status="pending"):
        self.calls = []
        self.fail = set(fail)
        self.status = status

    def table(self, name):
        assert name == "game_corrections", name
        return _Table(self)

    def rpc(self, name, params):
        return _Rpc(self, name, params)


def _apply(db):
    return apply_score_correction(
        db,
        game_uid="tgs:2026-10-04:a:b",
        original=ORIGINAL,
        corrected=CORRECTED,
        reason="tgs schedule now reports a different score",
        submitted_by="reconcile_tgs_scores",
    )


def test_a_correction_is_filed_as_a_score_correction_and_applied_by_the_submitter():
    db = _Db()

    assert _apply(db) is True

    assert db.calls == [
        (
            "insert",
            {
                "original_game_uid": "tgs:2026-10-04:a:b",
                "correction_type": "score",
                "original_values": ORIGINAL,
                "corrected_values": CORRECTED,
                "reason": "tgs schedule now reports a different score",
                "submitted_by": "reconcile_tgs_scores",
            },
        ),
        ("rpc", "apply_game_correction", {"correction_id": "corr-1", "approver_name": "reconcile_tgs_scores"}),
    ]


def test_a_correction_that_fails_to_apply_is_rejected_so_it_does_not_stay_pending():
    db = _Db(fail={"rpc"})

    assert _apply(db) is False

    assert db.calls[-1] == ("update", {"status": "rejected"}, ("id", "corr-1"), ("status", "pending"))


def test_a_response_lost_after_the_server_approved_the_correction_still_counts_as_applied():
    db = _Db(fail={"rpc"}, status="approved")

    assert _apply(db) is True

    assert [call[0] for call in db.calls] == ["insert", "rpc", "select"]


def test_a_correction_still_pending_after_a_failure_is_rejected_not_counted():
    db = _Db(fail={"rpc"}, status="pending")

    assert _apply(db) is False

    assert [call[0] for call in db.calls] == ["insert", "rpc", "select", "update"]


def test_a_status_that_cannot_be_read_is_not_taken_as_approved_and_the_row_is_still_rejected():
    db = _Db(fail={"rpc", "select"})

    assert _apply(db) is False

    assert db.calls[-1] == ("update", {"status": "rejected"}, ("id", "corr-1"), ("status", "pending"))


def test_a_reject_that_also_fails_still_returns_false_instead_of_raising():
    db = _Db(fail={"rpc", "update"})

    assert _apply(db) is False


def test_a_correction_that_could_not_be_filed_has_nothing_to_reject():
    db = _Db(fail={"insert"})

    assert _apply(db) is False

    assert [call[0] for call in db.calls] == ["insert"]


@pytest.mark.parametrize(
    "stored, incoming, expected",
    [
        ((2, 0), (3, 0), False),
        ((2, 0), (2, 1), False),
        ((2, 0), (3, 1), True),
        ((2, 0), (0, 2), False),
        ((2, 0), (2, 0), False),
        ((1, 1), (0, 2), True),
        ((1, 1), (1, 1), False),
        ((0, 0), (3, 1), True),
        ((3, 1), (1, 3), False),
    ],
)
def test_a_score_moves_both_sides_unless_one_is_unchanged_or_the_pair_is_swapped(stored, incoming, expected):
    assert moves_both_sides(stored, incoming) is expected
