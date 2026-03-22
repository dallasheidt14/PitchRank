"""Unified profile report: combines CPU, memory, timing, and DB profiling results.

Usage:
    report = ProfileReport("Ranking Pipeline v53e")
    report.add_timing(timing_report)
    report.add_cpu(cpu_profiler)
    report.add_memory(memory_profiler)
    report.add_db(query_profiler)
    report.save("data/profiles/ranking_report.json")
    report.print_summary()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.profiling.cpu_profiler import CpuProfiler
from src.profiling.memory_profiler import MemoryProfiler
from src.profiling.timer import TimingReport
from src.profiling.db_profiler import QueryProfiler

logger = logging.getLogger(__name__)

PROFILES_DIR = Path("data/profiles")


class ProfileReport:
    """Aggregates profiling data from all sources into a single report."""

    def __init__(self, name: str):
        self.name = name
        self.timestamp = datetime.now().isoformat()
        self._timing: Optional[TimingReport] = None
        self._cpu: Optional[CpuProfiler] = None
        self._memory: Optional[MemoryProfiler] = None
        self._db: Optional[QueryProfiler] = None
        self._custom: dict = {}

    def add_timing(self, timing: TimingReport) -> "ProfileReport":
        self._timing = timing
        return self

    def add_cpu(self, cpu: CpuProfiler) -> "ProfileReport":
        self._cpu = cpu
        return self

    def add_memory(self, memory: MemoryProfiler) -> "ProfileReport":
        self._memory = memory
        return self

    def add_db(self, db: QueryProfiler) -> "ProfileReport":
        self._db = db
        return self

    def add_custom(self, key: str, value) -> "ProfileReport":
        """Add custom metrics (e.g., team count, game count)."""
        self._custom[key] = value
        return self

    def to_dict(self) -> dict:
        """Export full report as dict."""
        data = {
            "name": self.name,
            "timestamp": self.timestamp,
            "custom_metrics": self._custom,
        }

        if self._timing:
            data["timing"] = self._timing.to_dict()

        if self._cpu:
            data["cpu"] = {
                "elapsed_seconds": round(self._cpu.elapsed, 4),
                "top_functions": self._cpu.get_top_functions(20),
            }

        if self._memory and self._memory.report:
            mem = self._memory.report
            data["memory"] = {
                "rss_start_mb": round(mem.start.rss_mb, 1),
                "rss_end_mb": round(mem.end.rss_mb, 1),
                "rss_delta_mb": round(mem.rss_delta_mb, 1),
                "peak_traced_mb": round(mem.peak_tracemalloc_mb, 1),
                "gc_objects_start": mem.start.gc_objects,
                "gc_objects_end": mem.end.gc_objects,
                "top_allocations": mem.top_allocations[:10],
                "potential_leaks": mem.leaked_objects[:10],
            }

        if self._db:
            db_report = self._db.get_report()
            data["database"] = {
                "total_queries": db_report.total_queries,
                "total_time_ms": round(db_report.total_time_ms, 1),
                "avg_time_ms": round(db_report.avg_time_ms, 1),
                "queries_by_table": db_report.queries_by_table,
                "slow_queries": [
                    {
                        "table": q.table,
                        "operation": q.operation,
                        "elapsed_ms": round(q.elapsed_ms, 1),
                        "row_count": q.row_count,
                        "filters": q.filters,
                    }
                    for q in db_report.slow_queries[:20]
                ],
                "n_plus_one_patterns": db_report.n_plus_one,
            }

        return data

    def save(self, path: Optional[str] = None) -> Path:
        """Save report to JSON file."""
        if path:
            output = Path(path)
        else:
            output = PROFILES_DIR / f"{self.name.replace(' ', '_').lower()}_profile.json"

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        logger.info(f"Profile report saved: {output}")
        return output

    def print_summary(self) -> str:
        """Print a consolidated summary of all profiling data."""
        lines = [
            f"\n{'=' * 70}",
            f" PERFORMANCE PROFILE: {self.name}",
            f" {self.timestamp}",
            f"{'=' * 70}",
        ]

        # Custom metrics
        if self._custom:
            lines.append("\n  Context:")
            for k, v in self._custom.items():
                lines.append(f"    {k}: {v}")

        # Timing
        if self._timing:
            lines.append(self._timing.print_summary())

        # CPU
        if self._cpu:
            lines.append(f"\n  CPU Profile: {self._cpu.elapsed:.2f}s total")
            top = self._cpu.get_top_functions(10)
            for fn in top:
                lines.append(
                    f"    {fn['cumulative_time']:>8.3f}s  {fn['function']:<40} "
                    f"({fn['calls']} calls, {fn['file']}:{fn['line']})"
                )

        # Memory
        if self._memory and self._memory.report:
            lines.append(f"\n{self._memory.report.summary()}")

        # Database
        if self._db:
            lines.append(self._db.print_report())

        lines.append(f"{'=' * 70}\n")
        output = "\n".join(lines)
        logger.info(output)
        return output


def generate_report(
    name: str,
    timing: Optional[TimingReport] = None,
    cpu: Optional[CpuProfiler] = None,
    memory: Optional[MemoryProfiler] = None,
    db: Optional[QueryProfiler] = None,
    **custom_metrics,
) -> ProfileReport:
    """Convenience function to generate a report from profiling components."""
    report = ProfileReport(name)
    if timing:
        report.add_timing(timing)
    if cpu:
        report.add_cpu(cpu)
    if memory:
        report.add_memory(memory)
    if db:
        report.add_db(db)
    for k, v in custom_metrics.items():
        report.add_custom(k, v)
    return report
