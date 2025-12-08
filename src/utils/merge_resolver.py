"""
Team merge resolution utilities.

This module provides the MergeResolver class for resolving deprecated team IDs
to their canonical form. Used in ranking calculations to ensure merged teams
are properly consolidated.

Part of Phase 2 of the team merge implementation (Option 1 architecture).
"""

import hashlib
import logging
from typing import Dict, Optional, Set, List

import pandas as pd

logger = logging.getLogger(__name__)


class MergeResolver:
    """
    Resolves deprecated team IDs to canonical team IDs.

    This class loads the team_merge_map from the database and provides
    efficient lookups for resolving team IDs. It also provides a version
    hash for cache invalidation when merges change.

    Usage:
        resolver = MergeResolver(supabase_client)
        resolver.load_merge_map()

        # Resolve single ID
        canonical_id = resolver.resolve(team_id)

        # Resolve DataFrame columns
        df = resolver.resolve_dataframe(df, ['home_team_master_id', 'away_team_master_id'])

        # Include version in cache key
        cache_key = f"rankings_{resolver.version}"
    """

    def __init__(self, supabase_client):
        """
        Initialize the MergeResolver.

        Args:
            supabase_client: Supabase client instance
        """
        self.client = supabase_client
        self._merge_map: Dict[str, str] = {}
        self._version: Optional[str] = None
        self._loaded: bool = False

    def load_merge_map(self) -> None:
        """
        Load current merge mappings from database.

        Fetches all entries from team_merge_map and builds an in-memory
        lookup dictionary. Also computes a version hash for cache invalidation.
        """
        try:
            response = self.client.table('team_merge_map').select(
                'deprecated_team_id, canonical_team_id'
            ).execute()

            self._merge_map = {
                str(row['deprecated_team_id']): str(row['canonical_team_id'])
                for row in response.data
            }

            # Compute version hash for cache invalidation
            if self._merge_map:
                map_str = ''.join(sorted(f"{k}:{v}" for k, v in self._merge_map.items()))
                self._version = hashlib.md5(map_str.encode()).hexdigest()[:8]
            else:
                self._version = "no_merges"

            self._loaded = True

            if self._merge_map:
                logger.info(f"Loaded {len(self._merge_map)} team merges (version: {self._version})")
            else:
                logger.debug("No team merges found")

        except Exception as e:
            logger.error(f"Failed to load merge map: {e}")
            self._merge_map = {}
            self._version = "error"
            self._loaded = True

    def resolve(self, team_id: Optional[str]) -> Optional[str]:
        """
        Resolve a single team ID to its canonical form.

        Args:
            team_id: The team ID to resolve (can be None)

        Returns:
            The canonical team ID, or the original ID if not merged,
            or None if input was None
        """
        if team_id is None:
            return None

        if not self._loaded:
            self.load_merge_map()

        team_id_str = str(team_id)
        return self._merge_map.get(team_id_str, team_id_str)

    def resolve_series(self, series: pd.Series) -> pd.Series:
        """
        Resolve a pandas Series of team IDs.

        Args:
            series: Pandas Series containing team IDs

        Returns:
            Series with deprecated IDs replaced by canonical IDs
        """
        if not self._loaded:
            self.load_merge_map()

        if not self._merge_map:
            return series

        return series.astype(str).map(lambda x: self._merge_map.get(x, x) if pd.notna(x) and x != 'nan' else x)

    def resolve_dataframe(self, df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """
        Resolve multiple team ID columns in a DataFrame.

        Args:
            df: DataFrame to process
            columns: List of column names containing team IDs

        Returns:
            DataFrame with deprecated IDs replaced by canonical IDs
        """
        if not self._loaded:
            self.load_merge_map()

        if not self._merge_map:
            return df

        df = df.copy()
        resolved_count = 0

        for col in columns:
            if col in df.columns:
                original = df[col].copy()
                df[col] = self.resolve_series(df[col])
                resolved_count += (original != df[col]).sum()

        if resolved_count > 0:
            logger.info(f"Resolved {resolved_count} team ID references across {len(columns)} columns")

        return df

    @property
    def version(self) -> str:
        """
        Get version hash for cache key inclusion.

        The version changes whenever the merge map changes, allowing
        caches to be invalidated when merges are added/removed.

        Returns:
            8-character hash string representing current merge state
        """
        if not self._loaded:
            self.load_merge_map()
        return self._version or "unknown"

    @property
    def has_merges(self) -> bool:
        """
        Check if any merges exist.

        Returns:
            True if there are any team merges in the map
        """
        if not self._loaded:
            self.load_merge_map()
        return len(self._merge_map) > 0

    @property
    def merge_count(self) -> int:
        """
        Get the number of merged teams.

        Returns:
            Count of deprecated teams that have been merged
        """
        if not self._loaded:
            self.load_merge_map()
        return len(self._merge_map)

    def get_deprecated_teams(self) -> Set[str]:
        """
        Get set of all deprecated team IDs.

        Returns:
            Set of team IDs that have been merged into other teams
        """
        if not self._loaded:
            self.load_merge_map()
        return set(self._merge_map.keys())

    def get_canonical_teams(self) -> Set[str]:
        """
        Get set of all canonical team IDs.

        Returns:
            Set of team IDs that other teams have been merged into
        """
        if not self._loaded:
            self.load_merge_map()
        return set(self._merge_map.values())

    def is_deprecated(self, team_id: str) -> bool:
        """
        Check if a team ID is deprecated (has been merged).

        Args:
            team_id: The team ID to check

        Returns:
            True if the team has been merged into another team
        """
        if not self._loaded:
            self.load_merge_map()
        return str(team_id) in self._merge_map

    def get_merge_info(self, team_id: str) -> Optional[Dict]:
        """
        Get merge information for a deprecated team.

        Args:
            team_id: The deprecated team ID

        Returns:
            Dict with canonical_team_id, or None if not merged
        """
        if not self._loaded:
            self.load_merge_map()

        team_id_str = str(team_id)
        if team_id_str in self._merge_map:
            return {
                'deprecated_team_id': team_id_str,
                'canonical_team_id': self._merge_map[team_id_str],
                'is_merged': True
            }
        return None

    def refresh(self) -> None:
        """
        Refresh the merge map from the database.

        Call this to reload merges if they may have changed during
        a long-running process.
        """
        self._loaded = False
        self.load_merge_map()

    def __repr__(self) -> str:
        return f"MergeResolver(merges={self.merge_count}, version={self.version})"
