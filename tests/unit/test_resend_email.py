"""Tests for src/utils/resend_email.py."""

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils import resend_email  # noqa: E402


class _Response:
    def __init__(self, status_code, text=""):
        self.status_code, self.text = status_code, text


def _posting(monkeypatch, answer):
    posts = []

    def post(url, **kwargs):
        posts.append((url, kwargs))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(resend_email.requests, "post", post)
    return posts


def test_an_accepted_email_names_its_recipient_subject_and_body(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    posts = _posting(monkeypatch, _Response(200))

    assert resend_email.send_email("owner@example.test", "Subject", "<p>Body</p>") is True

    url, kwargs = posts[0]
    assert url == "https://api.resend.com/emails"
    assert kwargs["headers"]["Authorization"] == "Bearer re_test"
    assert kwargs["json"] == {
        "from": "PitchRank <newsletter@mail.pitchrank.io>",
        "to": ["owner@example.test"],
        "subject": "Subject",
        "html": "<p>Body</p>",
    }
    assert kwargs["timeout"] == 10


def test_without_a_key_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    posts = _posting(monkeypatch, _Response(200))

    assert resend_email.send_email("owner@example.test", "Subject", "<p>Body</p>") is False
    assert posts == []


def test_a_refusal_or_a_lost_connection_reports_the_email_unsent(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    _posting(monkeypatch, _Response(422, "invalid"))
    assert resend_email.send_email("owner@example.test", "Subject", "<p>Body</p>") is False

    _posting(monkeypatch, requests.ConnectionError("reset"))
    assert resend_email.send_email("owner@example.test", "Subject", "<p>Body</p>") is False


def test_a_refused_header_keeps_the_key_out_of_the_log(monkeypatch, caplog):
    monkeypatch.setenv("RESEND_API_KEY", "re_te\nst")
    _posting(monkeypatch, requests.exceptions.InvalidHeader("Invalid header value b'Bearer re_te\\nst'"))

    assert resend_email.send_email("owner@example.test", "Subject", "<p>Body</p>") is False
    assert "Sending the email failed: InvalidHeader" in caplog.text and "re_te" not in caplog.text
