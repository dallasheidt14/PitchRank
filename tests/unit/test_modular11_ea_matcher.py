"""The EA matcher resolves teams only through modular11_ea aliases."""

import inspect
from unittest.mock import MagicMock

from src.etl import enhanced_pipeline
from src.models.modular11_ea_matcher import Modular11EaGameMatcher

PROVIDER = "prov-ea"


def _matcher(cache=None):
    matcher = Modular11EaGameMatcher(MagicMock(), provider_id=PROVIDER, alias_cache=cache or {}, dry_run=True)
    matcher._validate_team_age_group = lambda *a, **k: True
    return matcher


def test_cached_alias_resolves():
    matcher = _matcher({"7155": {"team_id_master": "T1", "match_method": "direct_id", "review_status": "approved"}})
    result = matcher._match_team(PROVIDER, "7155", "Emerald City FC", "u17", "Male")
    assert (result["matched"], result["team_id"], result["method"]) == (True, "T1", "direct_id")


def test_unlinked_team_never_fuzzy_matches_or_creates():
    matcher = _matcher()
    matcher._match_by_provider_id = lambda *a, **k: None
    matcher._match_by_alias = MagicMock(side_effect=AssertionError("name alias must not run"))
    matcher._fuzzy_match_team = MagicMock(side_effect=AssertionError("fuzzy must not run"))
    matcher._create_alias = MagicMock(side_effect=AssertionError("must not write"))
    result = matcher._match_team(PROVIDER, "999", "Emerald City FC", "u17", "Male")
    assert result == {"matched": False, "team_id": None, "method": None, "confidence": 0.0}


def test_pipeline_selects_ea_matcher():
    source = inspect.getsource(enhanced_pipeline)
    assert 'elif self.provider_code.lower() == "modular11_ea":' in source
    assert "Modular11EaGameMatcher(" in source
