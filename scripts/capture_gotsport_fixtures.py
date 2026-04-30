"""Capture per-tier ``?group=<id>/schedules`` HTML fixtures for the gotsport
tier-section parser test corpus.

Re-runnable. Reads the hard-coded ``EVENTS_TO_CAPTURE`` dict below — the
``(event_id, [group_ids])`` pairs were derived once from the captured
landing fixtures via ``scripts/_tmp_inspect_gotsport_landing.py``. To add
a new event: drop its landing HTML in ``tests/fixtures/gotsport/``, run
the inspect script, hand-pick representative gids, paste below.

Usage::

    python scripts/capture_gotsport_fixtures.py

Each successful subfetch is saved to
``tests/fixtures/gotsport/event_<eid>__group_<gid>.html``. CAPTCHA-gated
or otherwise-failed responses are logged and skipped; the test corpus
uses ``pytest.mark.skipif(not fixture_path.exists())`` to tolerate gaps,
so a partial capture does not break CI.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

import requests

logger = logging.getLogger("capture_gotsport_fixtures")
logging.basicConfig(level=logging.INFO, format="%(message)s")

FIXTURES_DIR = Path("tests/fixtures/gotsport")
SUBPAGE_BASE = "https://system.gotsport.com/org_event/events/{eid}/schedules?group={gid}"
LANDING_BASE = "https://system.gotsport.com/org_event/events/{eid}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
THROTTLE_SECONDS = 1.0  # matches GOTSPORT_DELAY_MIN/MAX defaults
TEAM_ANCHOR_RE = re.compile(r"\bteam=\d+")
CAPTCHA_BODY_MARKER = re.compile(r"Please verify to continue", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Filled from ``scripts/_tmp_inspect_gotsport_landing.py`` output. Each list
# is a curated sample spanning the cohort + tier vocabulary that event uses.
# Comments are the raw sibling-<b> labels from the landing fixture so a
# reviewer can audit the choice without re-running the inspect script.
# ---------------------------------------------------------------------------
EVENTS_TO_CAPTURE: dict[str, list[int]] = {
    # 49371 — comprehensive coverage of every in-scope (U10+) group so the
    # orchestrator's many-subfetch state machine is fully exercised.
    "49371": [
        485294,  # U-19 BOYS GOLD
        485295,  # U-17 BOYS GOLD
        485296,  # U-16 BOYS GOLD
        485297,  # U-15 BOYS GOLD
        485298,  # U-15 BOYS SILVER
        485299,  # U-14 BOYS GOLD
        485300,  # U-13 BOYS GOLD
        485301,  # U-12 BOYS GOLD
        485425,  # U-12 BOYS SILVER
        485434,  # U-11 BOYS GOLD
        485435,  # U-11 BOYS SILVER
        485436,  # U-10 BOYS GOLD
        485439,  # U-15 GIRLS GOLD
        485440,  # U-13 GIRLS GOLD
        485441,  # U-11 GIRLS GOLD
        485442,  # U-10 GIRLS GOLD
        485444,  # U-13 BOYS SILVER
        485513,  # U-12 GIRLS GOLD
    ],
    # 42433 — color tier vocabulary; pick three U13 Boys variants.
    "42433": [
        365847,  # U13 Boys Red
        365850,  # U13 Boys White
        365849,  # U13 Boys Blue
    ],
    # 44692 — birth-year forms (B2014/B2015) + numeric Silver-N residues.
    "44692": [
        391315,  # B2015 Gold (9v9)
        391318,  # B2014 Silver 2 (9v9)
        474710,  # B2014 Silver 1 (9v9)
    ],
    # 46103 — surname tier vocabulary spanning boys/girls + multiple ages.
    "46103": [
        478925,  # U10 Boys Tolkin
        478952,  # U17 Boys Reyna
        479440,  # U11 Girls Sonnett
    ],
    # 50469 — bare U-token, color residue.
    "50469": [
        477680,  # U13 Red
        477685,  # U15 Red
        477692,  # U17 Red
    ],
    # 46958 — Form 11 glued U-prefix + gender (UxxB).
    "46958": [
        409815,  # U10B Elite White
        409827,  # U12B Premier
        409838,  # U15B Elite
    ],
    # 49407 — Form 5 reverse-token (NU BOYS) + multi-word residues + slash form.
    "49407": [
        436891,  # 11U BOYS GOLD A DIVISION
        436907,  # 14U BOYS GOLD DIVISION
        436924,  # 17/19U BOYS GOLD DIVISION
    ],
    # 45394 — bare U-token; mostly out-of-scope ages, sample the in-scope ones.
    "45394": [
        469715,  # U10 Blue
        469721,  # U14 Gold
        469726,  # U19 Gold
    ],
}


# Captcha-gated landings to attempt — separate from per-tier capture because
# the file is the challenge body itself, not a normal landing page.
CAPTCHA_GATED_LANDINGS: list[str] = [
    "47021",  # Round-2 probe found the per-event reCAPTCHA challenge here.
]


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _save(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    logger.info("saved %s (%d bytes)", path, len(body))


def capture_subpage(session: requests.Session, event_id: str, group_id: int) -> bool:
    out = FIXTURES_DIR / f"event_{event_id}__group_{group_id}.html"
    if out.exists():
        logger.info("skip %s — already captured", out.name)
        return True
    url = SUBPAGE_BASE.format(eid=event_id, gid=group_id)
    try:
        resp = session.get(url, timeout=30)
    except requests.RequestException as exc:
        logger.warning("event %s group %s: HTTP error %s", event_id, group_id, exc)
        return False
    body = resp.text or ""
    if resp.status_code != 200:
        logger.warning("event %s group %s: HTTP %s", event_id, group_id, resp.status_code)
        return False
    if CAPTCHA_BODY_MARKER.search(body):
        logger.warning("event %s group %s: CAPTCHA-gated, skipping", event_id, group_id)
        return False
    if not TEAM_ANCHOR_RE.search(body):
        logger.warning("event %s group %s: no ?team= anchors found, skipping", event_id, group_id)
        return False
    _save(out, body)
    return True


def capture_captcha_landing(session: requests.Session, event_id: str) -> bool:
    out = FIXTURES_DIR / f"event_{event_id}.html"
    if out.exists():
        logger.info("skip %s — already captured", out.name)
        return True
    url = LANDING_BASE.format(eid=event_id)
    try:
        resp = session.get(url, timeout=30)
    except requests.RequestException as exc:
        logger.warning("event %s landing: HTTP error %s", event_id, exc)
        return False
    body = resp.text or ""
    if not CAPTCHA_BODY_MARKER.search(body):
        logger.warning(
            "event %s landing: no captcha marker — gate may have cleared. "
            "Aborting capture so we don't overwrite the test corpus with a normal landing.",
            event_id,
        )
        return False
    _save(out, body)
    return True


def main() -> int:
    session = _make_session()
    captured = 0
    failed = 0

    for event_id in CAPTCHA_GATED_LANDINGS:
        if capture_captcha_landing(session, event_id):
            captured += 1
        else:
            failed += 1
        time.sleep(THROTTLE_SECONDS)

    for event_id, group_ids in EVENTS_TO_CAPTURE.items():
        for gid in group_ids:
            if capture_subpage(session, event_id, gid):
                captured += 1
            else:
                failed += 1
            time.sleep(THROTTLE_SECONDS)

    logger.info("done. captured=%d failed=%d", captured, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
