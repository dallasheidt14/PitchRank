"""Every workflow step that scrapes a GotSport event page is given the ZenRows key.

``GotsportScraper`` decides whether to proxy from the mere presence of the variable::

    self.zenrows_api_key = os.getenv("ZENROWS_API_KEY")
    self.use_zenrows = bool(self.zenrows_api_key)

so a step that omits it does not fail, warn, or log anything -- ``_fetch_event_page``
quietly fetches ``system.gotsport.com`` through a plain session instead. GotSport 403s
that from a GitHub runner and redirects to a login host that then times out, so the
event yields zero games and the failure surfaces far downstream as a missing output
file. ``weekly-prospective-refresh.yml`` ran red every week from 2026-04-28 to
2026-09-07 on exactly that, 19 consecutive runs, because the omission is invisible.

The invariant is pinned rather than the four steps that hold it today: the script list
is derived by searching for the event-page calls themselves, so a new caller, or a new
workflow running an existing one, fails this test until it is given the key too.

The API-only GotSport paths are deliberately out of scope. ``system.gotsport.com/api/v1``
is not behind the same WAF -- ``process-missing-games.yml`` drains the queue every 15
minutes without the key and stays green -- so requiring it there would be cargo cult.
"""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
SCRIPTS = PROJECT_ROOT / "scripts"
SCRAPER = PROJECT_ROOT / "src" / "scrapers" / "gotsport.py"

ZENROWS_VAR = "ZENROWS_API_KEY"

# Methods that fetch an event page rather than the JSON API. A script calling any of
# them needs the proxy; one that only touches the API does not.
EVENT_PAGE_CALLS = (
    "scrape_games_from_schedule_pages",
    "extract_event_teams",
    "_fetch_event_page",
)


def _event_page_scripts() -> set[str]:
    """Script filenames that reach an event page, found by their calls."""
    found = set()
    for path in SCRIPTS.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(call in text for call in EVENT_PAGE_CALLS):
            found.add(path.name)
    return found


def _steps_running(script_name: str):
    """(workflow path, job env, workflow env, step) for every step invoking the script."""
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        try:
            doc = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        except yaml.YAMLError:  # pragma: no cover - a malformed workflow is its own failure
            continue
        if not isinstance(doc, dict):
            continue
        workflow_env = doc.get("env") or {}
        for job in (doc.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            job_env = job.get("env") or {}
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                run = step.get("run") or ""
                if f"scripts/{script_name}" in run:
                    yield workflow, job_env, workflow_env, step


def test_the_event_page_call_markers_still_exist():
    """A rename that empties EVENT_PAGE_CALLS would leave this whole module vacuous."""
    text = SCRAPER.read_text(encoding="utf-8", errors="ignore")
    missing = [call for call in EVENT_PAGE_CALLS if f"def {call}" not in text]
    assert not missing, (
        f"{missing} no longer defined in {SCRAPER.name}; update EVENT_PAGE_CALLS or this "
        "guard silently covers nothing."
    )


def test_some_scripts_are_actually_discovered():
    """The derivation must find callers, or every assertion below passes vacuously."""
    assert _event_page_scripts(), (
        "No script matched EVENT_PAGE_CALLS. Either the scraper API was renamed or the "
        "glob is wrong; in both cases this guard is inert."
    )


def test_the_zenrows_decision_is_still_presence_based():
    """The whole risk is that absence is silent rather than loud."""
    text = SCRAPER.read_text(encoding="utf-8", errors="ignore")
    assert f'os.getenv("{ZENROWS_VAR}")' in text, (
        f"{ZENROWS_VAR} is no longer read by name in {SCRAPER.name}. If the scraper now "
        "fails loudly without a proxy, this guard can be retired; if it just moved, "
        "update it."
    )


@pytest.mark.parametrize("script_name", sorted(_event_page_scripts()))
def test_event_page_steps_pass_the_zenrows_key(script_name):
    """Each workflow step running an event-page script resolves ZENROWS_API_KEY."""
    offenders = []
    for workflow, job_env, workflow_env, step in _steps_running(script_name):
        step_env = step.get("env") or {}
        if ZENROWS_VAR in step_env or ZENROWS_VAR in job_env or ZENROWS_VAR in workflow_env:
            continue
        offenders.append(f"{workflow.name} -> step {step.get('name', '<unnamed>')!r}")

    assert not offenders, (
        f"{script_name} scrapes GotSport event pages, so these steps need "
        f"{ZENROWS_VAR} and do not have it: {offenders}. Without it the scrape returns "
        "zero games and logs nothing about why."
    )
