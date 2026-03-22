"""Memory profiling: heap tracking, leak detection, and GC analysis.

Usage:
    @profile_memory
    def process_data():
        ...

    with MemoryProfiler("ranking") as mp:
        compute_rankings(...)
    mp.print_report()
"""

from __future__ import annotations

import functools
import gc
import logging
import os
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

PROFILES_DIR = Path("data/profiles")


@dataclass
class MemorySnapshot:
    """Point-in-time memory measurement."""

    timestamp: float
    label: str
    rss_mb: float  # Resident Set Size
    tracemalloc_mb: float  # tracemalloc current
    tracemalloc_peak_mb: float  # tracemalloc peak
    gc_objects: int  # Objects tracked by GC


@dataclass
class MemoryReport:
    """Summary of memory usage across a profiled section."""

    name: str
    start: MemorySnapshot
    end: MemorySnapshot
    peak_tracemalloc_mb: float
    top_allocations: list[dict] = field(default_factory=list)
    leaked_objects: list[dict] = field(default_factory=list)

    @property
    def rss_delta_mb(self) -> float:
        return self.end.rss_mb - self.start.rss_mb

    @property
    def elapsed(self) -> float:
        return self.end.timestamp - self.start.timestamp

    def summary(self) -> str:
        lines = [
            f"=== Memory Profile: {self.name} ===",
            f"Duration:        {self.elapsed:.2f}s",
            f"RSS start:       {self.start.rss_mb:.1f} MB",
            f"RSS end:         {self.end.rss_mb:.1f} MB",
            f"RSS delta:       {self.rss_delta_mb:+.1f} MB",
            f"Peak (traced):   {self.peak_tracemalloc_mb:.1f} MB",
            f"GC objects:      {self.start.gc_objects:,} -> {self.end.gc_objects:,} "
            f"({self.end.gc_objects - self.start.gc_objects:+,})",
        ]
        if self.top_allocations:
            lines.append(f"\nTop {len(self.top_allocations)} allocations:")
            for alloc in self.top_allocations:
                lines.append(
                    f"  {alloc['size_mb']:.2f} MB  {alloc['file']}:{alloc['line']}  "
                    f"({alloc['count']} blocks)"
                )
        if self.leaked_objects:
            lines.append(f"\nPotential leaks ({len(self.leaked_objects)} types with growth):")
            for leak in self.leaked_objects[:10]:
                lines.append(f"  +{leak['delta']:,} {leak['type']}  (now: {leak['count']:,})")
        return "\n".join(lines)


def _get_rss_mb() -> float:
    """Get current RSS in MB (cross-platform)."""
    try:
        # Linux: read from /proc
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (FileNotFoundError, PermissionError):
        pass

    # Fallback: use resource module
    try:
        import resource
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        # macOS returns bytes, Linux returns KB
        if sys.platform == "darwin":
            return rusage.ru_maxrss / (1024 * 1024)
        return rusage.ru_maxrss / 1024.0
    except ImportError:
        return 0.0


def _take_snapshot(label: str) -> MemorySnapshot:
    """Take a memory snapshot."""
    current, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (0, 0)
    return MemorySnapshot(
        timestamp=time.perf_counter(),
        label=label,
        rss_mb=_get_rss_mb(),
        tracemalloc_mb=current / (1024 * 1024),
        tracemalloc_peak_mb=peak / (1024 * 1024),
        gc_objects=len(gc.get_objects()),
    )


def _get_type_counts() -> dict[str, int]:
    """Count objects by type for leak detection."""
    counts: dict[str, int] = {}
    for obj in gc.get_objects():
        type_name = type(obj).__name__
        counts[type_name] = counts.get(type_name, 0) + 1
    return counts


class MemoryProfiler:
    """Context manager for memory profiling."""

    def __init__(
        self,
        name: str = "memory",
        top_allocations: int = 15,
        detect_leaks: bool = True,
        enabled: bool = True,
    ):
        self.name = name
        self.top_allocations = top_allocations
        self.detect_leaks = detect_leaks
        self.enabled = enabled
        self._report: Optional[MemoryReport] = None
        self._type_counts_before: dict[str, int] = {}
        self._tracemalloc_was_tracing = False

    def __enter__(self) -> "MemoryProfiler":
        if not self.enabled:
            return self

        # Start tracemalloc if not already running
        self._tracemalloc_was_tracing = tracemalloc.is_tracing()
        if not self._tracemalloc_was_tracing:
            tracemalloc.start(25)  # 25 frames deep

        gc.collect()

        if self.detect_leaks:
            self._type_counts_before = _get_type_counts()

        self._start = _take_snapshot("start")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if not self.enabled:
            return

        gc.collect()
        end = _take_snapshot("end")

        # Get top allocations
        top_allocs = []
        if tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            stats = snapshot.statistics("lineno")
            for stat in stats[: self.top_allocations]:
                frame = stat.traceback[0]
                top_allocs.append({
                    "file": frame.filename,
                    "line": frame.lineno,
                    "size_mb": stat.size / (1024 * 1024),
                    "count": stat.count,
                })

        # Detect potential leaks
        leaked = []
        if self.detect_leaks:
            after_counts = _get_type_counts()
            for type_name, count in after_counts.items():
                before = self._type_counts_before.get(type_name, 0)
                delta = count - before
                if delta > 100:  # Only flag significant growth
                    leaked.append({
                        "type": type_name,
                        "count": count,
                        "delta": delta,
                    })
            leaked.sort(key=lambda x: x["delta"], reverse=True)

        _, peak = tracemalloc.get_traced_memory()

        self._report = MemoryReport(
            name=self.name,
            start=self._start,
            end=end,
            peak_tracemalloc_mb=peak / (1024 * 1024),
            top_allocations=top_allocs,
            leaked_objects=leaked,
        )

        # Stop tracemalloc if we started it
        if not self._tracemalloc_was_tracing:
            tracemalloc.stop()

        # Save report
        output_dir = PROFILES_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"{self.name}_memory.txt"
        report_path.write_text(self._report.summary())
        logger.info(f"Memory profile saved: {report_path}")

    @property
    def report(self) -> Optional[MemoryReport]:
        return self._report

    def print_report(self) -> str:
        """Print and return the memory report."""
        if self._report is None:
            return "[No memory data collected]"
        output = self._report.summary()
        logger.info(f"\n{output}")
        return output


def profile_memory(
    func: Optional[Callable] = None,
    *,
    top: int = 15,
    detect_leaks: bool = True,
    enabled: bool = True,
):
    """Decorator to profile a function's memory usage.

    Usage:
        @profile_memory
        def process_data(): ...

        @profile_memory(top=20, detect_leaks=True)
        def process_data(): ...
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with MemoryProfiler(
                name=fn.__qualname__,
                top_allocations=top,
                detect_leaks=detect_leaks,
                enabled=enabled,
            ) as mp:
                result = fn(*args, **kwargs)
            if enabled:
                mp.print_report()
            return result

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            with MemoryProfiler(
                name=fn.__qualname__,
                top_allocations=top,
                detect_leaks=detect_leaks,
                enabled=enabled,
            ) as mp:
                result = await fn(*args, **kwargs)
            if enabled:
                mp.print_report()
            return result

        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
