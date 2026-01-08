"""Utility functions and helpers"""

# Club normalizer (no external dependencies beyond standard library + optional rapidfuzz)
from .club_normalizer import (
    normalize_club_name,
    normalize_to_club,
    are_same_club,
    similarity_score,
    group_by_club,
    ClubNormResult,
)

# Conditional imports for pandas-dependent modules
try:
    from .merge_resolver import MergeResolver
    from .merge_suggester import MergeSuggester, MergeSuggestion, suggest_merges_for_cohort
    _HAVE_PANDAS_DEPS = True
except ImportError:
    MergeResolver = None
    MergeSuggester = None
    MergeSuggestion = None
    suggest_merges_for_cohort = None
    _HAVE_PANDAS_DEPS = False

__all__ = [
    # Club normalizer (always available)
    'normalize_club_name',
    'normalize_to_club',
    'are_same_club',
    'similarity_score',
    'group_by_club',
    'ClubNormResult',
    # Merge utilities (require pandas)
    'MergeResolver',
    'MergeSuggester',
    'MergeSuggestion',
    'suggest_merges_for_cohort',
]
