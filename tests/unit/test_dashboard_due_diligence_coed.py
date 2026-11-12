"""The Due Diligence Review must not let a reviewer approve a record GotSport files as Coed.

The weekly gate holds such a record as gender_check "coed" (PitchRank does not rank coed teams), and
"✅ Approve & Link" is the only control on that page that writes an alias and links the record's
games. dashboard.py is a Streamlit script that cannot be imported, so the scan is scoped to the
section's block.
"""

import re
from pathlib import Path


def _due_diligence_block() -> str:
    source = (Path(__file__).resolve().parents[2] / "dashboard.py").read_text(encoding="utf-8")
    start = source.index('elif section == "🛡️ Due Diligence Review":')
    end = source.index("\nelif section ==", start + 1)
    return source[start:end]


def _approve_button_call() -> str:
    block = _due_diligence_block()
    start = block.index('"✅ Approve & Link"')
    return block[start : block.index("):", start)]


def test_approve_is_disabled_for_a_coed_record():
    disabled = re.search(r"disabled=(.+)", _approve_button_call())
    assert disabled is not None
    assert re.search(r"""row\.get\(["']gender_check["'].*==\s*["']coed["']""", disabled.group(1))


def test_a_coed_record_is_shown_as_a_failure():
    block = _due_diligence_block()

    assert re.search(r"""if v == "coed":\s*return "🔴 Coed\"""", block)
    assert '.isin(["mismatch", "unknown", "coed"])' in block
