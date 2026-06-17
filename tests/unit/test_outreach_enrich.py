"""Unit tests for outreach enrichment: merge, email pick, collision -> held, resumability."""

from postgrest.exceptions import APIError

from src.outreach import enrich


def test_merge_confidence_preserves_tokens_and_does_not_mutate():
    personalization = {"state": "AZ", "league_mix": "ECNL"}
    merged = enrich.merge_confidence(personalization, 87.0)
    assert merged == {"state": "AZ", "league_mix": "ECNL", "enrich_confidence": 87.0}
    assert personalization == {"state": "AZ", "league_mix": "ECNL"}


def test_pick_domain_email_prefers_generic_then_confidence():
    emails = [
        {"value": "coach@x.org", "type": "personal", "confidence": 90},
        {"value": "info@x.org", "type": "generic", "confidence": 70},
        {"value": "contact@x.org", "type": "generic", "confidence": 85},
    ]
    assert enrich._pick_domain_email(emails)["value"] == "contact@x.org"
    assert enrich._pick_domain_email([]) is None


# --- Minimal Supabase client fake (only the chains enrich_queued uses) ---


class _Result:
    def __init__(self, data):
        self.data = data


class _Select:
    def __init__(self, table):
        self.table = table
        self._limit = None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = [dict(r) for r in self.table.rows if r.get("status") == "queued" and r.get("contact") is None]
        if self._limit:
            rows = rows[: self._limit]
        return _Result(rows)


class _Update:
    def __init__(self, table, values):
        self.table = table
        self.values = values
        self._flt = None

    def eq(self, col, val):
        self._flt = (col, val)
        return self

    def execute(self):
        self.table.apply_update(self.values, self._flt)
        return _Result([])


class _Table:
    def __init__(self, rows, taken_emails=()):
        self.rows = rows
        self.taken = {e.lower() for e in taken_emails}

    def select(self, *a, **k):
        return _Select(self)

    def update(self, values):
        return _Update(self, values)

    def apply_update(self, values, flt):
        col, val = flt
        for row in self.rows:
            if row.get(col) == val:
                if "contact" in values and values["contact"].lower() in self.taken:
                    raise APIError({"code": "23505", "message": "duplicate key", "details": "", "hint": None})
                row.update(values)


class _Client:
    def __init__(self, table):
        self._table = table

    def table(self, _name):
        return self._table


def test_enrich_resolves_and_merges(monkeypatch):
    rows = [
        {"id": "a", "status": "queued", "contact": None, "source_domain": "az.org", "personalization": {"state": "AZ"}},
        {"id": "b", "status": "queued", "contact": None, "source_domain": "ga.org", "personalization": {"state": "GA"}},
    ]
    client = _Client(_Table(rows))
    monkeypatch.setattr(enrich, "find_email", lambda domain, full_name=None: (f"info@{domain}", 80.0))

    stats = enrich.enrich_queued(client=client)

    assert stats == {"resolved": 2, "no_email": 0, "held_collision": 0}
    assert rows[0]["contact"] == "info@az.org"
    assert rows[0]["personalization"] == {"state": "AZ", "enrich_confidence": 80.0}


def test_enrich_collision_sends_row_to_held(monkeypatch):
    rows = [
        {"id": "a", "status": "queued", "contact": None, "source_domain": "az.org", "personalization": {}},
    ]
    client = _Client(_Table(rows, taken_emails=["info@az.org"]))
    monkeypatch.setattr(enrich, "find_email", lambda domain, full_name=None: ("info@az.org", 75.0))

    stats = enrich.enrich_queued(client=client)

    assert stats == {"resolved": 0, "no_email": 0, "held_collision": 1}
    assert rows[0]["status"] == "held"
    assert rows[0]["contact"] is None


def test_enrich_skips_already_enriched_rows(monkeypatch):
    rows = [
        {"id": "a", "status": "queued", "contact": "info@az.org", "source_domain": "az.org", "personalization": {}},
    ]
    client = _Client(_Table(rows))

    def _boom(*a, **k):
        raise AssertionError("find_email should not be called for already-enriched rows")

    monkeypatch.setattr(enrich, "find_email", _boom)

    stats = enrich.enrich_queued(client=client)

    assert stats == {"resolved": 0, "no_email": 0, "held_collision": 0}


def test_enrich_no_source_domain_counts_no_email(monkeypatch):
    rows = [{"id": "a", "status": "queued", "contact": None, "source_domain": None, "personalization": {}}]
    client = _Client(_Table(rows))

    def _boom(*a, **k):
        raise AssertionError("find_email should not be called when source_domain is missing")

    monkeypatch.setattr(enrich, "find_email", _boom)

    stats = enrich.enrich_queued(client=client)

    assert stats == {"resolved": 0, "no_email": 1, "held_collision": 0}
    assert rows[0]["status"] == "queued" and rows[0]["contact"] is None


def test_enrich_find_email_none_counts_no_email(monkeypatch):
    rows = [
        {"id": "a", "status": "queued", "contact": None, "source_domain": "az.org", "personalization": {"state": "AZ"}}
    ]
    client = _Client(_Table(rows))
    monkeypatch.setattr(enrich, "find_email", lambda domain, full_name=None: (None, 0.0))

    stats = enrich.enrich_queued(client=client)

    assert stats == {"resolved": 0, "no_email": 1, "held_collision": 0}
    assert rows[0]["status"] == "queued" and rows[0]["contact"] is None


# --- find_email response parsing (monkeypatch the HTTP call, no network) ---


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_find_email_domain_search_picks_best_generic(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    payload = {
        "data": {
            "emails": [
                {"value": "info@az.org", "type": "generic", "confidence": 70},
                {"value": "contact@az.org", "type": "generic", "confidence": 90},
            ]
        }
    }
    monkeypatch.setattr(enrich, "retry_session_get", lambda *a, **k: _FakeResp(payload))
    assert enrich.find_email("az.org") == ("contact@az.org", 90.0)


def test_find_email_name_branch_uses_email_finder(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    payload = {"data": {"email": "jane@az.org", "score": 88}}
    monkeypatch.setattr(enrich, "retry_session_get", lambda *a, **k: _FakeResp(payload))
    assert enrich.find_email("az.org", full_name="Jane Doe") == ("jane@az.org", 88.0)


def test_find_email_score_zero_is_kept(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    payload = {"data": {"email": "info@az.org", "score": 0}}
    monkeypatch.setattr(enrich, "retry_session_get", lambda *a, **k: _FakeResp(payload))
    assert enrich.find_email("az.org", full_name="Jane Doe") == ("info@az.org", 0.0)


def test_find_email_empty_data_returns_none(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    monkeypatch.setattr(enrich, "retry_session_get", lambda *a, **k: _FakeResp({"data": {}}))
    assert enrich.find_email("az.org") == (None, 0.0)
