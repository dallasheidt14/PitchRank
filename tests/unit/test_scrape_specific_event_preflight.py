"""The pre-flight fetch must not retire a live event on a WAF redirect.

``scrape_specific_event`` opens with one direct ``session.get`` to read the event's
title. That fetch is the only one in the run that does not go through ZenRows, and it
cannot go through it: the proxy returns the ``api.zenrows.com`` URL with the target
percent-encoded inside it, so there is no landing URL to test.

That makes the redirect signal a statement about the caller's IP as much as about the
event. From a GitHub runner GotSport's WAF redirects to the login host, and the script
used to read that as "archived or invalid" and return -- aborting before the proxied
scrape, which is the part that would have worked, ever ran. Raised by Codex on #1104.
"""

import pytest

from scripts.scrape_specific_event import preflight_verdict

EVENT_URL = "https://system.gotsport.com/org_event/events/51201"
LOGIN_HOST = "https://home.gotsport.com/"
LOGIN_PATH = "https://home.gotsport.com/login/"


@pytest.mark.parametrize("use_zenrows", [True, False])
def test_landing_on_the_event_is_ok_either_way(use_zenrows):
    assert preflight_verdict(EVENT_URL, use_zenrows=use_zenrows) == "ok"


@pytest.mark.parametrize("landing", [LOGIN_HOST, LOGIN_PATH, "https://system.gotsport.com/"])
def test_a_redirect_without_a_proxy_still_reads_as_archived(landing):
    """Unproxied, the signal is the best available and its old meaning is kept."""
    assert preflight_verdict(landing, use_zenrows=False) == "archived"


@pytest.mark.parametrize("landing", [LOGIN_HOST, LOGIN_PATH, "https://system.gotsport.com/"])
def test_a_redirect_with_a_proxy_configured_is_inconclusive(landing):
    """The regression: this returned 'archived' and aborted the whole run."""
    assert preflight_verdict(landing, use_zenrows=True) == "inconclusive"


def test_only_archived_is_fatal():
    """Naming the three verdicts as literals -- deriving them from the function under
    test would hold for any renaming, including one that made 'inconclusive' fatal."""
    assert preflight_verdict(LOGIN_PATH, use_zenrows=False) == "archived"
    assert preflight_verdict(LOGIN_PATH, use_zenrows=True) != "archived"
    assert preflight_verdict(EVENT_URL, use_zenrows=True) != "archived"
