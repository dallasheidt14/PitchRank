"""Every new TGS team is decided in one job, after every shard has scraped and before any imports.

Decided shard by shard, two shards could each link a different new TGS id to the same team, and
separating the games they then import onto it takes a manual split by provider id.
"""

import fnmatch
import re
from pathlib import Path

import pytest

from tests.unit.test_tgs_workflow_chain import _bash_sees_the_callers_environment, _outputs, _run, _step, _workflow

# What each expression the CSV hand-off names would read in shard 4 of run 7.
FILLED = {
    "steps.range.outputs.shard_start": "3400",
    "steps.range.outputs.shard_end": "3429",
    "github.run_number": "7",
    "matrix.shard": "4",
}
needs_bash = pytest.mark.skipif(
    not _bash_sees_the_callers_environment(), reason="needs a bash that sees the caller's environment"
)


def _jobs():
    return _workflow()["jobs"]


def _jobs_running(script):
    return [name for name, job in _jobs().items() if any(script in (step.get("run") or "") for step in job["steps"])]


def _fill(text, **values):
    values = {**FILLED, **values}
    return re.sub(r"\$\{\{\s*([\w.]+)\s*\}\}", lambda expression: values[expression.group(1)], text)


def test_teams_are_matched_in_one_job_that_is_not_split_into_shards():
    assert _jobs_running("extract_and_import_tgs_teams.py") == ["match-teams"]
    assert "strategy" not in _jobs()["match-teams"]


def test_matching_waits_for_every_scrape_shard_and_every_import_waits_for_it():
    jobs = _jobs()

    assert _jobs_running("scrape_tgs_event.py") == ["scrape"]
    assert _jobs_running("import_games_enhanced.py") == ["import"]
    assert "scrape" in jobs["match-teams"]["needs"]
    assert "match-teams" in jobs["import"]["needs"]


def test_the_match_and_import_jobs_run_on_exactly_these_conditions():
    """A cancelled run neither matches nor imports. The import waits for matching and runs whether it
    succeeded or failed: a failed match leaves the run red, not the week's other games unimported."""
    jobs = _jobs()

    assert jobs["match-teams"]["if"] == "${{ !cancelled() && needs.prepare.result == 'success' }}"
    assert jobs["import"]["if"] == (
        "${{ !cancelled() && needs.prepare.result == 'success' "
        "&& (needs.match-teams.result == 'success' || needs.match-teams.result == 'failure') }}"
    )
    assert _step("match-teams", "Match or create TGS teams")["if"] == (
        "${{ needs.prepare.outputs.skip_import != 'true' && env.AGE_ROLLOVER_FREEZE == 'false' }}"
    )


def _place_shard_csvs(tmp_path):
    """Lay out each job's downloaded CSVs as the artifact actions would, and return their names."""
    upload = _step("scrape", "Upload scraped data")["with"]
    names = [
        Path(_fill(upload["path"], **shard)).name.replace("*", "20261116_063000")
        for shard in ({}, {"steps.range.outputs.shard_start": "3430", "steps.range.outputs.shard_end": "3459"})
    ]
    for job, step in (("match-teams", "Download scraped data"), ("import", "Download this shard's scraped data")):
        folder = tmp_path / job / _step(job, step)["with"]["path"]
        folder.mkdir(parents=True)
        for name in names if job == "match-teams" else names[:1]:
            (folder / name).write_text("game_date\n2026-09-12\n", newline="\n")
    return names


@needs_bash
def test_every_shards_csv_reaches_the_match_step_and_only_its_own_import_shard(tmp_path):
    """A CSV the match step misses imports games whose new teams were never decided."""
    upload = _step("scrape", "Upload scraped data")["with"]
    match_download = _step("match-teams", "Download scraped data")["with"]
    import_download = _step("import", "Download this shard's scraped data")["with"]

    artifact = _fill(upload["name"])
    assert fnmatch.fnmatchcase(artifact, _fill(match_download["pattern"]))
    assert fnmatch.fnmatchcase(artifact, _fill(import_download["pattern"]))
    assert not fnmatch.fnmatchcase(artifact, _fill(import_download["pattern"], **{"matrix.shard": "3"}))
    assert match_download["merge-multiple"] is True and import_download["merge-multiple"] is True

    # A one-file artifact holds just the file, and merge-multiple unpacks it straight into `path`.
    names = _place_shard_csvs(tmp_path)

    match = _run(_step("match-teams", "Match or create TGS teams")["run"], {}, tmp_path / "match-teams", ("python",))
    assert match.returncode == 0, match.stdout + match.stderr
    calls = [line for line in match.stdout.splitlines() if line.startswith(("python ", "gh "))]
    shard_csvs = " ".join(f"{match_download['path']}/{name}" for name in sorted(names))
    assert calls == [f"python scripts/extract_and_import_tgs_teams.py {shard_csvs} tgs"]

    output = tmp_path / "import" / "find-csv-output"
    find = _run(_step("import", "Find scraped CSV file")["run"], {"GITHUB_OUTPUT": str(output)}, tmp_path / "import")
    assert find.returncode == 0, find.stdout + find.stderr
    found = _outputs(output)
    assert (found["csv_file"], found["has_games"]) == (f"{import_download['path']}/{names[0]}", "true")


@needs_bash
def test_a_failing_match_script_fails_the_match_step(tmp_path):
    """The script's exit status is the run's only red signal for a team it could not decide."""
    _place_shard_csvs(tmp_path)
    failing_python = 'python() { printf "python %s\\n" "$*"; return 1; }\n'
    script = failing_python + _step("match-teams", "Match or create TGS teams")["run"]

    match = _run(script, {}, tmp_path / "match-teams", ("python",))

    assert match.returncode != 0
    assert any(line.startswith("python scripts/extract_and_import_tgs_teams.py ") for line in match.stdout.splitlines())
