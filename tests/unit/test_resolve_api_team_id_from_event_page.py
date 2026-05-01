"""Unit tests for ``GotsportScraper._resolve_api_team_id_from_event_page``.

Verifies the post-2026-05-01 API-first contract documented in
``src/scrapers/gotsport.py``. The resolver MUST return ``None`` on no-self-match
— promoting the queried id to a canonical API team_id was the bug this rewrite
fixed.

Self-match is on ``homeTeam.team_id`` / ``awayTeam.team_id``, NOT on
``home_team_reg_id`` / ``away_team_reg_id`` — the gotsport API endpoint only
accepts api_team_ids (verified live 2026-05-01: a known reg_id returns 404).
The reg_id fields in match records are the per-event registrations of BOTH
teams; they're not the queried team's reg_id.

Tests stub ``_fetch_json_via_zenrows`` instead of constructing a full
``GotsportScraper`` so the heavyweight ``__init__`` (Supabase ``providers``
round-trip, nested scraper init) doesn't run.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from src.scrapers.gotsport import GotsportScraper


def _make_response(status_code: int, body: Any = None, raises_json: bool = False) -> MagicMock:
    """Build a fake ``requests.Response`` covering the surface the resolver reads."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    if raises_json:
        response.json.side_effect = json.JSONDecodeError("expecting value", "", 0)
    else:
        response.json.return_value = body
    return response


def _resolver(response_or_exc: Any):
    """Build a barebones scraper stand-in with a stubbed _fetch_json_via_zenrows."""
    scraper = MagicMock(spec=GotsportScraper)
    if isinstance(response_or_exc, Exception):
        scraper._fetch_json_via_zenrows.side_effect = response_or_exc
    else:
        scraper._fetch_json_via_zenrows.return_value = response_or_exc
    # Bind the real resolver so it operates on our stub
    scraper._resolve_api_team_id_from_event_page = (
        GotsportScraper._resolve_api_team_id_from_event_page.__get__(scraper, GotsportScraper)
    )
    return scraper


class TestResolveApiTeamIdFromEventPage:
    def test_self_match_on_away_team_id_returns_queried_id(self):
        # Schedule page link `team=255164` is the API team_id; API returns
        # matches where 255164 IS awayTeam.team_id.
        body = [
            {
                "home_team_reg_id": 3714464,
                "away_team_reg_id": 3714466,
                "homeTeam": {"team_id": 630656},
                "awayTeam": {"team_id": 255164},
            }
        ]
        scraper = _resolver(_make_response(200, body))
        assert scraper._resolve_api_team_id_from_event_page("e1", "255164", "Away FC") == "255164"

    def test_self_match_on_home_team_id_returns_queried_id(self):
        body = [
            {
                "home_team_reg_id": 3714464,
                "away_team_reg_id": 3714466,
                "homeTeam": {"team_id": 630656},
                "awayTeam": {"team_id": 255164},
            }
        ]
        scraper = _resolver(_make_response(200, body))
        assert scraper._resolve_api_team_id_from_event_page("e1", "630656", "Home FC") == "630656"

    def test_no_self_match_returns_none(self):
        # 200 OK but the queried id doesn't appear as home/away team_id in any
        # match — defensive against malformed response. Must NOT promote the
        # queried id (that's the bug this rewrite fixed).
        body = [
            {
                "home_team_reg_id": 111,
                "away_team_reg_id": 222,
                "homeTeam": {"team_id": 333},
                "awayTeam": {"team_id": 444},
            }
        ]
        scraper = _resolver(_make_response(200, body))
        assert scraper._resolve_api_team_id_from_event_page("e1", "999999", "Some FC") is None

    def test_reg_id_self_match_does_not_count(self):
        # If the queried id matches a home_team_reg_id or away_team_reg_id but
        # NOT a homeTeam.team_id / awayTeam.team_id, treat as no self-match.
        # (This case shouldn't happen in practice — reg_ids 404 — but the
        # resolver must not be tricked into promoting a reg_id by stale data.)
        body = [
            {
                "home_team_reg_id": 3714466,  # numeric coincidence with queried id
                "away_team_reg_id": 222,
                "homeTeam": {"team_id": 100001},
                "awayTeam": {"team_id": 100002},
            }
        ]
        scraper = _resolver(_make_response(200, body))
        assert scraper._resolve_api_team_id_from_event_page("e1", "3714466", "Reg ID FC") is None

    def test_empty_list_returns_none(self):
        scraper = _resolver(_make_response(200, []))
        assert scraper._resolve_api_team_id_from_event_page("e1", "12345", None) is None

    def test_404_returns_none(self):
        # Verified live 2026-05-01: querying a reg_id returns 404. This is
        # the deterministic registration-vs-api-id classifier.
        scraper = _resolver(_make_response(404))
        assert scraper._resolve_api_team_id_from_event_page("e1", "3714466", None) is None

    def test_500_returns_none(self):
        scraper = _resolver(_make_response(500))
        assert scraper._resolve_api_team_id_from_event_page("e1", "12345", None) is None

    def test_network_error_returns_none(self):
        scraper = _resolver(requests.ConnectionError("boom"))
        assert scraper._resolve_api_team_id_from_event_page("e1", "12345", None) is None

    def test_malformed_json_returns_none(self):
        # response.json() raising JSONDecodeError is in the resolver's
        # exception tuple — must not propagate.
        scraper = _resolver(_make_response(200, raises_json=True))
        assert scraper._resolve_api_team_id_from_event_page("e1", "12345", None) is None

    def test_match_with_none_team_ids_returns_none(self):
        # Defensive: a partial-write match record where homeTeam/awayTeam
        # team_id is None must not crash the resolver via str(None) coercion.
        body = [
            {
                "homeTeam": {"team_id": None},
                "awayTeam": {"team_id": None},
                "home_team_reg_id": 111,
                "away_team_reg_id": 222,
            }
        ]
        scraper = _resolver(_make_response(200, body))
        assert scraper._resolve_api_team_id_from_event_page("e1", "12345", None) is None

    def test_non_list_body_returns_none(self):
        # API contract drift: gotsport returns a wrapper dict instead of a
        # list. Resolver must treat as unresolved.
        scraper = _resolver(_make_response(200, {"matches": []}))
        assert scraper._resolve_api_team_id_from_event_page("e1", "12345", None) is None

    @pytest.mark.parametrize("queried_id", ["255164", 255164])
    def test_str_coercion_on_both_sides(self, queried_id):
        # Both sides of the team_id comparison are str-coerced so a numeric
        # API response value matches a string call-site argument.
        body = [
            {
                "homeTeam": {"team_id": 255164},  # int from API
                "awayTeam": {"team_id": 444},
                "home_team_reg_id": 999,
                "away_team_reg_id": 998,
            }
        ]
        scraper = _resolver(_make_response(200, body))
        assert scraper._resolve_api_team_id_from_event_page("e1", str(queried_id), None) == "255164"
