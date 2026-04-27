"""Integration smoke for the cohort CLI's PHASE marker emission.

Shell 06 patches ``scripts/backtest_tournament_cohort.py`` to print
``PHASE: <name>`` lines on stdout so the orchestrator's Popen stream loop
can drive the Streamlit ``st.status`` UI. The full CLI requires a real
Supabase client to land on the snapshot path; this smoke just asserts the
help string still resolves so a typo in the patches doesn't break ``--help``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_cohort_cli_help_runs_clean():
    result = subprocess.run(
        [sys.executable, "scripts/backtest_tournament_cohort.py", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--input" in result.stdout
    assert "--output-dir" in result.stdout
