"""The scheduled-cancellation rule the reconcile job reads from Stripe and writes to user_profiles.

It must agree with isCancellationScheduled in frontend/lib/stripe/server.ts, or
the scheduled reconcile writes a different canceling flag than the webhook.
"""

import sys
import types
from types import SimpleNamespace

try:
    import stripe  # noqa: F401
except ModuleNotFoundError:
    # CI installs requirements.lock, which does not carry the Stripe SDK; every
    # Stripe call below goes through a double.
    sys.modules["stripe"] = types.ModuleType("stripe")

import scripts.reconcile_stripe_subscriptions as reconcile_job  # noqa: E402
from scripts.reconcile_stripe_subscriptions import is_cancellation_scheduled  # noqa: E402

PERIOD_END = 1798761600


class _StripeObject(dict):
    """Item and attribute access, as stripe-python objects allow."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _sub(status="active", cancel_at=None, cancel_at_period_end=False, sub_id="sub_1"):
    return _StripeObject(
        id=sub_id,
        status=status,
        cancel_at=cancel_at,
        cancel_at_period_end=cancel_at_period_end,
        items=_StripeObject(data=[_StripeObject(current_period_end=PERIOD_END)]),
    )


def _stripe_returning(sub):
    return SimpleNamespace(Subscription=SimpleNamespace(list=lambda **_: SimpleNamespace(data=[sub])))


class _Db:
    """A supabase double that returns only the selected columns and records updates at execute()."""

    def __init__(self, rows):
        self.rows = rows
        self.executed_updates = []

    def table(self, _name):
        return _Query(self)


class _Query:
    def __init__(self, db):
        self.db = db
        self.columns = []
        self.payload = None
        self.filters = []

    def select(self, columns):
        self.columns = [c.strip() for c in columns.split(",")]
        return self

    @property
    def not_(self):
        return self

    def is_(self, column, value):
        self.filters.append((column, value))
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.payload is not None:
            self.db.executed_updates.append((self.filters, self.payload))
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[{c: row.get(c) for c in self.columns} for row in self.db.rows])


def _profile(**overrides):
    row = {
        "id": "user-1",
        "email": "member@example.com",
        "plan": "premium",
        "subscription_status": "active",
        "stripe_customer_id": "cus_1",
        "stripe_subscription_id": "sub_1",
        "subscription_period_end": None,
        "cancel_at_period_end": False,
    }
    row.update(overrides)
    return row


def test_reads_a_cancellation_scheduled_through_cancel_at_alone():
    assert is_cancellation_scheduled(_sub(cancel_at=PERIOD_END)) is True


def test_reads_a_cancellation_scheduled_through_cancel_at_period_end_alone():
    assert is_cancellation_scheduled(_sub(cancel_at_period_end=True)) is True


def test_is_false_with_neither_set():
    assert is_cancellation_scheduled(_sub()) is False


def test_applies_to_trials_and_past_due_subscriptions():
    assert is_cancellation_scheduled(_sub(status="trialing", cancel_at=PERIOD_END)) is True
    assert is_cancellation_scheduled(_sub(status="past_due", cancel_at=PERIOD_END)) is True


def test_is_false_for_a_subscription_that_no_longer_grants_premium():
    for status in ("canceled", "unpaid", "paused"):
        assert is_cancellation_scheduled(_sub(status=status, cancel_at=PERIOD_END)) is False
        assert is_cancellation_scheduled(_sub(status=status, cancel_at_period_end=True)) is False


def test_check_reports_a_cancel_at_only_cancellation(monkeypatch):
    monkeypatch.setattr(reconcile_job, "stripe", _stripe_returning(_sub(cancel_at=PERIOD_END)))
    assert reconcile_job.check_stripe_subscription("cus_1")["cancel_at_period_end"] is True


def test_reconcile_fixes_a_profile_whose_only_drift_is_the_canceling_flag(monkeypatch):
    monkeypatch.setattr(reconcile_job, "stripe", _stripe_returning(_sub(cancel_at=PERIOD_END)))
    monkeypatch.setattr(reconcile_job.time, "sleep", lambda _: None)
    db = _Db([_profile()])

    mismatches, checked = reconcile_job.reconcile(db, dry_run=False)

    assert checked == 1
    assert [m["after"]["cancel_at_period_end"] for m in mismatches] == [True]
    assert len(db.executed_updates) == 1
    filters, payload = db.executed_updates[0]
    assert ("id", "user-1") in filters
    assert payload["cancel_at_period_end"] is True


def test_reconcile_writes_nothing_on_a_dry_run(monkeypatch):
    monkeypatch.setattr(reconcile_job, "stripe", _stripe_returning(_sub(cancel_at=PERIOD_END)))
    monkeypatch.setattr(reconcile_job.time, "sleep", lambda _: None)
    db = _Db([_profile()])

    mismatches, _ = reconcile_job.reconcile(db, dry_run=True)

    assert len(mismatches) == 1
    assert db.executed_updates == []


def test_reconcile_leaves_a_profile_that_already_agrees(monkeypatch):
    monkeypatch.setattr(reconcile_job, "stripe", _stripe_returning(_sub(cancel_at=PERIOD_END)))
    monkeypatch.setattr(reconcile_job.time, "sleep", lambda _: None)
    db = _Db([_profile(cancel_at_period_end=True)])

    mismatches, _ = reconcile_job.reconcile(db, dry_run=False)

    assert mismatches == []
    assert db.executed_updates == []
