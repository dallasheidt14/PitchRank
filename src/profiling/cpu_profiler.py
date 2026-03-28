"""CPU profiling with cProfile and optional flamegraph generation.

Supports both decorator and context manager usage:

    @profile_cpu(output="profiles/ranking.prof")
    def calculate():
        ...

    with CpuProfiler("ranking") as prof:
        compute_rankings(...)
    prof.print_stats(top=20)
"""

from __future__ import annotations

import cProfile
import functools
import io
import logging
import pstats
import time
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

PROFILES_DIR = Path("data/profiles")


class CpuProfiler:
    """Context manager for CPU profiling with cProfile."""

    def __init__(
        self,
        name: str = "profile",
        output_dir: Optional[Path] = None,
        sort_by: str = "cumulative",
        enabled: bool = True,
    ):
        self.name = name
        self.output_dir = output_dir or PROFILES_DIR
        self.sort_by = sort_by
        self.enabled = enabled
        self._profiler: Optional[cProfile.Profile] = None
        self._stats: Optional[pstats.Stats] = None
        self._start_time: float = 0
        self._elapsed: float = 0

    def __enter__(self) -> "CpuProfiler":
        if not self.enabled:
            self._start_time = time.perf_counter()
            return self

        self._profiler = cProfile.Profile()
        self._profiler.enable()
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._elapsed = time.perf_counter() - self._start_time

        if not self.enabled or self._profiler is None:
            return

        self._profiler.disable()

        # Save raw profile data
        self.output_dir.mkdir(parents=True, exist_ok=True)
        prof_path = self.output_dir / f"{self.name}.prof"
        self._profiler.dump_stats(str(prof_path))
        logger.info(f"CPU profile saved: {prof_path} ({self._elapsed:.2f}s)")

        # Build stats object
        self._stats = pstats.Stats(self._profiler)
        self._stats.sort_stats(self.sort_by)

    @property
    def elapsed(self) -> float:
        return self._elapsed

    def print_stats(self, top: int = 30) -> str:
        """Print top N functions by cumulative time. Returns the output string."""
        if self._stats is None:
            return f"[{self.name}] No profile data (elapsed: {self._elapsed:.2f}s)"

        stream = io.StringIO()
        self._stats.stream = stream
        self._stats.print_stats(top)
        output = stream.getvalue()
        logger.info(f"\n--- CPU Profile: {self.name} (top {top}) ---\n{output}")
        return output

    def get_top_functions(self, top: int = 20) -> list[dict]:
        """Return top functions as structured data."""
        if self._stats is None:
            return []

        results = []
        # pstats stores: (primitive_calls, total_calls, total_time, cumulative_time, callers)
        for func_key, (cc, nc, tt, ct, callers) in sorted(
            self._stats.stats.items(),
            key=lambda x: x[1][3],  # sort by cumulative time
            reverse=True,
        )[:top]:
            filename, lineno, funcname = func_key
            results.append(
                {
                    "function": funcname,
                    "file": filename,
                    "line": lineno,
                    "calls": nc,
                    "total_time": round(tt, 4),
                    "cumulative_time": round(ct, 4),
                    "time_per_call": round(tt / nc, 6) if nc > 0 else 0,
                }
            )
        return results

    def generate_flamegraph_input(self) -> Optional[Path]:
        """Generate collapsed stack format for flamegraph.pl or speedscope.

        Requires the profile to have been saved. Use with:
            python -m flameprof data/profiles/<name>.prof > flamegraph.svg
        or upload the .prof to https://www.speedscope.app/
        """
        prof_path = self.output_dir / f"{self.name}.prof"
        if not prof_path.exists():
            return None
        logger.info(
            f"Flamegraph: upload {prof_path} to https://www.speedscope.app/ "
            f"or run: python -m flameprof {prof_path} > {self.name}_flamegraph.svg"
        )
        return prof_path


def profile_cpu(
    func: Optional[Callable] = None,
    *,
    output: Optional[str] = None,
    sort_by: str = "cumulative",
    top: int = 20,
    enabled: bool = True,
):
    """Decorator to profile a function's CPU usage.

    Args:
        func: The function to profile (auto-filled when used without parens).
        output: Output filename (default: function name).
        sort_by: Sort stats by this key.
        top: Print top N functions.
        enabled: Toggle profiling on/off without removing decorator.

    Usage:
        @profile_cpu
        def my_func(): ...

        @profile_cpu(top=50, sort_by="tottime")
        def my_func(): ...
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            name = output or fn.__qualname__.replace(".", "_").replace("<", "").replace(">", "")
            with CpuProfiler(name=name, sort_by=sort_by, enabled=enabled) as prof:
                result = fn(*args, **kwargs)
            if enabled:
                prof.print_stats(top=top)
            return result

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            name = output or fn.__qualname__.replace(".", "_").replace("<", "").replace(">", "")
            with CpuProfiler(name=name, sort_by=sort_by, enabled=enabled) as prof:
                result = await fn(*args, **kwargs)
            if enabled:
                prof.print_stats(top=top)
            return result

        import asyncio

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
