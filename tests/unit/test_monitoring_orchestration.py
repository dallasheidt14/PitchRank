"""Preview is outcome blind and coverage pagination preserves every denominator."""

from types import SimpleNamespace

from src.predictions.sos_monitoring import collect_review, coverage_rows


class Query:
    def __init__(self, client, name, rows):
        self.client, self.name, self.rows = client, name, rows
        self.start, self.end = 0, 999

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        self.client.calls.append((self.name, self.start, self.end))
        return SimpleNamespace(data=self.rows[self.start : self.end + 1])


def test_coverage_pages_more_than_1000_provider_cohort_dates():
    class Client:
        calls = []

        def rpc(self, name, parameters):
            assert name == "compare_monitor_coverage"
            assert parameters == {"p_signature": "a" * 64}
            return Query(self, name, [{"stratum": i, "missing": 1} for i in range(1001)])

    client = Client()
    rows = coverage_rows(client, "a" * 64)
    assert len(rows) == 1001
    assert sum(row["missing"] for row in rows) == 1001
    assert client.calls == [("compare_monitor_coverage", 0, 999), ("compare_monitor_coverage", 1000, 1999)]


def test_preview_requests_metadata_without_reading_outcomes_or_auditing_results():
    class Client:
        calls = []

        def rpc(self, name, parameters):
            assert name == "compare_monitor_review"
            assert parameters["p_preview"] is True
            return Query(
                self,
                name,
                [{"game_date": "2030-01-01", "provider": "test", "open": True, "fixture": None, "payload": None}],
            )

        def table(self, name):
            raise AssertionError("Preview queried source results")

    records, coverage, _ = collect_review(Client(), "a" * 64, dry_run=True)
    assert records == []
    assert coverage["counts"]["reviewable"] == 1
