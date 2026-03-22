"""Tests for the performance profiling toolkit."""

import time
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.profiling.cpu_profiler import CpuProfiler, profile_cpu
from src.profiling.memory_profiler import MemoryProfiler, profile_memory
from src.profiling.timer import timer, Timer, TimingReport
from src.profiling.db_profiler import QueryProfiler, detect_n_plus_one, QueryRecord
from src.profiling.reporter import ProfileReport, generate_report


# ─── Timer Tests ──────────────────────────────────────────────────────


class TestTimer:
    def test_basic_timing(self):
        t = Timer("test")
        t.start()
        time.sleep(0.05)
        t.stop()
        assert t.elapsed >= 0.04
        assert t.elapsed < 0.5

    def test_format_microseconds(self):
        t = Timer()
        t._start = 0
        t._end = 0.0005
        assert "µs" in t.format_elapsed()

    def test_format_milliseconds(self):
        t = Timer()
        t._start = 0
        t._end = 0.05
        assert "ms" in t.format_elapsed()

    def test_format_seconds(self):
        t = Timer()
        t._start = 0
        t._end = 5.5
        assert "s" in t.format_elapsed()

    def test_format_minutes(self):
        t = Timer()
        t._start = 0
        t._end = 125.0
        assert "m" in t.format_elapsed()

    def test_context_manager(self):
        with timer("test_section") as t:
            time.sleep(0.01)
        assert t.elapsed >= 0.01


class TestTimingReport:
    def test_sections(self):
        report = TimingReport("Test")
        with report.section("step1"):
            time.sleep(0.01)
        with report.section("step2"):
            time.sleep(0.02)

        assert len(report.entries) == 2
        assert report.entries[0].name == "step1"
        assert report.entries[1].name == "step2"

    def test_print_summary(self):
        report = TimingReport("Test Pipeline")
        with report.section("fast"):
            pass
        with report.section("slow"):
            time.sleep(0.01)

        output = report.print_summary()
        assert "Test Pipeline" in output
        assert "fast" in output
        assert "slow" in output
        assert "TOTAL" in output

    def test_to_dict(self):
        report = TimingReport("Test")
        with report.section("step1", extra="info"):
            pass

        d = report.to_dict()
        assert d["name"] == "Test"
        assert len(d["sections"]) == 1
        assert d["sections"][0]["name"] == "step1"
        assert d["sections"][0]["extra"] == "info"
        assert "total_seconds" in d

    def test_empty_report(self):
        report = TimingReport("Empty")
        output = report.print_summary()
        assert "No sections" in output


# ─── CPU Profiler Tests ──────────────────────────────────────────────


class TestCpuProfiler:
    def test_basic_profiling(self, tmp_path):
        with CpuProfiler("test", output_dir=tmp_path) as prof:
            total = sum(range(10000))
        assert prof.elapsed > 0
        assert (tmp_path / "test.prof").exists()

    def test_print_stats(self, tmp_path):
        with CpuProfiler("test", output_dir=tmp_path) as prof:
            sum(range(10000))
        output = prof.print_stats(top=5)
        assert "function calls" in output or "test" in output.lower() or len(output) > 0

    def test_get_top_functions(self, tmp_path):
        with CpuProfiler("test", output_dir=tmp_path) as prof:
            sum(range(10000))
        top = prof.get_top_functions(5)
        assert len(top) > 0
        assert "function" in top[0]
        assert "cumulative_time" in top[0]

    def test_disabled(self, tmp_path):
        with CpuProfiler("test", output_dir=tmp_path, enabled=False) as prof:
            pass
        assert not (tmp_path / "test.prof").exists()
        assert prof.elapsed >= 0

    def test_decorator(self):
        @profile_cpu(enabled=False)
        def my_func():
            return sum(range(1000))

        result = my_func()
        assert result == 499500

    def test_decorator_no_parens(self):
        @profile_cpu
        def my_func():
            return 42

        # This will actually profile (enabled=True by default)
        # We just verify it doesn't crash
        result = my_func()
        assert result == 42

    def test_flamegraph_path(self, tmp_path):
        with CpuProfiler("test", output_dir=tmp_path) as prof:
            pass
        path = prof.generate_flamegraph_input()
        assert path is not None
        assert path.exists()


# ─── Memory Profiler Tests ───────────────────────────────────────────


class TestMemoryProfiler:
    def test_basic_profiling(self):
        with MemoryProfiler("test", detect_leaks=False) as mp:
            data = [i ** 2 for i in range(10000)]
        report = mp.report
        assert report is not None
        assert report.name == "test"
        assert report.elapsed > 0
        assert report.start.rss_mb >= 0

    def test_summary_output(self):
        with MemoryProfiler("test", detect_leaks=False) as mp:
            pass
        output = mp.print_report()
        assert "Memory Profile" in output
        assert "RSS" in output

    def test_disabled(self):
        with MemoryProfiler("test", enabled=False) as mp:
            pass
        assert mp.report is None

    def test_decorator(self):
        @profile_memory(enabled=False)
        def my_func():
            return list(range(100))

        result = my_func()
        assert len(result) == 100


# ─── DB Profiler Tests ───────────────────────────────────────────────


class TestQueryProfiler:
    def test_record_query(self):
        profiler = QueryProfiler()
        profiler.record(
            table="games",
            operation="select",
            elapsed_ms=150.0,
            row_count=1000,
        )
        assert len(profiler.queries) == 1
        assert profiler.queries[0].table == "games"

    def test_slow_query_detection(self):
        profiler = QueryProfiler(slow_threshold_ms=100)
        profiler.record(table="games", operation="select", elapsed_ms=50)
        profiler.record(table="teams", operation="select", elapsed_ms=200)
        profiler.record(table="rankings", operation="select", elapsed_ms=500)

        slow = profiler.get_slow_queries()
        assert len(slow) == 2
        assert slow[0].table == "teams"

    def test_n_plus_one_detection(self):
        profiler = QueryProfiler()
        base_time = time.time()

        # Simulate N+1: 10 individual team lookups in rapid succession
        for i in range(10):
            record = QueryRecord(
                table="teams",
                operation="select",
                elapsed_ms=5.0,
                row_count=1,
                timestamp=base_time + i * 0.01,  # 10ms apart
                filters=f"id={i}",
            )
            profiler.queries.append(record)

        patterns = profiler.detect_n_plus_one()
        assert len(patterns) > 0
        assert patterns[0]["table"] == "teams"
        assert patterns[0]["count"] >= 5

    def test_no_false_positive_n_plus_one(self):
        profiler = QueryProfiler()
        base_time = time.time()

        # Queries spread over a long time — not N+1
        for i in range(5):
            record = QueryRecord(
                table="teams",
                operation="select",
                elapsed_ms=5.0,
                row_count=1,
                timestamp=base_time + i * 10,  # 10 seconds apart
            )
            profiler.queries.append(record)

        patterns = profiler.detect_n_plus_one()
        assert len(patterns) == 0

    def test_report_generation(self):
        profiler = QueryProfiler()
        profiler.record(table="games", operation="select", elapsed_ms=100, row_count=500)
        profiler.record(table="teams", operation="select", elapsed_ms=50, row_count=100)

        report = profiler.get_report()
        assert report.total_queries == 2
        assert report.total_time_ms == 150.0
        assert report.queries_by_table["games"] == 1

    def test_print_report(self):
        profiler = QueryProfiler()
        profiler.record(table="games", operation="select", elapsed_ms=600, row_count=1000)

        output = profiler.print_report()
        assert "Database Query Profile" in output
        assert "games" in output

    def test_reset(self):
        profiler = QueryProfiler()
        profiler.record(table="games", operation="select", elapsed_ms=100)
        profiler.reset()
        assert len(profiler.queries) == 0

    def test_wrap_client(self):
        """Test wrapping a mock Supabase client."""
        mock_result = MagicMock()
        mock_result.data = [{"id": 1}, {"id": 2}]

        mock_builder = MagicMock()
        mock_builder.select.return_value = mock_builder
        mock_builder.eq.return_value = mock_builder
        mock_builder.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_builder

        profiler = QueryProfiler()
        tracked = profiler.wrap(mock_client)

        result = tracked.table("games").select("*").eq("id", "123").execute()
        assert result.data == [{"id": 1}, {"id": 2}]
        assert len(profiler.queries) == 1
        assert profiler.queries[0].table == "games"
        assert profiler.queries[0].operation == "select"


# ─── Profile Report Tests ────────────────────────────────────────────


class TestProfileReport:
    def test_basic_report(self, tmp_path):
        report = ProfileReport("Test Report")
        report.add_custom("teams", 100)
        report.add_custom("games", 5000)

        d = report.to_dict()
        assert d["name"] == "Test Report"
        assert d["custom_metrics"]["teams"] == 100

    def test_save_json(self, tmp_path):
        report = ProfileReport("Test Report")
        report.add_custom("key", "value")

        path = report.save(str(tmp_path / "test_report.json"))
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["name"] == "Test Report"
        assert data["custom_metrics"]["key"] == "value"

    def test_full_report_integration(self, tmp_path):
        """Integration test: combine all profilers into one report."""
        timing = TimingReport("Test Pipeline")
        with timing.section("step1"):
            time.sleep(0.01)

        cpu = CpuProfiler("test", output_dir=tmp_path, enabled=True)
        with cpu:
            sum(range(10000))

        memory = MemoryProfiler("test", detect_leaks=False, enabled=True)
        with memory:
            data = list(range(1000))

        db = QueryProfiler()
        db.record(table="games", operation="select", elapsed_ms=200, row_count=1000)

        report = generate_report(
            "Full Integration Test",
            timing=timing,
            cpu=cpu,
            memory=memory,
            db=db,
            game_count=5000,
            team_count=500,
        )

        d = report.to_dict()
        assert "timing" in d
        assert "cpu" in d
        assert "memory" in d
        assert "database" in d
        assert d["custom_metrics"]["game_count"] == 5000

        # Save and verify
        path = report.save(str(tmp_path / "full_report.json"))
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["database"]["total_queries"] == 1

    def test_print_summary(self):
        report = ProfileReport("Test")
        timing = TimingReport("Test")
        with timing.section("step"):
            pass
        report.add_timing(timing)

        output = report.print_summary()
        assert "PERFORMANCE PROFILE" in output


# ─── Standalone N+1 Detection ────────────────────────────────────────


class TestDetectNPlusOne:
    def test_standalone_detection(self):
        base_time = time.time()
        queries = [
            QueryRecord(
                table="teams",
                operation="select",
                elapsed_ms=5,
                row_count=1,
                timestamp=base_time + i * 0.01,
            )
            for i in range(10)
        ]
        result = detect_n_plus_one(queries)
        assert len(result) > 0

    def test_empty_list(self):
        result = detect_n_plus_one([])
        assert result == []
