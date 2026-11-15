"""A frozen input export never reads target outcomes, even in execute mode."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import export_compare_formula_inputs as export
from src.predictions import private_research_output


class Client:
    def __init__(self, size=1001):
        self.calls = []
        self.payload_reads = []
        self.sealed_days = set()
        self.clock = "2026-11-14T00:00:00Z"
        self.rows = [
            {
                "baseline_forecast_id": f"{i:05}",
                "captured_at": "2026-11-13T12:00:00Z",
                "payload": {"context": {"frozenEvidence": {"as_of": "2026-11-13"}}},
                "payload_sha256": "hash",
                "prospective_match_predictions": {"game_date": "2026-11-15", "provider_code": "gotsport"},
            }
            for i in range(size)
        ]

    def rpc(self, name, args):
        assert name in ("compare_monitor_clock", "compare_monitor_results_open")
        return SimpleNamespace(
            execute=lambda: SimpleNamespace(
                data=self.clock
                if name == "compare_monitor_clock"
                else (args["p_day"] < self.clock[:10] and all(args["p_day"] < start for start in self.sealed_days))
            )
        )

    def table(self, table):
        assert table in ("compare_monitoring_models", "compare_monitoring_forecasts")
        parent = self

        class Query:
            def __init__(self):
                self.fields, self.start, self.end, self.cutoff, self.ordering = None, 0, 999, None, None
                self.ids = None

            def select(self, fields):
                self.fields = fields
                return self

            def eq(self, field, value):
                assert field in ("signature", "monitor_signature") and value == "signature"
                return self

            def single(self):
                return self

            def in_(self, field, values):
                assert field == "baseline_forecast_id"
                self.ids = values
                return self

            def lte(self, field, cutoff):
                assert field == "captured_at"
                self.cutoff = cutoff
                return self

            def order(self, field):
                self.ordering = field
                return self

            def range(self, start, end):
                self.start, self.end = start, end
                return self

            def execute(self):
                if table == "compare_monitoring_models":
                    return SimpleNamespace(
                        data={
                            "signature": "signature",
                            "manifest": {
                                "model_version": "heuristic_v8_continuous_transitions_v1",
                                "code_revision": "c061cfc042953d0e677ea5474cbb509758f14593",
                                "runtime_profile": {"calibration": {}},
                            },
                        }
                    )
                assert self.ordering == "baseline_forecast_id"
                assert self.cutoff == parent.clock if self.ids is None else self.cutoff is None
                parent.calls.append((self.start, self.fields))
                rows = deepcopy([r for r in parent.rows if self.ids is None or r["baseline_forecast_id"] in self.ids])
                rows = rows[self.start : self.end + 1]
                if "payload" in self.fields.split(","):
                    parent.payload_reads.extend(row["baseline_forecast_id"] for row in rows)
                else:
                    rows = [
                        {
                            key.split(":")[0]: row["payload"]["context"]["frozenEvidence"].get("as_of")
                            if key.startswith("history_as_of:")
                            else row[key]
                            for key in self.fields.split(",")
                        }
                        for row in rows
                    ]
                return SimpleNamespace(data=rows)

        return Query()


def test_preview_pages_by_unique_id_and_requests_no_payloads_or_scores(tmp_path):
    client = Client()
    result = export.run(client, "signature")
    assert result["captures"] == 1001 and result["output_written"] is False
    metadata = "baseline_forecast_id,captured_at,history_as_of:payload->context->frozenEvidence->>as_of"
    assert client.calls == [(0, metadata), (1000, metadata)]
    assert list(tmp_path.iterdir()) == []


def test_execute_freezes_only_forecast_inputs_and_target_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(private_research_output.subprocess, "run", lambda *args, **kwargs: None)
    output = tmp_path / "inputs.json"
    client = Client(1)
    result = export.run(client, "signature", execute=True, output=output)
    assert result["captures"] == 1 and len(result["sha256"]) == 64
    assert client.calls[0][1] == (
        "baseline_forecast_id,captured_at,history_as_of:payload->context->frozenEvidence->>as_of"
    )
    assert (
        client.calls[1][1] == "baseline_forecast_id,captured_at,payload,payload_sha256,"
        "prospective_match_predictions!inner(game_date,provider_code)"
    )
    data = json.loads(output.read_text())
    assert data["rows"][0]["game_date"] == "2026-11-15"
    assert data["rows"][0]["provider"] == "gotsport"
    with pytest.raises(ValueError, match="overwrite"):
        export.run(client, "signature", execute=True, output=output)


def test_rejects_write_configuration_in_preview(tmp_path):
    with pytest.raises(ValueError):
        export.run(Client(), "signature", output=tmp_path / "private.json")


@pytest.mark.parametrize("capture_day", ["2026-11-14", "2026-11-13"])
def test_withholds_histories_before_fetching_any_sealed_payload(monkeypatch, tmp_path, capture_day):
    monkeypatch.setattr(private_research_output.subprocess, "run", lambda *args, **kwargs: None)
    client = Client(2)
    client.clock = "2026-11-15T18:00:00Z"
    client.rows[1]["captured_at"] = f"{capture_day}T23:59:55Z"
    client.rows[1]["payload"] = {
        "context": {
            "frozenEvidence": {
                "as_of": "2026-11-14",
                "games": [],
                "omitted": [
                    {
                        "reason": "excluded_opponent",
                        "record": {
                            "game_date": "2026-11-14",
                            "goals_for": 3,
                            "goals_against": 1,
                            "protected_result": "must never be fetched",
                        },
                    }
                ],
            }
        }
    }
    client.sealed_days.add("2026-11-14")
    output = tmp_path / "safe.json"
    result = export.run(client, "signature", execute=True, output=output)
    assert result["found"] == 2 and result["captures"] == 1 and result["withheld_history_seals"] == 1
    data = json.loads(output.read_text())
    assert [row["baseline_forecast_id"] for row in data["rows"]] == ["00000"]
    assert data["withheld"][0]["baseline_forecast_id"] == "00001"
    assert "protected_result" not in output.read_text()
    assert client.payload_reads == ["00000"]


@pytest.mark.parametrize("history_bound", [None, "bad-date", "20261113", 123])
def test_withholds_unknown_history_bound_before_any_payload_read(monkeypatch, tmp_path, history_bound):
    monkeypatch.setattr(private_research_output.subprocess, "run", lambda *args, **kwargs: None)
    client = Client(1)
    client.rows[0]["payload"]["context"]["frozenEvidence"]["as_of"] = history_bound
    output = tmp_path / "unbounded.json"
    result = export.run(client, "signature", execute=True, output=output)
    assert result["captures"] == 0 and result["withheld_missing_history_bound"] == 1
    assert client.payload_reads == []
    data = json.loads(output.read_text())
    assert data["rows"] == []
    assert data["withheld_missing_history_bound"][0]["baseline_forecast_id"] == "00000"
