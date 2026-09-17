"""The reconcile job repairs plan, status and subscription id, and leaves the canceling flag alone.

The Stripe webhook starts the Beehiiv canceling and reactivation emails only when it sees
user_profiles.cancel_at_period_end change, so a reconcile write to that column would swallow
the transition for a webhook that arrives late.
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


def _quiet(monkeypatch, sub):
    monkeypatch.setattr(reconcile_job, "stripe", _stripe_returning(sub))
    monkeypatch.setattr(reconcile_job.time, "sleep", lambda _: None)


def test_reconcile_fixes_a_status_mismatch_without_writing_the_canceling_flag(monkeypatch):
    _quiet(monkeypatch, _sub(cancel_at=PERIOD_END))
    db = _Db([_profile(subscription_status="trialing")])

    mismatches, checked = reconcile_job.reconcile(db, dry_run=False)

    assert checked == 1
    assert len(mismatches) == 1
    assert len(db.executed_updates) == 1
    filters, payload = db.executed_updates[0]
    assert ("id", "user-1") in filters
    assert payload["subscription_status"] == "active"
    assert "cancel_at_period_end" not in payload


def test_reconcile_leaves_a_profile_whose_only_drift_is_the_canceling_flag(monkeypatch):
    _quiet(monkeypatch, _sub(cancel_at=PERIOD_END))
    db = _Db([_profile()])

    mismatches, _ = reconcile_job.reconcile(db, dry_run=False)

    assert mismatches == []
    assert db.executed_updates == []


def test_reconcile_writes_nothing_on_a_dry_run(monkeypatch):
    _quiet(monkeypatch, _sub(cancel_at=PERIOD_END))
    db = _Db([_profile(subscription_status="trialing")])

    mismatches, _ = reconcile_job.reconcile(db, dry_run=True)

    assert len(mismatches) == 1
    assert db.executed_updates == []
