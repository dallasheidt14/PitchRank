"""
Verify get_pending_requests orders by priority then requested_at, no longer
filters by request_type='missing_game', and defaults to limit=200.
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest.mock import Mock, call
from scripts.process_missing_games import MissingGamesProcessor


def _build_mock_supabase():
    """Return a supabase mock whose query chain ends in .execute() -> .data = []"""
    supabase = Mock()
    chain = supabase.table.return_value.select.return_value.eq.return_value
    # chained .order() returns the same object so further calls keep working
    chain.order.return_value = chain
    chain.limit.return_value.execute.return_value.data = []
    return supabase, chain


def test_get_pending_requests_orders_by_priority_then_requested_at():
    supabase, chain = _build_mock_supabase()

    p = MissingGamesProcessor(supabase, dry_run=True)
    p.get_pending_requests(limit=200)

    order_calls = chain.order.call_args_list
    assert len(order_calls) >= 2, f"Expected >=2 order() calls, got {len(order_calls)}: {order_calls}"

    # First order call: priority ASC
    first_args, first_kwargs = order_calls[0]
    assert first_args[0] == "priority", f"First order column should be 'priority', got {first_args[0]!r}"
    assert first_kwargs.get("desc") is False, f"priority should be desc=False, got {first_kwargs}"

    # Second order call: requested_at ASC
    second_args, second_kwargs = order_calls[1]
    assert second_args[0] == "requested_at", (
        f"Second order column should be 'requested_at', got {second_args[0]!r}"
    )
    assert second_kwargs.get("desc") is False, f"requested_at should be desc=False, got {second_kwargs}"


def test_get_pending_requests_does_not_filter_by_request_type():
    """All request_types should be processed by the queue, not just 'missing_game'."""
    supabase, chain = _build_mock_supabase()

    p = MissingGamesProcessor(supabase, dry_run=True)
    p.get_pending_requests(limit=200)

    # Collect all .eq() calls on the select() result and any chained objects
    select_result = supabase.table.return_value.select.return_value
    eq_calls = select_result.eq.call_args_list

    # Flatten into a list of (col, val) pairs
    eq_pairs = [(c.args[0] if c.args else None, c.args[1] if len(c.args) > 1 else None) for c in eq_calls]

    # status='pending' must be present
    assert any(col == "status" and val == "pending" for col, val in eq_pairs), (
        f"Expected .eq('status', 'pending') call; got {eq_pairs}"
    )

    # request_type must NOT appear in any .eq() call
    assert not any(col == "request_type" for col, val in eq_pairs), (
        f"request_type filter should have been removed; got {eq_pairs}"
    )


def test_get_pending_requests_default_limit_is_40():
    """The method signature default should be 40 (lowered in PR #838)."""
    import inspect

    sig = inspect.signature(MissingGamesProcessor.get_pending_requests)
    default_limit = sig.parameters["limit"].default
    assert default_limit == 40, f"Default limit should be 40, got {default_limit}"
