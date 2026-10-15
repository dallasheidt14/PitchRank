"""The Kitman matcher resolves teams only through mlsnext_kitman aliases."""

import inspect
from unittest.mock import MagicMock

from src.etl import enhanced_pipeline
from src.models.mlsnext_kitman_matcher import PROVIDER_CODE, MlsNextKitmanGameMatcher

PROVIDER = "prov-kitman"


def _matcher(cache=None):
    matcher = MlsNextKitmanGameMatcher(MagicMock(), provider_id=PROVIDER, alias_cache=cache or {}, dry_run=True)
    matcher._validate_team_age_group = lambda *a, **k: True
    return matcher


def test_cached_alias_resolves():
    matcher = _matcher({"5747:2026": {"team_id_master": "T1", "match_method": "direct_id", "review_status": "approved"}})
    result = matcher._match_team(PROVIDER, "5747:2026", "Club U13 HD", "u13", "Male")
    assert (result["matched"], result["team_id"], result["method"]) == (True, "T1", "direct_id")


def test_unlinked_team_never_fuzzy_matches_or_creates():
    matcher = _matcher()
    matcher._match_by_provider_id = lambda *a, **k: None
    matcher._match_by_alias = MagicMock(side_effect=AssertionError("name alias must not run"))
    matcher._fuzzy_match_team = MagicMock(side_effect=AssertionError("fuzzy must not run"))
    matcher._create_alias = MagicMock(side_effect=AssertionError("must not write"))
    result = matcher._match_team(PROVIDER, "999:2026", "Club U13 HD", "u13", "Male")
    assert result == {"matched": False, "team_id": None, "method": None, "confidence": 0.0}


def test_a_blank_id_is_unmatched():
    assert _matcher()._match_team(PROVIDER, "", "Club U13 HD", "u13", "Male")["matched"] is False


def test_provider_code_is_the_seeded_one():
    assert PROVIDER_CODE == "mlsnext_kitman"


def test_pipeline_selects_the_kitman_matcher_with_dry_run():
    source = inspect.getsource(enhanced_pipeline)
    branch = source.split('elif self.provider_code.lower() == "mlsnext_kitman":', 1)[1].split("elif ", 1)[0]
    assert "MlsNextKitmanGameMatcher(" in branch
    assert "dry_run=self.dry_run" in branch
