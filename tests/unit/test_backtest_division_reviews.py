"""Operator division reviews survive refreshes and concurrent intake saves."""

from contextlib import contextmanager
from dataclasses import replace

import pytest

from src.tournaments import backtest_intake_state as state
from tests.unit.test_backtest_intake_state import sample_snapshot

EVENT_KEY = "gotsport__51783__2025"


def reviewed_snapshot():
    snapshot = sample_snapshot()
    reviews = tuple(
        state.DivisionReview(
            division.group_id,
            state.structure_hash(division),
            notes=notes,
            source_url=url,
            checked=True,
        )
        for division, notes, url in zip(
            snapshot.roster.divisions,
            ("Top two advance; final goes to penalties", "Three-team round robin"),
            ("https://example.test/rules/gold", "https://example.test/rules/silver"),
        )
    )
    return replace(snapshot, reviews=reviews)


def edit_review(snapshot, group_id="10", **changes):
    return replace(snapshot, reviews=tuple(
        replace(review, **changes) if review.group_id == group_id else review
        for review in snapshot.reviews
    ))


def saved_reviews(tmp_path):
    return {review.group_id: review for review in state.read_snapshot(EVENT_KEY, base_dir=tmp_path).reviews}


def changed_structure(snapshot):
    division = snapshot.roster.divisions[0]
    fixture = replace(division.fixtures[0], location="Field 2")
    division = replace(division, fixtures=(fixture,))
    roster = replace(snapshot.roster, divisions=(division,) + snapshot.roster.divisions[1:])
    return state.BacktestSnapshot.create(roster, snapshot.resolved)


@pytest.mark.parametrize("incoming", ["no_reviews", "default_review", "identical_reviews"])
def test_fresh_capture_save_preserves_saved_notes_sources_and_checks(tmp_path, incoming):
    original = reviewed_snapshot()
    state.write_snapshot(EVENT_KEY, original, base_dir=tmp_path)
    refreshed = state.BacktestSnapshot.create(original.roster, original.resolved)
    if incoming == "default_review":
        refreshed = replace(refreshed, reviews=(state.DivisionReview(
            "10", state.structure_hash(refreshed.roster.divisions[0])
        ),))
    elif incoming == "identical_reviews":
        refreshed = replace(refreshed, reviews=original.reviews)

    path = state.write_snapshot(EVENT_KEY, refreshed, base_dir=tmp_path)

    loaded = state.read_snapshot(EVENT_KEY, base_dir=tmp_path)
    assert path == state.snapshot_path(EVENT_KEY, base_dir=tmp_path)
    assert loaded.generation == refreshed.generation != original.generation
    assert loaded.reviews == original.reviews


@pytest.mark.parametrize("omit_review", [False, True])
@pytest.mark.parametrize("field,value", [
    ("notes", "Top two advance; no extra time"),
    ("source_url", "https://example.test/corrected-source"),
    ("checked", False),
])
def test_stale_session_save_preserves_another_sessions_new_review(tmp_path, omit_review, field, value):
    baseline = reviewed_snapshot()
    state.write_snapshot(EVENT_KEY, baseline, base_dir=tmp_path)
    updated = edit_review(baseline, **{field: value})
    state.write_snapshot(EVENT_KEY, updated, base_dir=tmp_path, review_baseline=baseline.reviews)
    stale = replace(baseline, resolved=tuple(
        replace(outcome, team_id_master="resolved-later") for outcome in baseline.resolved
    ))
    if omit_review:
        stale = replace(stale, reviews=stale.reviews[1:])

    state.write_snapshot(EVENT_KEY, stale, base_dir=tmp_path, review_baseline=baseline.reviews)

    loaded = state.read_snapshot(EVENT_KEY, base_dir=tmp_path)
    assert loaded.reviews == updated.reviews
    assert loaded.resolved[0].team_id_master == "resolved-later"


@pytest.mark.parametrize("second_group", ["10", "20"])
def test_disjoint_review_edits_merge_in_both_save_orders(tmp_path, second_group):
    baseline = reviewed_snapshot()
    first = edit_review(baseline, notes="Only first place advances")
    second = edit_review(baseline, group_id=second_group, source_url="https://example.test/revised-rules")

    for index, order in enumerate(((first, second), (second, first))):
        directory = tmp_path / str(index)
        state.write_snapshot(EVENT_KEY, baseline, base_dir=directory)
        for snapshot in order:
            state.write_snapshot(EVENT_KEY, snapshot, base_dir=directory, review_baseline=baseline.reviews)

        reviews = saved_reviews(directory)
        assert reviews["10"].notes == "Only first place advances"
        assert reviews[second_group].source_url == "https://example.test/revised-rules"
        assert reviews["10"].checked is True
        assert reviews["20"].notes == "Three-team round robin"


@pytest.mark.parametrize("field,value", [("notes", ""), ("source_url", ""), ("checked", False)])
def test_explicit_clear_or_uncheck_merges_without_reverting_other_division(tmp_path, field, value):
    baseline = reviewed_snapshot()
    state.write_snapshot(EVENT_KEY, baseline, base_dir=tmp_path)
    other_session = edit_review(baseline, group_id="20", notes="Winner determined by points")
    state.write_snapshot(EVENT_KEY, other_session, base_dir=tmp_path, review_baseline=baseline.reviews)
    cleared = edit_review(baseline, **{field: value})

    state.write_snapshot(EVENT_KEY, cleared, base_dir=tmp_path, review_baseline=baseline.reviews)

    reviews = saved_reviews(tmp_path)
    assert getattr(reviews["10"], field) == value
    assert reviews["20"].notes == "Winner determined by points"
    for other_field in {"notes", "source_url", "checked"} - {field}:
        assert getattr(reviews["10"], other_field) == getattr(baseline.reviews[0], other_field)


@pytest.mark.parametrize("field,values", [
    ("notes", ("Winner advances", "Top two advance")),
    ("source_url", ("https://example.test/rules/a", "https://example.test/rules/b")),
])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_conflicting_field_edits_are_refused_atomically(tmp_path, field, values, reverse_order):
    baseline = reviewed_snapshot()
    path = state.write_snapshot(EVENT_KEY, baseline, base_dir=tmp_path)
    first_value, second_value = reversed(values) if reverse_order else values
    first = edit_review(baseline, **{field: first_value})
    second = edit_review(baseline, **{field: second_value})
    # Include an independent pending edit to prove a conflict writes none of it.
    second = edit_review(second, group_id="20", notes="Must not be partially saved")
    state.write_snapshot(EVENT_KEY, first, base_dir=tmp_path, review_baseline=baseline.reviews)
    before = path.read_bytes()

    with pytest.raises(state.ReviewConflict):
        state.write_snapshot(EVENT_KEY, second, base_dir=tmp_path, review_baseline=baseline.reviews)

    assert path.read_bytes() == before
    assert getattr(saved_reviews(tmp_path)["10"], field) == first_value
    assert saved_reviews(tmp_path)["20"].notes == "Three-team round robin"


@pytest.mark.parametrize("field,value", [
    ("notes", "Agreed rules"), ("source_url", "https://example.test/final-rules"), ("checked", False),
])
def test_identical_concurrent_edits_are_not_false_conflicts(tmp_path, field, value):
    baseline = reviewed_snapshot()
    state.write_snapshot(EVENT_KEY, baseline, base_dir=tmp_path)
    desired = edit_review(baseline, **{field: value})

    for _ in range(2):
        state.write_snapshot(EVENT_KEY, desired, base_dir=tmp_path, review_baseline=baseline.reviews)

    assert getattr(saved_reviews(tmp_path)["10"], field) == value


@pytest.mark.parametrize("field,value", [
    ("notes", "Different rules with no captured baseline"),
    ("source_url", "https://example.test/unbased-rules"),
])
def test_nonempty_conflicting_edits_require_an_explicit_baseline(tmp_path, field, value):
    original = reviewed_snapshot()
    path = state.write_snapshot(EVENT_KEY, original, base_dir=tmp_path)
    before = path.read_bytes()

    with pytest.raises(state.ReviewConflict):
        state.write_snapshot(EVENT_KEY, edit_review(original, **{field: value}), base_dir=tmp_path)

    assert path.read_bytes() == before


def test_new_structure_keeps_notes_and_sources_but_invalidates_only_changed_division(tmp_path):
    original = reviewed_snapshot()
    state.write_snapshot(EVENT_KEY, original, base_dir=tmp_path)
    refreshed = changed_structure(original)
    expected_hash = state.structure_hash(refreshed.roster.divisions[0])
    assert expected_hash != original.reviews[0].structure_hash

    aligned = {review.group_id: review for review in state.reviews_for_capture(refreshed.roster, original.reviews)}
    state.write_snapshot(EVENT_KEY, refreshed, base_dir=tmp_path)

    reviews = saved_reviews(tmp_path)
    assert reviews == aligned
    assert reviews["10"].notes == "Top two advance; final goes to penalties"
    assert reviews["10"].source_url == "https://example.test/rules/gold"
    assert reviews["10"].structure_hash == expected_hash
    assert reviews["10"].checked is False
    assert reviews["20"] == original.reviews[1]


def test_old_structure_check_cannot_verify_a_new_capture_and_new_review_can(tmp_path):
    original = reviewed_snapshot()
    state.write_snapshot(EVENT_KEY, original, base_dir=tmp_path)
    refreshed = replace(changed_structure(original), reviews=original.reviews)

    state.write_snapshot(EVENT_KEY, refreshed, base_dir=tmp_path, review_baseline=original.reviews)

    loaded = state.read_snapshot(EVENT_KEY, base_dir=tmp_path)
    assert saved_reviews(tmp_path)["10"].checked is False
    explicitly_rechecked = edit_review(loaded, checked=True)
    state.write_snapshot(EVENT_KEY, explicitly_rechecked, base_dir=tmp_path, review_baseline=loaded.reviews)
    assert saved_reviews(tmp_path)["10"].checked is True
    assert saved_reviews(tmp_path)["10"].structure_hash == state.structure_hash(refreshed.roster.divisions[0])


def test_latest_reviews_are_read_and_merged_inside_snapshot_lock(tmp_path, monkeypatch):
    baseline = reviewed_snapshot()
    path = state.write_snapshot(EVENT_KEY, baseline, base_dir=tmp_path)
    pending = edit_review(baseline, source_url="https://example.test/new-source")
    concurrent = edit_review(baseline, notes="Changed while waiting for lock")
    original_write = state.write_json
    locked = False

    @contextmanager
    def competing_save_then_lock(lock_path, **kwargs):
        nonlocal locked
        assert lock_path == path.with_suffix(".lock")
        original_write(path, concurrent.to_dict())
        locked = True
        try:
            yield
        finally:
            locked = False

    def require_locked_write(output_path, payload):
        assert locked, "The merged snapshot must be written before releasing its lock"
        original_write(output_path, payload)

    monkeypatch.setattr(state, "_acquire_file_lock", competing_save_then_lock)
    monkeypatch.setattr(state, "write_json", require_locked_write)
    state.write_snapshot(EVENT_KEY, pending, base_dir=tmp_path, review_baseline=baseline.reviews)

    reviews = saved_reviews(tmp_path)
    assert reviews["10"].notes == "Changed while waiting for lock"
    assert reviews["10"].source_url == "https://example.test/new-source"


def test_dry_run_review_edit_preserves_existing_file(tmp_path):
    original = reviewed_snapshot()
    path = state.write_snapshot(EVENT_KEY, original, base_dir=tmp_path)
    before = path.read_bytes()

    result = state.write_snapshot(EVENT_KEY, edit_review(original, notes="Dry run only"),
                                  base_dir=tmp_path, review_baseline=original.reviews, dry_run=True)

    assert result == path
    assert path.read_bytes() == before
