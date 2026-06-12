"""Unit tests for ``_normalize_text`` in the AthleteOne/TGS HTML parser.

Scraped free-text flows into DB inserts unmodified, so ``_normalize_text``
caps stored values at ``_MAX_TEXT_LENGTH`` by default while leaving searched-but-
not-stored text uncapped via ``max_length=None``.
"""

from __future__ import annotations

from src.providers.athleteone_html_parser import _MAX_TEXT_LENGTH, _normalize_text


def test_normalize_text_caps_at_max_length_by_default():
    long_text = "x" * 500
    assert len(_normalize_text(long_text)) == _MAX_TEXT_LENGTH


def test_normalize_text_uncapped_when_max_length_none():
    long_text = "x" * 500
    assert len(_normalize_text(long_text, max_length=None)) == 500


def test_normalize_text_collapses_whitespace():
    assert _normalize_text("  a   b  ") == "a b"
