"""Shared leakage-safe time partitions for match-model evaluation."""

from __future__ import annotations

import pandas as pd


def event_aware_partition_groups(
    dataset_df: pd.DataFrame,
    *,
    event_max_span_days: int = 14,
) -> pd.Series:
    """Group rows into non-overlapping date blocks without splitting short events."""

    if dataset_df.empty:
        return pd.Series(index=dataset_df.index, dtype="object")
    if event_max_span_days < 0:
        raise ValueError("event_max_span_days must be non-negative")
    dates = pd.to_datetime(dataset_df["game_date"], errors="raise").dt.normalize()
    unique_game_dates = [pd.Timestamp(value) for value in sorted(dates.unique())]
    parent = {value: value for value in unique_game_dates}

    def find(value: pd.Timestamp) -> pd.Timestamp:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: pd.Timestamp, right: pd.Timestamp) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        earlier, later = sorted((left_root, right_root))
        parent[later] = earlier

    if "event_name" not in dataset_df.columns:
        return pd.Series(
            [f"date:{value.date().isoformat()}" for value in dates],
            index=dataset_df.index,
            dtype="object",
        )

    event_names = dataset_df["event_name"].fillna("").astype(str).str.strip()
    for event_name in sorted(name for name in event_names.unique() if name):
        event_mask = event_names.eq(event_name)
        event_dates = sorted(dates[event_mask].unique())
        clusters: list[list[pd.Timestamp]] = []
        for event_date in event_dates:
            normalized_date = pd.Timestamp(event_date)
            if (
                not clusters
                or (normalized_date - clusters[-1][-1]).days > event_max_span_days
            ):
                clusters.append([normalized_date])
            else:
                clusters[-1].append(normalized_date)
        for cluster in clusters:
            if (cluster[-1] - cluster[0]).days > event_max_span_days:
                continue
            for event_date in cluster[1:]:
                union(cluster[0], event_date)

    # When an event spans a date used by another competition, both intervals
    # must stay together or later evidence can leak into an earlier partition.
    intervals_by_root: dict[pd.Timestamp, list[pd.Timestamp]] = {}
    for game_date in unique_game_dates:
        intervals_by_root.setdefault(find(game_date), []).append(game_date)
    ordered_intervals = sorted(
        (
            (min(values), max(values), root)
            for root, values in intervals_by_root.items()
        ),
        key=lambda item: (item[0], item[1]),
    )
    active_root: pd.Timestamp | None = None
    active_end: pd.Timestamp | None = None
    for interval_start, interval_end, root in ordered_intervals:
        if (
            active_root is not None
            and active_end is not None
            and interval_start <= active_end
        ):
            union(active_root, root)
            active_root = find(active_root)
            active_end = max(active_end, interval_end)
        else:
            active_root = root
            active_end = interval_end
    return pd.Series(
        [f"date-block:{find(pd.Timestamp(value)).date().isoformat()}" for value in dates],
        index=dataset_df.index,
        dtype="object",
    )
