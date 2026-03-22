"""Database query profiling: slow query detection, N+1 detection, query counting.

Wraps Supabase client calls to track query patterns and identify bottlenecks.

Usage:
    profiler = QueryProfiler()

    # Wrap a supabase client
    tracked_client = profiler.wrap(supabase_client)

    # Use tracked_client normally...
    tracked_client.table('games').select('*').execute()

    # Check results
    profiler.print_report()
    n_plus_one = profiler.detect_n_plus_one()
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class QueryRecord:
    """Record of a single database query."""

    table: str
    operation: str  # select, insert, update, delete, rpc
    elapsed_ms: float
    row_count: int
    timestamp: float
    filters: str = ""  # Simplified filter description
    columns: str = "*"  # Selected columns


@dataclass
class QueryReport:
    """Analysis of recorded queries."""

    total_queries: int
    total_time_ms: float
    slow_queries: list[QueryRecord]
    n_plus_one: list[dict]
    queries_by_table: dict[str, int]
    avg_time_ms: float

    def summary(self) -> str:
        lines = [
            f"\n{'=' * 60}",
            " Database Query Profile",
            f"{'=' * 60}",
            f"  Total queries:    {self.total_queries}",
            f"  Total time:       {self.total_time_ms:.1f}ms",
            f"  Avg per query:    {self.avg_time_ms:.1f}ms",
        ]

        if self.queries_by_table:
            lines.append("\n  Queries by table:")
            for table, count in sorted(
                self.queries_by_table.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"    {table:<30} {count:>5} queries")

        if self.slow_queries:
            lines.append(f"\n  Slow queries (>{SLOW_THRESHOLD_MS}ms):")
            for q in self.slow_queries[:10]:
                lines.append(
                    f"    {q.elapsed_ms:>8.1f}ms  {q.operation:<8} {q.table} "
                    f"({q.row_count} rows) {q.filters}"
                )

        if self.n_plus_one:
            lines.append("\n  N+1 Query Patterns Detected:")
            for pattern in self.n_plus_one:
                lines.append(
                    f"    {pattern['table']}: {pattern['count']} similar queries "
                    f"in {pattern['window_ms']:.0f}ms — consider batch query"
                )

        lines.append(f"{'=' * 60}\n")
        return "\n".join(lines)


# Threshold for "slow" queries (ms)
SLOW_THRESHOLD_MS = 500

# Threshold for N+1 detection: N similar queries to same table within window
N_PLUS_ONE_THRESHOLD = 5
N_PLUS_ONE_WINDOW_MS = 2000


class QueryProfiler:
    """Tracks and analyzes database query patterns."""

    def __init__(self, slow_threshold_ms: float = SLOW_THRESHOLD_MS):
        self.slow_threshold_ms = slow_threshold_ms
        self.queries: list[QueryRecord] = []
        self._enabled = True

    def record(
        self,
        table: str,
        operation: str,
        elapsed_ms: float,
        row_count: int = 0,
        filters: str = "",
        columns: str = "*",
    ) -> None:
        """Manually record a query."""
        if not self._enabled:
            return
        self.queries.append(QueryRecord(
            table=table,
            operation=operation,
            elapsed_ms=elapsed_ms,
            row_count=row_count,
            timestamp=time.time(),
            filters=filters,
            columns=columns,
        ))

    def wrap(self, supabase_client):
        """Wrap a Supabase client to automatically track queries.

        Returns a proxy that records timing for .execute() calls.
        """
        return _TrackedClient(supabase_client, self)

    def detect_n_plus_one(self) -> list[dict]:
        """Detect N+1 query patterns: many similar queries to the same table in a short window."""
        if len(self.queries) < N_PLUS_ONE_THRESHOLD:
            return []

        patterns = []
        # Group by (table, operation)
        groups: dict[tuple[str, str], list[QueryRecord]] = defaultdict(list)
        for q in self.queries:
            groups[(q.table, q.operation)].append(q)

        for (table, op), group_queries in groups.items():
            if len(group_queries) < N_PLUS_ONE_THRESHOLD:
                continue

            # Check if queries happen within a tight window
            group_queries.sort(key=lambda q: q.timestamp)
            window_start = 0
            for i in range(len(group_queries)):
                # Slide window
                while (
                    group_queries[i].timestamp - group_queries[window_start].timestamp
                ) * 1000 > N_PLUS_ONE_WINDOW_MS:
                    window_start += 1

                count_in_window = i - window_start + 1
                if count_in_window >= N_PLUS_ONE_THRESHOLD:
                    window_ms = (
                        group_queries[i].timestamp - group_queries[window_start].timestamp
                    ) * 1000
                    patterns.append({
                        "table": table,
                        "operation": op,
                        "count": count_in_window,
                        "window_ms": window_ms,
                    })
                    break  # One detection per group is enough

        return patterns

    def get_slow_queries(self) -> list[QueryRecord]:
        """Return queries exceeding the slow threshold."""
        return [q for q in self.queries if q.elapsed_ms > self.slow_threshold_ms]

    def get_report(self) -> QueryReport:
        """Generate a full query report."""
        total_time = sum(q.elapsed_ms for q in self.queries)
        by_table: dict[str, int] = defaultdict(int)
        for q in self.queries:
            by_table[q.table] += 1

        return QueryReport(
            total_queries=len(self.queries),
            total_time_ms=total_time,
            slow_queries=self.get_slow_queries(),
            n_plus_one=self.detect_n_plus_one(),
            queries_by_table=dict(by_table),
            avg_time_ms=total_time / len(self.queries) if self.queries else 0,
        )

    def print_report(self) -> str:
        """Print and return the query report."""
        report = self.get_report()
        output = report.summary()
        logger.info(output)
        return output

    def reset(self) -> None:
        """Clear all recorded queries."""
        self.queries.clear()


class _TrackedClient:
    """Proxy around Supabase client that records query timing."""

    def __init__(self, client, profiler: QueryProfiler):
        self._client = client
        self._profiler = profiler

    def table(self, name: str):
        return _TrackedTable(self._client.table(name), name, self._profiler)

    def rpc(self, fn_name: str, params=None):
        return _TrackedRpc(self._client, fn_name, params, self._profiler)

    def __getattr__(self, name):
        return getattr(self._client, name)


class _TrackedTable:
    """Proxy around Supabase table builder that intercepts .execute()."""

    def __init__(self, table_builder, table_name: str, profiler: QueryProfiler):
        self._builder = table_builder
        self._table_name = table_name
        self._profiler = profiler
        self._operation = "select"
        self._filters: list[str] = []
        self._columns = "*"

    def select(self, columns: str = "*"):
        self._operation = "select"
        self._columns = columns
        self._builder = self._builder.select(columns)
        return self

    def insert(self, data):
        self._operation = "insert"
        self._builder = self._builder.insert(data)
        return self

    def update(self, data):
        self._operation = "update"
        self._builder = self._builder.update(data)
        return self

    def delete(self):
        self._operation = "delete"
        self._builder = self._builder.delete()
        return self

    def eq(self, column, value):
        self._filters.append(f"{column}=...")
        self._builder = self._builder.eq(column, value)
        return self

    def in_(self, column, values):
        self._filters.append(f"{column} IN ({len(values)} values)")
        self._builder = self._builder.in_(column, values)
        return self

    def range(self, start, end):
        self._filters.append(f"range({start},{end})")
        self._builder = self._builder.range(start, end)
        return self

    def execute(self):
        start = time.perf_counter()
        result = self._builder.execute()
        elapsed_ms = (time.perf_counter() - start) * 1000

        row_count = len(result.data) if hasattr(result, "data") and result.data else 0
        self._profiler.record(
            table=self._table_name,
            operation=self._operation,
            elapsed_ms=elapsed_ms,
            row_count=row_count,
            filters=", ".join(self._filters),
            columns=self._columns,
        )
        return result

    def __getattr__(self, name):
        # Pass through other builder methods (gte, lte, order, limit, etc.)
        attr = getattr(self._builder, name)
        if callable(attr):
            def proxy(*args, **kwargs):
                self._filters.append(f"{name}(...)")
                self._builder = attr(*args, **kwargs)
                return self
            return proxy
        return attr


class _TrackedRpc:
    """Proxy for RPC calls."""

    def __init__(self, client, fn_name: str, params, profiler: QueryProfiler):
        self._client = client
        self._fn_name = fn_name
        self._params = params
        self._profiler = profiler

    def execute(self):
        start = time.perf_counter()
        result = self._client.rpc(self._fn_name, self._params).execute()
        elapsed_ms = (time.perf_counter() - start) * 1000

        row_count = 0
        if hasattr(result, "data"):
            if isinstance(result.data, list):
                row_count = len(result.data)
            elif result.data is not None:
                row_count = 1

        self._profiler.record(
            table=f"rpc:{self._fn_name}",
            operation="rpc",
            elapsed_ms=elapsed_ms,
            row_count=row_count,
        )
        return result


def detect_n_plus_one(queries: list[QueryRecord]) -> list[dict]:
    """Standalone N+1 detection for a list of query records."""
    profiler = QueryProfiler()
    profiler.queries = queries
    return profiler.detect_n_plus_one()
