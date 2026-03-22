"""PitchRank Performance Profiling Toolkit.

Provides CPU, memory, I/O, and database profiling for the ranking engine,
scrapers, and API endpoints. Always measure before and after.

Usage:
    from src.profiling import profile_cpu, profile_memory, timer

    @profile_cpu
    def my_function():
        ...

    @profile_memory
    def my_function():
        ...

    with timer("ranking calculation"):
        compute_rankings(...)
"""

from src.profiling.cpu_profiler import profile_cpu, CpuProfiler
from src.profiling.memory_profiler import profile_memory, MemoryProfiler
from src.profiling.timer import timer, Timer, TimingReport
from src.profiling.db_profiler import QueryProfiler, detect_n_plus_one
from src.profiling.reporter import ProfileReport, generate_report

__all__ = [
    "profile_cpu",
    "CpuProfiler",
    "profile_memory",
    "MemoryProfiler",
    "timer",
    "Timer",
    "TimingReport",
    "QueryProfiler",
    "detect_n_plus_one",
    "ProfileReport",
    "generate_report",
]
