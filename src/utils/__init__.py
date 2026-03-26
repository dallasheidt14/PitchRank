"""Utility functions and helpers"""

# Club normalizer (no external dependencies beyond standard library + optional rapidfuzz)
from .club_normalizer import (
    normalize_club_name,
    normalize_to_club,
    are_same_club,
    similarity_score,
    group_by_club,
    get_matches_needing_review,
    get_confident_matches,
    ClubNormResult,
)

# Conditional imports for pandas-dependent modules
try:
    from .merge_resolver import MergeResolver
    _HAVE_PANDAS_DEPS = True
except ImportError:
    MergeResolver = None
    _HAVE_PANDAS_DEPS = False

__all__ = [
    # Club normalizer (always available)
    'normalize_club_name',
    'normalize_to_club',
    'are_same_club',
    'similarity_score',
    'group_by_club',
    'get_matches_needing_review',
    'ClubNormResult',
    # Merge utilities (require pandas)
    'MergeResolver',
]
