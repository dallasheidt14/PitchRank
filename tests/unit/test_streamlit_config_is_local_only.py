"""The repo's Streamlit apps listen only on this machine and check the page's origin.

A ``streamlit run`` from the repo root reads ``.streamlit/config.toml``, and these
settings are what keep the apps' service-role key off the network. The origin
check still trusts any page served from this machine, on any port, and a
DNS-rebinding page can pass it. A login would close both; a Host check only the
rebinding path.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"


def _server() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))["server"]


def test_the_apps_listen_only_on_this_machine():
    assert _server().get("address") == "127.0.0.1"


def test_the_origin_and_xsrf_checks_are_on():
    server = _server()

    assert server.get("enableCORS") is True
    assert server.get("enableXsrfProtection") is True
