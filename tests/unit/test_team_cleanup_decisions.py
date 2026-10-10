"""Tests for the owner's standing team-cleanup decisions, as the duplicate scans read them."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.find_cross_provider_duplicates import resolver  # noqa: E402
from scripts.team_cleanup import decisions as dec  # noqa: E402

REASON = "the owner chose Keep separate on 2026-09-25"


def decision(team_id, other_team_id, decided_at="2026-09-25T06:37:42+00:00"):
    return dec.KeepSeparate(team_id, other_team_id, decided_at)


def row(team_id, other_team_id, *, superseded_at=None):
    return {
        "id": f"{team_id}-{other_team_id}",
        "team_id_master": team_id,
        "other_team_id": other_team_id,
        "decided_at": "2026-09-25T06:37:42+00:00",
        "superseded_at": superseded_at,
    }


class _Cause(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def unavailable(code):
    try:
        raise dec.DecisionsUnavailable("could not read") from _Cause(code)
    except dec.DecisionsUnavailable as exc:
        return exc


def test_the_pair_subject_is_the_same_whichever_team_comes_first():
    assert dec.pair_subject("b", "a") == dec.pair_subject("a", "b") == "a|b"


def test_a_superseded_decision_is_not_active():
    active = dec.active_keep_separate([row("a", "b"), row("c", "d", superseded_at="2026-10-01T00:00:00+00:00")])
    assert active == [decision("a", "b")]


def test_a_decision_follows_each_team_to_the_row_it_was_merged_into():
    canonical = resolver({"a": "a2", "a2": "a3"})
    index = dec.keep_separate_index([decision("a", "b")], canonical)
    assert dec.kept_apart_reason(index, canonical, "a3", "b") == REASON


def test_a_decision_is_found_from_either_side():
    canonical = resolver({})
    index = dec.keep_separate_index([decision("a", "b")], canonical)
    assert dec.kept_apart_reason(index, canonical, "b", "a") == REASON


def test_a_pair_merged_together_anyway_holds_nothing():
    canonical = resolver({"a": "b"})
    assert dec.keep_separate_index([decision("a", "b")], canonical) == {}


def test_an_unrelated_pair_is_not_kept_apart():
    canonical = resolver({})
    index = dec.keep_separate_index([decision("a", "b")], canonical)
    assert dec.kept_apart_reason(index, canonical, "a", "c") is None


def test_only_a_table_missing_from_the_schema_cache_counts_as_missing():
    assert unavailable("PGRST205").table_missing is True
    assert unavailable("42501").table_missing is False
