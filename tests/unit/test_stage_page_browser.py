"""The review pages' scripts (the stage page, and the merge page's connection handling), driven in
headless Chromium against a fake `window.claude` db that follows the store's contract: a first
snapshot served from cache and missing what was saved elsewhere, update() refusing a missing
document, get() and set(), random write delays, and a fresh snapshot after each write. A test
delivers the live snapshot, and drops the connection, when it chooses. Skipped where Playwright or
its Chromium is not installed."""

import json
import os
import sys

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup import pages  # noqa: E402
from scripts.team_cleanup.run_store import MANIFEST_FILE, stage_dir  # noqa: E402
from tests.unit.test_build_review_page import brp  # noqa: E402
from tests.unit.test_team_cleanup_pages import RUN, _state_week  # noqa: E402

FAKE_STORE = r"""
(() => {
  const PRELOAD = %PRELOAD%, MODE = %MODE%;
  const docs = {}, listeners = {};
  window.__docs = docs;
  window.__inflight = 0; window.__maxInflight = 0;
  const delay = () => new Promise(r => setTimeout(r, 20 + Math.random() * 120));
  const err = code => Object.assign(new Error(code), {code});
  function emit(name, fromCache){
    const snap = {docs: Object.entries(docs[name]).map(([id, d]) => ({id, data: () => JSON.parse(JSON.stringify(d))})),
                  metadata: {fromCache}};
    for (const cb of listeners[name] || []) cb(snap);
  }
  async function call(work){
    window.__inflight += 1; window.__maxInflight = Math.max(window.__maxInflight, window.__inflight);
    try { await delay(); return work(); } finally { window.__inflight -= 1; }
  }
  const db = {collection(name){
    docs[name] = docs[name] || {};
    return {
      doc(id){ return {
        update: body => call(() => {
          if (MODE === "denied") throw err("not_granted");
          if (!(id in docs[name])) throw err("invalid_argument");
          docs[name][id] = {...docs[name][id], ...body}; setTimeout(() => emit(name, false), 30);
        }),
        get: () => call(() => ({exists: id in docs[name]})),
        set: body => call(() => { docs[name][id] = {...body}; setTimeout(() => emit(name, false), 30); }),
      }; },
      onSnapshot(cb, onErr){
        (listeners[name] = listeners[name] || []).push(cb);
        setTimeout(() => emit(name, true), 10);
        window.__goLive = () => { Object.assign(docs[name], PRELOAD); emit(name, false); };
        window.__drop = onErr;
        return () => {};
      },
    };
  }};
  window.claude = {use: async cap => (cap === "db" ? db : null)};
})();
"""
LIVE = "document.querySelector('#status').textContent === 'Choices save automatically.'"


def _live(page):
    """Deliver the store's first live snapshot, after the cached one."""
    page.wait_for_function("typeof window.__goLive === 'function'")
    page.evaluate("window.__goLive()")
    page.wait_for_function(LIVE)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A real states page for the fixture week: a "B fill" group of two cards (fill, other) that the
    page can apply whole, then one unsure correction (unsure)."""
    store, db = _state_week(tmp_path_factory.mktemp("week"))
    pages.build(db, store, RUN, "states")
    folder = stage_dir(store, RUN, "states")
    manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
    page_file = folder / "smoke.html"
    page_file.write_text("<!doctype html><meta charset=utf-8>" + (folder / pages.PAGE_FILE).read_text("utf-8"), "utf-8")
    ids = {p["team_id_master"]: card for card, p in manifest["cards"].items()}
    return page_file, ids, f"decisions-{manifest['run']}"


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            chromium = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        yield chromium
        chromium.close()


@pytest.fixture
def open_page(browser, built):
    page_file, ids, _ = built
    contexts = []

    def opener(preload=None, mode="ok"):
        ctx = browser.new_context()
        contexts.append(ctx)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        saved = {ids[team]: data for team, data in (preload or {}).items()}
        page.add_init_script(FAKE_STORE.replace("%PRELOAD%", json.dumps(saved)).replace("%MODE%", json.dumps(mode)))
        page.goto(page_file.as_uri())
        return page, errors

    yield opener
    for ctx in contexts:
        ctx.close()


def _stored(page, built):
    _, ids, collection = built
    docs = page.evaluate(f"window.__docs[{json.dumps(collection)}]")
    return {team: docs.get(card) for team, card in ids.items()}


def _settle(page):
    page.wait_for_function("window.__inflight === 0")
    page.wait_for_timeout(200)


def test_editing_waits_for_a_live_snapshot_and_shows_a_choice_saved_elsewhere(open_page):
    page, errors = open_page({"other": {"decision": "dont_apply", "note": "plays in CA"}})
    other = page.locator(".card").nth(1)

    page.wait_for_function("typeof window.__goLive === 'function'")
    assert page.locator(".card").nth(0).locator("button.b-apply").is_disabled()
    _live(page)
    assert not page.locator(".card").nth(0).locator("button.b-apply").is_disabled()
    assert other.locator("button.b-dont").get_attribute("aria-pressed") == "true"
    assert other.locator("textarea").input_value() == "plays in CA"
    assert not errors


def test_apply_all_saves_only_its_groups_undecided_cards(open_page, built):
    page, errors = open_page({"other": {"decision": "dont_apply", "note": "plays in CA"}})
    _live(page)

    page.locator(".b-all").click()
    _settle(page)

    stored = _stored(page, built)
    assert stored["fill"]["decision"] == "apply"
    assert stored["other"] == {"decision": "dont_apply", "note": "plays in CA"}
    assert stored["unsure"] is None
    assert not errors


def test_apply_all_writes_one_card_at_a_time(open_page, built):
    page, errors = open_page()
    _live(page)

    page.evaluate("const b = document.querySelector('.b-all'); b.click(); b.click();")
    page.wait_for_function("document.querySelector('.b-all').disabled && window.__inflight === 0")
    _settle(page)

    stored = _stored(page, built)
    assert (stored["fill"]["decision"], stored["other"]["decision"]) == ("apply", "apply")
    assert page.evaluate("window.__maxInflight") == 1
    assert not errors


def test_a_note_typed_before_a_click_is_saved_and_a_second_click_clears_the_choice(open_page, built):
    page, errors = open_page()
    _live(page)
    unsure = page.locator(".card").nth(2)

    unsure.locator("textarea").fill("club moved to Reno")
    unsure.locator("button.b-apply").click()
    _settle(page)
    assert {k: _stored(page, built)["unsure"][k] for k in ("decision", "note")} == {
        "decision": "apply",
        "note": "club moved to Reno",
    }

    unsure.locator("button.b-apply").click()
    _settle(page)
    assert _stored(page, built)["unsure"]["decision"] is None
    assert not errors


def test_losing_the_connection_turns_editing_off(open_page):
    page, _ = open_page()
    _live(page)
    page.evaluate("window.__drop()")

    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Lost the connection')")
    assert page.locator(".card").nth(0).locator("button.b-apply").is_disabled()
    assert page.locator(".b-all").is_disabled()


def test_a_refused_write_turns_editing_off_and_shows_the_stored_choice(open_page):
    page, _ = open_page(mode="denied")
    _live(page)
    apply = page.locator(".card").nth(0).locator("button.b-apply")

    apply.click()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith(\"Changes can't be saved\")")
    assert apply.is_disabled() and apply.get_attribute("aria-pressed") == "false"


def test_the_merge_page_turns_editing_off_when_the_connection_drops(browser, tmp_path):
    def side(team_id, name):
        return {
            "team_id": team_id,
            "name": name,
            "original": None,
            "club": "Edge",
            "age": "u12",
            "gender": "Male",
            "provider": "gotsport",
            "games": 3,
            "excluded": 0,
            "first": "2026-08-30",
            "last": "2026-09-20",
        }

    run = "20261011T000000Z-abc123"
    record = {
        "id": f"{run}_{'1' * 16}",
        "n": 1,
        "status": "held",
        "reason": "same squad",
        "rows": [side("a", "Edge 2014 Black"), side("b", "Edge 14B Black")],
    }
    page_file = tmp_path / "merge.html"
    page_file.write_text("<!doctype html><meta charset=utf-8>" + brp.render([record], "Review", run), "utf-8")
    ctx = browser.new_context()
    try:
        page = ctx.new_page()
        page.add_init_script(FAKE_STORE.replace("%PRELOAD%", "{}").replace("%MODE%", json.dumps("ok")))
        page.goto(page_file.as_uri())
        _live(page)
        assert not page.locator("button.b-merge").is_disabled()

        page.evaluate("window.__drop()")
        page.wait_for_function("document.querySelector('#status').textContent.startsWith('Lost the connection')")
        assert page.locator("button.b-merge").is_disabled()
    finally:
        ctx.close()
