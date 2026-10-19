"""Send one email through Resend's HTTP API."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
FROM_EMAIL = "PitchRank <newsletter@mail.pitchrank.io>"
TIMEOUT_SECONDS = 10


def send_email(to: str, subject: str, html: str) -> bool:
    """Whether Resend accepted the email. Without RESEND_API_KEY nothing is sent."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        logger.warning("RESEND_API_KEY is not set, so no email was sent")
        return False
    try:
        resp = requests.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": FROM_EMAIL, "to": [to], "subject": subject, "html": html},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        # Only the exception's type: a malformed key fails as InvalidHeader, whose message quotes the header.
        logger.warning("Sending the email failed: %s", type(exc).__name__)
        return False
    if resp.status_code == 200:
        return True
    logger.warning("Resend answered %s: %s", resp.status_code, resp.text[:300])
    return False
