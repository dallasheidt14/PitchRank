"""Every workflow step that scrapes a GotSport event page is given the ZenRows key.

``GotsportScraper`` decides whether to proxy from the mere presence of the variable::

    self.zenrows_api_key = os.getenv("ZENROWS_API_KEY")
    self.use_zenrows = bool(self.zenrows_api_key)

so a step that omits it does not fail, warn, or log anything -- ``_fetch_event_page``
quietly fetches ``system.gotsport.com`` through a plain session instead. GotSport 403s
that from a GitHub runner and redirects to a login host that then times out.

The omission is invisible at both ends. ``scrape_games_from_schedule_pages`` catches the
403, logs one line and returns an empty list, so the scrape writes a zero-row file and
**exits 0**: the step goes green having found nothing. ``weekly-prospective-refresh.yml``
scraped zero games this way from 2026-04-28 to 2026-09-07 while its red X came from an
unrelated expired model artifact, so the empty scrape went unnoticed for four months.
A green event-scrape step is not evidence that fixtures were found.

**The method list is derived, not written down.** A first draft of this guard hard-coded
three method names and was wrong in both directions: it missed ``scrape_event_games`` and
``fetch_teams_by_cohort`` entirely -- leaving ``scrape_event.py`` uncovered -- while
matching ``scrape_specific_event.py`` only because a *comment* there names
``_fetch_event_page``. Deleting that comment would have dropped the coverage silently.
So the entry points are read out of the scraper class body (every method that touches
``EVENT_BASE`` or calls ``_fetch_event_page``), and scripts are matched on call syntax
rather than bare substring, so a mention in prose does not count as a use.
"""

import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
SCRIPTS = PROJECT_ROOT / "scripts"
SCRAPER = PROJECT_ROOT / "src" / "scrapers" / "gotsport.py"

ZENROWS_VAR = "ZENROWS_API_KEY"

# The event-page scraper class. The other class in this module is the JSON API client,
# which is deliberately out of scope -- see the module docstring's closing note.
EVENT_CLASS = "class GotsportScraper"

# What marks a method as reaching an event page rather than the JSON API.
EVENT_PAGE_MARKERS = ("EVENT_BASE", "_fetch_event_page")

# Not an entry point a script would call -- it is the proxy transport itself, and it
# appears in the derivation only because it is defined alongside the callers.
NOT_AN_ENTRY_POINT = {"_make_zenrows_request"}


def _event_page_methods() -> set[str]:
    """Methods on the event-page class that reach an event page, read from its body."""
    lines = SCRAPER.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(EVENT_CLASS))

    methods: set[str] = set()
    current: str | None = None
    for line in lines[start:]:
        if line.startswith("class ") and not line.startswith(EVENT_CLASS):
            break
        match = re.match(r"    def (\w+)\(", line)
        if match:
            current = match.group(1)
        elif current and any(marker in line for marker in EVENT_PAGE_MARKERS):
            methods.add(current)
    return methods - NOT_AN_ENTRY_POINT


def _event_page_scripts() -> set[str]:
    """Script filenames that import the GotSport scraper *and* call one of its methods.

    Both halves are needed. Prose does not count as a call, and a call alone does not
    imply GotSport: ``scrape_athleteone_weekly.py`` calls its own provider's
    ``scrape_event_games`` and must not be told it needs a ZenRows key.
    """
    methods = _event_page_methods()
    calls = re.compile(r"\.(" + "|".join(sorted(map(re.escape, methods))) + r")\s*\(")
    imports_gotsport = re.compile(r"^\s*(from|import)\s+.*gotsport", re.IGNORECASE)

    found = set()
    for path in SCRIPTS.glob("*.py"):
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not any(imports_gotsport.match(line) for line in lines):
            continue
        if any(calls.search(line.split("#", 1)[0]) for line in lines):
            found.add(path.name)
    return found


def _steps_running(script_name: str):
    """(workflow, job env, workflow env, step) for every step invoking the script."""
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
                if isinstance(step, dict) and f"scripts/{script_name}" in (step.get("run") or ""):
                    yield workflow, job_env, workflow_env, step


def test_the_event_class_and_its_markers_still_exist():
    """A rename that empties the derivation would leave this whole module vacuous."""
    text = SCRAPER.read_text(encoding="utf-8", errors="ignore")
    assert EVENT_CLASS in text, f"{EVENT_CLASS} not found in {SCRAPER.name}; update this guard."
    for marker in EVENT_PAGE_MARKERS:
        assert marker in text, f"{marker} gone from {SCRAPER.name}; the derivation is now blind."


def test_the_derivation_finds_the_known_entry_points():
    """Named literally: asserting against the derivation itself would always hold.

    These four are the ones a caller actually reaches for. If a rename drops one, the
    guard would quietly stop covering its callers, which is how the first draft of this
    module missed two of them.
    """
    methods = _event_page_methods()
    for expected in (
        "scrape_event_games",
        "scrape_games_from_schedule_pages",
        "extract_event_teams",
        "fetch_teams_by_cohort",
    ):
        assert expected in methods, f"{expected} no longer derived; coverage silently shrank."


def test_some_scripts_are_actually_discovered():
    """The derivation must find callers, or every assertion below passes vacuously."""
    assert _event_page_scripts(), "No script calls an event-page method; this guard is inert."


def test_a_prose_mention_is_not_treated_as_a_call():
    """scrape_specific_event.py names _fetch_event_page in a comment explaining why it
    does NOT use it. Counting that as a call is what made the first draft look complete."""
    calls = re.compile(r"\.(" + "|".join(sorted(map(re.escape, _event_page_methods()))) + r")\s*\(")
    assert not calls.search("    # (not the CAPTCHA-aware _fetch_event_page) so an archived")


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
        "zero games and still exits 0."
    )
