"""The weekly TGS chain walks every event id from seed link to final link, and alarms once the final link has games.

The chain is a bash `case` in the finalize job's "Dispatch next chain link" step, and its final
link is the ceiling: events above it get scraped only by a manual run. A gap or a duplicate label
leaves a range unscraped while every run stays green. These run the workflow's own step scripts
with a recording `gh` in place of the real CLI, which would dispatch a production scrape.
"""

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "tgs-event-scrape-import.yml"
BASH = shutil.which("bash")
CHAIN = [
    (3400, 3550),
    (3551, 3700),
    (3701, 3850),
    (3851, 4000),
    (4001, 4150),
    (4151, 4300),
    (4301, 4600),
    (4601, 4900),
]
REF = "chain-test-branch"
DISPATCH = re.compile(
    rf"gh workflow run tgs-event-scrape-import\.yml --ref {REF} "
    r"-f start_event=(\d+) -f end_event=(\d+) -f chain_next=true"
)
RECORD_GH = 'printf "gh %s\\n" "$*"'


def _bash_sees_the_callers_environment():
    """WSL's `bash.exe` launchers drop the caller's environment, so every link would read as unknown."""
    if BASH is None:
        return False
    try:
        probe = subprocess.run(
            [BASH, "-c", 'test "$PROBE" = ok'],
            env={"PATH": os.environ["PATH"], "PROBE": "ok"},
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not _bash_sees_the_callers_environment(), reason="needs a bash that sees the caller's environment"
)


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job, name):
    return next(step for step in _workflow()["jobs"][job]["steps"] if step.get("name") == name)


def _run(script, env, cwd):
    """Run a step's script as Actions runs a step with no `shell:` (`bash -e {0}`), with `gh` recorded.

    The function catches a bare `gh` even if the stub is not executable; the stub, first on PATH,
    catches the spellings that skip shell functions (`command gh`, `timeout 60 gh`).
    """
    stub = cwd / "fake-gh"
    stub.mkdir(exist_ok=True)
    (stub / "gh").write_text(f"#!/bin/sh\n{RECORD_GH}\n", newline="\n")
    (stub / "gh").chmod(0o755)
    return subprocess.run(
        [BASH, "-e", "-c", f"gh() {{ {RECORD_GH}; }}\n{script}"],
        env={"PATH": f"{stub}{os.pathsep}{os.environ['PATH']}", **env},
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _outputs(path):
    """A step's `key=value` GITHUB_OUTPUT lines; as on the runner, a later line for a key replaces an earlier one."""
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def _gate(tmp_path, event_name, start="", end=""):
    """The range the prepare job's gate hands the rest of the run, for one trigger."""
    output = tmp_path / "gate-output"
    output.unlink(missing_ok=True)
    env = {
        **{key: str(value) for key, value in _workflow()["env"].items()},
        "EVENT_NAME": event_name,
        "START_INPUT": start,
        "END_INPUT": end,
        "SKIP_INPUT": "false",
        "GITHUB_OUTPUT": str(output),
    }
    result = _run(_step("prepare", "Compute shard gate")["run"], env, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    gate = _outputs(output)
    return int(gate["start_event"]), int(gate["end_event"])


def _dispatch(link, tmp_path, any_imported):
    env = {
        "CURRENT_START": str(link[0]),
        "CURRENT_END": str(link[1]),
        "ANY_IMPORTED": any_imported,
        "GITHUB_REF_NAME": REF,
    }
    result = _run(_step("finalize", "Dispatch next chain link")["run"], env, tmp_path)
    return result.returncode, result.stdout, [line for line in result.stdout.splitlines() if line.startswith("gh ")]


def _walk(tmp_path, any_imported):
    """The links a week runs: the gate's range for the cron seed, then for each dispatched link."""
    link = _gate(tmp_path, "schedule")
    walked = [link]
    for _ in range(len(CHAIN) + 1):
        code, _, gh_calls = _dispatch(link, tmp_path, any_imported)
        if not gh_calls:
            return walked
        assert code == 0, f"link {link} failed after dispatching"
        assert len(gh_calls) == 1, gh_calls
        dispatch = DISPATCH.fullmatch(gh_calls[0])
        assert dispatch, gh_calls[0]
        link = _gate(tmp_path, "workflow_dispatch", dispatch.group(1), dispatch.group(2))
        walked.append(link)
    pytest.fail(f"the chain never reached a link that stops it: {walked}")


@pytest.mark.parametrize("any_imported", ["true", "false"])
def test_the_chain_runs_from_the_seed_through_every_link_to_the_final_one(tmp_path, any_imported):
    """Every link but the last hands off, with `chain_next`, whether or not its own events had games."""
    walked = _walk(tmp_path, any_imported)
    arms = re.findall(r'^\s*"(\d+)-(\d+)"\)', _step("finalize", "Dispatch next chain link")["run"], re.M)

    assert walked == CHAIN
    assert sorted((int(start), int(end)) for start, end in arms) == walked
    assert all(later[0] == earlier[1] + 1 for earlier, later in zip(walked, walked[1:])), walked


def test_each_link_reads_the_range_its_own_gate_computed():
    """The walk carries each range between steps by hand; these bindings carry it in a real run."""
    gate = _step("prepare", "Compute shard gate")
    prepare_outputs = _workflow()["jobs"]["prepare"]["outputs"]
    dispatch_env = _step("finalize", "Dispatch next chain link")["env"]

    assert gate["id"] == "gate"
    assert (gate["env"]["EVENT_NAME"], gate["env"]["START_INPUT"], gate["env"]["END_INPUT"]) == (
        "${{ github.event_name }}",
        "${{ inputs.start_event }}",
        "${{ inputs.end_event }}",
    )
    assert (prepare_outputs["start_event"], prepare_outputs["end_event"]) == (
        "${{ steps.gate.outputs.start_event }}",
        "${{ steps.gate.outputs.end_event }}",
    )
    assert (dispatch_env["CURRENT_START"], dispatch_env["CURRENT_END"]) == (
        "${{ needs.prepare.outputs.start_event }}",
        "${{ needs.prepare.outputs.end_event }}",
    )


def test_the_dispatch_step_runs_on_the_seed_and_on_every_chained_link():
    """GitHub compares a boolean input to a string as numbers, so `== 'true'` would stop the chain."""
    assert _step("finalize", "Dispatch next chain link")["if"] == (
        "${{ (github.event_name == 'schedule' || inputs.chain_next == true) "
        "&& needs.scrape-and-import.result == 'success' }}"
    )
    # YAML reads the bare `on:` key as True.
    assert _workflow()[True]["workflow_dispatch"]["inputs"]["chain_next"]["type"] == "boolean"


@pytest.mark.parametrize("any_imported, alarms", [("true", True), ("false", False), ("", False)])
def test_the_final_link_fails_the_run_once_its_events_have_games(tmp_path, any_imported, alarms):
    """A red run shows in the Actions run list; a warning shows only inside the run."""
    code, out, gh_calls = _dispatch(CHAIN[-1], tmp_path, any_imported)

    assert gh_calls == []
    assert (code != 0) is alarms
    assert any(line.startswith("::error::") for line in out.splitlines()) is alarms


def test_the_alarm_reads_the_markers_the_importing_shards_upload(tmp_path):
    """A marker that never reaches the folder the check reads leaves the alarm silent and the run green."""
    finalize = [step.get("name") for step in _workflow()["jobs"]["finalize"]["steps"]]
    drop = _step("scrape-and-import", "Drop import marker")
    upload = _step("scrape-and-import", "Upload import marker")["with"]
    download = _step("finalize", "Download import markers")["with"]
    check = _step("finalize", "Check for any imported shard")
    assert _step("finalize", "Dispatch next chain link")["env"]["ANY_IMPORTED"] == (
        "${{ steps.check_imports.outputs.any_imported }}"
    )
    assert check["id"] == "check_imports"
    assert finalize.index(check["name"]) < finalize.index("Dispatch next chain link")
    artifact = upload["name"].replace("${{ github.run_number }}", "7").replace("${{ matrix.shard }}", "4")
    assert fnmatch.fnmatchcase(artifact, download["pattern"].replace("${{ github.run_number }}", "7"))
    assert download["merge-multiple"] is True

    shard = tmp_path / "shard"
    shard.mkdir()
    assert _run(drop["run"], {"TGS_SHARD_INDEX": "4", "GAME_COUNT": "12"}, shard).returncode == 0
    marker = shard / upload["path"].replace("${{ matrix.shard }}", "4")
    assert marker.is_file()
    landed = tmp_path / download["path"]
    landed.mkdir()
    output = tmp_path / "check-output"
    assert _run(check["run"], {"GITHUB_OUTPUT": str(output)}, tmp_path).returncode == 0
    assert _outputs(output)["any_imported"] == "false"

    # A one-file artifact holds just the file, and merge-multiple unpacks it straight into `path`.
    shutil.copy(marker, landed / marker.name)
    output.unlink()
    assert _run(check["run"], {"GITHUB_OUTPUT": str(output)}, tmp_path).returncode == 0
    assert _outputs(output)["any_imported"] == "true"
