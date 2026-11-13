"""Execute registration in an owned Git repository, with storage/index writes recorded locally."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.predictions.form_study import is_research_source
from src.rankings.input_archive import source_file_names

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def registration_repo(tmp_path):
    root = tmp_path / "study-source"
    root.mkdir()
    paths = {name for name in source_file_names(ROOT) if is_research_source(name)}
    paths.update({"src/rankings/input_archive.py", "src/rankings/archive_storage.py"})
    for name in paths:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    # Package initialization is outside the registration composition under test.
    for name in ("src/__init__.py", "src/rankings/__init__.py"):
        (root / name).write_text("", encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n_norton_/\n", encoding="utf-8")
    commands = [
        ["git", "init", "--quiet"], ["git", "config", "core.autocrlf", "false"],
        ["git", "add", "--", ".gitignore", *sorted(paths), "src/__init__.py", "src/rankings/__init__.py"],
        ["git", "-c", "user.name=Research Test", "-c", "user.email=research-test@example.test",
         "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Freeze isolated registration fixture"],
    ]
    for command in commands:
        subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=30)
    return root


@pytest.mark.parametrize("mode", ["valid", "boundary", "generic_boundary", "dirty"])
def test_executing_registration_uses_frozen_sources_and_authoritative_server_time(registration_repo, tmp_path, mode):
    output = tmp_path / "registered-archive"
    if mode == "dirty":
        with (registration_repo / "src/predictions/form_policy.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# Deliberate uncommitted test input\n")
    driver = tmp_path / "registration-driver.py"
    driver.write_text(
        "import json,os,runpy,sys\nfrom pathlib import Path\nsys.path.insert(0,os.getcwd())\n"
        "from src.predictions.form_study import register_form_study\n"
        "from src.rankings import input_archive\n"
        "from src.rankings.archive_storage import publish_archive\n"
        "mode=sys.argv[1]; output=Path(sys.argv[2])\n"
        "FakeServer=runpy.run_path(sys.argv[3])['FakeServer']\n"
        "before='2026-11-15T23:59:59Z' if 'boundary' in mode else '2026-11-12T00:00:00Z'\n"
        "after='2026-11-16T00:00:01Z' if 'boundary' in mode else '2026-11-12T00:00:01Z'\n"
        "input_archive.utc_now=lambda:before\nserver=FakeServer(recorded_at=after)\n"
        "try:\n"
        " if mode=='generic_boundary':\n"
        "  early=FakeServer(recorded_at=before)\n"
        "  register_form_study(early,Path.cwd(),output,dry_run=False)\n"
        "  result=publish_archive(server,output,dry_run=False)\n"
        " else: result=register_form_study(server,Path.cwd(),output,dry_run=False)\n"
        " print(json.dumps({'result':result,'rows':len(server.rows),'calls':len(server.calls)}))\n"
        "except ValueError as error:\n"
        " print(json.dumps({'error':str(error),'rows':len(server.rows),'calls':len(server.calls),"
        "'output_exists':output.exists()}))\n",
        encoding="utf-8",
    )
    run = subprocess.run(
        [sys.executable, str(driver), mode, str(output), str(ROOT / "tests/unit/test_ranking_archive_storage.py")],
        cwd=registration_repo, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    if mode == "dirty":
        assert report["error"] == "Register the reviewed study from a clean committed checkout"
        assert report["rows"] == report["calls"] == 0 and not report["output_exists"]
    elif "boundary" in mode:
        assert report["error"] == "Study definition differs from the fixed prospective policy"
        assert report["rows"] == 1 and report["output_exists"]
    else:
        assert report["rows"] == 1 and report["calls"] > 0
        result = report["result"]
        assert result["registered"] and not result["production_promotion"]
        assert result["recorded_at"] == "2026-11-12T00:00:01Z"
        assert result["definition"]["policy"]["development_start"] == "2026-11-16"
        assert result["definition"]["policy"]["evaluation_end"] == "2027-01-10"
        assert result["definition"]["require_authoritative_inputs"] is True
        assert result["definition"]["policy"]["minimum_games"] == 1000
        manifest = json.loads((output / "manifest.json").read_text())
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=registration_repo, text=True).strip()
        assert manifest["source_revision"] == revision and manifest["status"] == "complete"
        assert "src/predictions/form_policy.py" in result["definition"]["research_sources"]
