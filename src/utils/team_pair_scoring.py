"""Adapter for the weekly hygiene pipeline's ``score_team_pair`` so
``src/models/`` matchers can re-use the same provider→canonical scoring
the Monday hygiene job uses for queue resolution.

Why an adapter and not a clean ``src/utils/`` rewrite?

The canonical implementations live in
``scripts/find_fuzzy_duplicate_teams.py`` and
``scripts/_team_distinction.py`` because they were authored alongside the
weekly hygiene workflow (``data-hygiene-weekly.yml``). Moving them
wholesale would touch ~2,000 lines across 3 script modules; the scope of
this PR is the provider-side matcher wire-in. The adapter below imports
them via a controlled ``sys.path`` shim so the dependency graph is
isolated to one file.

**Follow-up**: migrate ``scripts/find_fuzzy_duplicate_teams.py`` +
``scripts/find_queue_matches.py::{normalize_team_name,
extract_team_variant, has_protected_division}`` +
``scripts/_team_distinction.py`` into ``src/utils/`` so this shim can go
away. That's a separate PR — it'll need careful regression testing on
the hygiene pipeline because the weekly merge logic is load-bearing.

Exposed names (stable; matchers should import only from here):
  - ``score_team_pair(team_a, team_b) -> float | None`` — main scorer
  - ``should_skip_pair(name_a, name_b, club_name, ...) -> bool`` — distinction-aware hard reject
"""

from __future__ import annotations

import sys
from pathlib import Path

# The scripts/ dir is a sibling of src/. Hardcoded relative resolution so
# importing this module doesn't depend on the caller's sys.path setup
# (e.g., during pytest runs or matcher instantiation from the pipeline).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
# find_fuzzy_duplicate_teams itself imports from sibling scripts using a
# similar shim — ensure the repo root is also reachable so its
# ``from src.utils.team_name_utils import ...`` doesn't fail when loaded
# via this adapter.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _team_distinction import should_skip_pair  # noqa: E402
from find_fuzzy_duplicate_teams import score_team_pair  # noqa: E402

__all__ = ["score_team_pair", "should_skip_pair"]
