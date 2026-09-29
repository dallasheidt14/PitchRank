"""Diagnostic MatchBalance CSV exports are safe to open in spreadsheets."""

import ast
import csv
import importlib
from pathlib import Path
from typing import Callable

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_EXPECTED_WRITER_IDS = {
    "scripts.analyze_matchbalance_flight_plans._write_csv",
    "scripts.analyze_matchbalance_groups._write_csv",
    "scripts.suggest_matchbalance_flights._write_csv",
}


def _discover_matchbalance_csv_writers() -> tuple[
    tuple[str, Callable[..., None]], ...
]:
    writers = []
    for path in sorted(_SCRIPTS_DIR.glob("*matchbalance*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_write_csv"
            for node in tree.body
        ):
            continue
        module_name = f"scripts.{path.stem}"
        module = importlib.import_module(module_name)
        writers.append(
            (f"{module_name}._write_csv", getattr(module, "_write_csv"))
        )
    return tuple(writers)


_WRITERS = _discover_matchbalance_csv_writers()


def test_matchbalance_csv_writer_corpus_is_discovered_from_the_repository():
    assert {writer_id for writer_id, _writer in _WRITERS} == _EXPECTED_WRITER_IDS


@pytest.mark.parametrize(
    ("writer_id", "writer"),
    _WRITERS,
    ids=[writer_id for writer_id, _writer in _WRITERS],
)
def test_every_string_cell_is_defanged_before_csv_export(
    tmp_path, writer_id, writer
):
    assert writer_id in _EXPECTED_WRITER_IDS
    path = tmp_path / "diagnostic.csv"
    dangerous = {
        "equals": '=HYPERLINK("https://example.invalid")',
        "plus": "+1+1",
        "minus": "-1+1",
        "at": "@SUM(1,1)",
        "tab": "\t=1+1",
        "carriage_return": "\r=1+1",
        "newline": "\n=1+1",
    }
    writer(
        path,
        [
            {
                "safe": "Ordinary team",
                "number": 12,
                **dangerous,
            }
        ],
    )

    with path.open(encoding="utf-8-sig", newline="") as handle:
        exported = next(csv.DictReader(handle))

    assert exported["safe"] == "Ordinary team"
    assert exported["number"] == "12"
    for key, value in dangerous.items():
        assert exported[key] == "'" + value
