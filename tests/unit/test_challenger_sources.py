from pathlib import Path

from src.predictions import challenger_sources as sources


def test_dependency_binding_follows_expectation_helpers_and_ignores_erased_type_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "pinned_source_identity", lambda: {"source_hashes": {"matchPredictor.ts": "a"}})
    files = {
        "src/predictions/form_research.py": "from src.predictions.expectations import expected\n",
        "src/predictions/form_archive_sources.py": "from src.predictions.archive_inputs import read\n",
        "src/predictions/expectations.py": "from .expectation_rules import calculate\n",
        "src/predictions/expectation_rules.py": "calculate = 1\n",
        "src/predictions/archive_inputs.py": "from src.utils.frozen import read\n",
        "scripts/benchmark_compare_form.py": (
            "from src.predictions.form_research import run\n"
            "def main():\n    from src.predictions.cli_only import unused\n"
        ),
        "src/utils/frozen.py": "read = 1\n",
        "frontend/lib/matchPredictor.ts": "import {margin} from './expectations';\n",
        "frontend/lib/expectations.ts": "import {rule} from './rule';\n",
        "frontend/lib/rule.ts": "export const rule = 1;\n",
        "frontend/scripts/run-form-research.ts": "import type {Game} from './does-not-execute';\n",
        "frontend/scripts/verify-compare-source.ts": "import {verify} from '../lib/verify-inputs';\n",
        "frontend/lib/verify-inputs.ts": "export const verify = true;\n",
        "requirements.lock": "numpy==2.2.6\n", "frontend/package-lock.json": "{}",
        **{"frontend/public/data/calibration/" + name: "{}" for name in sources.CALIBRATION_SNAPSHOT_FILES.values()},
    }
    for name, contents in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    actual = sources.candidate_execution_paths(tmp_path)
    assert actual == set(files)


def test_real_execution_graph_includes_archive_expectations_and_verification():
    paths = sources.candidate_execution_paths(Path(__file__).resolve().parents[2])
    assert {"src/predictions/form_archive_sources.py", "src/predictions/archive_inputs.py",
            "src/rankings/archive_storage.py", "frontend/scripts/verify-compare-source.ts"} <= paths
    assert "src/predictions/challenger_capture.py" not in paths
