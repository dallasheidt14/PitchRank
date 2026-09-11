"""The app's page chrome must render once, not once per import of the file."""

from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path("tournament_intake.py")

CHROME = ("set_page_config", "title", "caption")


def _streamlit_calls_at_module_level(tree: ast.Module) -> list[str]:
    found = []
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "st" and func.attr in CHROME:
                found.append(func.attr)
    return found


def test_page_chrome_is_not_drawn_on_a_plain_import():
    """`backtest_event_intake` imports this file by name while Streamlit runs it
    as `__main__`, so Python executes it twice. Anything drawn at module level
    is drawn twice — the title and caption appeared again mid-page."""
    tree = ast.parse(APP.read_text(encoding="utf-8"))

    assert _streamlit_calls_at_module_level(tree) == [], (
        "guard these behind `if __name__ == \"__main__\":` — an import of this "
        "file must not draw anything"
    )
