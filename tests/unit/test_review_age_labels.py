"""Which folders the age review loads database credentials from."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".claude/skills/correcting-team-age-groups/scripts/review_age_labels.py"
_spec = importlib.util.spec_from_file_location("review_age_labels", SCRIPT)
ral = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ral)


def test_a_worktree_pointed_at_a_checkout_s_exports_also_reads_that_checkout_s_credentials(tmp_path):
    checkout = tmp_path / "PitchRank"
    (checkout / ".git").mkdir(parents=True)
    exports = checkout / "data" / "exports"
    exports.mkdir(parents=True)

    assert ral.credential_roots(exports) == [ral.REPO, checkout]


def test_a_run_store_outside_any_checkout_adds_no_credentials(tmp_path):
    home = tmp_path / "home"
    exports = home / "pitchrank-cleanup-runs" / "exports"
    exports.mkdir(parents=True)
    (home / ".env.local").write_text("SUPABASE_URL=http://elsewhere.invalid\n", encoding="utf-8")

    assert ral.credential_roots(exports) == [ral.REPO]


def test_a_data_exports_folder_that_is_not_in_a_checkout_adds_no_credentials(tmp_path):
    exports = tmp_path / "somewhere" / "data" / "exports"
    exports.mkdir(parents=True)

    assert ral.credential_roots(exports) == [ral.REPO]
