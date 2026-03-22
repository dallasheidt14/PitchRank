"""Lightweight timing utilities for measuring code sections.

Usage:
    with timer("ranking calculation"):
        compute_rankings(...)

    report = TimingReport()
    with report.section("fetch games"):
        fetch_games()
    with report.section("compute rankings"):
        compute()
    report.print_summary()
"""

from __future__ import annotations

import functools
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class TimingEntry:
    """Single timing measurement."""

    name: str
    elapsed: float
    start_time: float
    end_time: float
    metadata: dict = field(default_factory=dict)


@contextmanager
def timer(name: str, log_level: int = logging.INFO):
    """Context manager that logs elapsed time.

    Args:
        name: Description of the timed section.
        log_level: Logging level for the output.

    Yields:
        Timer object with .elapsed attribute (populated after block).
    """
    t = Timer(name)
    t.start()
    try:
        yield t
    finally:
        t.stop()
        logger.log(log_level, f"[timer] {name}: {t.format_elapsed()}")


class Timer:
    """Stopwatch-style timer."""

    def __init__(self, name: str = ""):
        self.name = name
        self._start: float = 0
        self._end: float = 0
        self._running = False

    def start(self) -> "Timer":
        self._start = time.perf_counter()
        self._running = True
        return self

    def stop(self) -> "Timer":
        self._end = time.perf_counter()
        self._running = False
        return self

    @property
    def elapsed(self) -> float:
        if self._running:
            return time.perf_counter() - self._start
        return self._end - self._start

    def format_elapsed(self) -> str:
        """Human-readable elapsed time."""
        s = self.elapsed
        if s < 0.001:
            return f"{s * 1_000_000:.0f}µs"
        if s < 1.0:
            return f"{s * 1000:.1f}ms"
        if s < 60:
            return f"{s:.2f}s"
        minutes = int(s // 60)
        seconds = s % 60
        return f"{minutes}m {seconds:.1f}s"


class TimingReport:
    """Collects timing data across multiple sections for comparison.

    Usage:
        report = TimingReport("Ranking Pipeline")
        with report.section("fetch games"):
            ...
        with report.section("v53e computation"):
            ...
        with report.section("ML Layer 13"):
            ...
        report.print_summary()
    """

    def __init__(self, name: str = "Profile"):
        self.name = name
        self.entries: list[TimingEntry] = []
        self._start_time = time.perf_counter()

    @contextmanager
    def section(self, name: str, **metadata):
        """Time a named section."""
        start = time.perf_counter()
        try:
            yield
        finally:
            end = time.perf_counter()
            self.entries.append(TimingEntry(
                name=name,
                elapsed=end - start,
                start_time=start,
                end_time=end,
                metadata=metadata,
            ))

    @property
    def total_elapsed(self) -> float:
        return time.perf_counter() - self._start_time

    def print_summary(self) -> str:
        """Print a formatted summary table of all sections."""
        if not self.entries:
            return f"[{self.name}] No sections recorded"

        total = sum(e.elapsed for e in self.entries)
        max_name_len = max(len(e.name) for e in self.entries)

        lines = [
            f"\n{'=' * 60}",
            f" {self.name} — Timing Report",
            f"{'=' * 60}",
        ]

        for entry in self.entries:
            pct = (entry.elapsed / total * 100) if total > 0 else 0
            bar_len = int(pct / 2)
            bar = "█" * bar_len + "░" * (50 - bar_len)
            elapsed_str = _format_time(entry.elapsed)
            lines.append(
                f"  {entry.name:<{max_name_len}}  {elapsed_str:>10}  "
                f"{pct:5.1f}%  {bar}"
            )

        lines.append(f"{'─' * 60}")
        lines.append(f"  {'TOTAL':<{max_name_len}}  {_format_time(total):>10}  100.0%")
        lines.append(f"{'=' * 60}\n")

        output = "\n".join(lines)
        logger.info(output)
        return output

    def to_dict(self) -> dict:
        """Export as dict for JSON serialization."""
        return {
            "name": self.name,
            "total_seconds": round(sum(e.elapsed for e in self.entries), 4),
            "sections": [
                {
                    "name": e.name,
                    "elapsed_seconds": round(e.elapsed, 4),
                    **e.metadata,
                }
                for e in self.entries
            ],
        }


def _format_time(seconds: float) -> str:
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f}µs"
    if seconds < 1.0:
        return f"{seconds * 1000:.1f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.1f}s"
