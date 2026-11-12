"""Register a separate form study through the append-only private archive index."""

from __future__ import annotations

import gzip
import hashlib
import io
import subprocess
import tarfile
from functools import lru_cache
from pathlib import Path

from src.predictions.form_study_contract import FORM_STUDY_KIND, study_definition
from src.rankings.input_archive import InputArchive, source_file_names, utc_now


def is_research_source(name: str) -> bool:
    return ((name.startswith("src/predictions/") and name.endswith(".py"))
            or (name.startswith("frontend/lib/") and name.endswith((".ts", ".tsx")))
            or name in {"scripts/benchmark_compare_form.py", "scripts/register_compare_form_study.py",
                        "scripts/assemble_compare_form_dataset.py",
                        "frontend/scripts/run-form-research.ts", "frontend/scripts/verify-compare-source.ts"})


def research_hashes(entries) -> dict[str, str]:
    return {name: hashlib.sha256(raw.decode("utf-8").replace("\r\n", "\n").encode()).hexdigest()
            for name, raw in entries if is_research_source(name)}


def archived_research_hashes(directory: Path, manifest: dict) -> dict[str, str]:
    return research_hashes(
        (name, gzip.decompress((directory / ref["object"]).read_bytes()))
        for name, ref in manifest["source_files"].items() if is_research_source(name)
    )


@lru_cache(maxsize=8)
def committed_research_sources(source_root: Path, revision: str) -> tuple:
    paths = ["src/predictions/", "frontend/lib/", "scripts/benchmark_compare_form.py",
             "scripts/assemble_compare_form_dataset.py",
             "scripts/register_compare_form_study.py", "frontend/scripts/run-form-research.ts",
             "frontend/scripts/verify-compare-source.ts"]
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "-z", revision, "--", *paths], cwd=source_root, timeout=30
    )
    expected = {name.decode() for name in names.split(b"\0") if name and is_research_source(name.decode())}
    if not expected:
        raise ValueError("Registered revision has no research sources")
    raw = subprocess.check_output(["git", "archive", "--format=tar", revision, "--", *sorted(expected)],
                                  cwd=source_root, timeout=30)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        entries = tuple((member.name, archive.extractfile(member).read()) for member in archive.getmembers()
                        if member.isfile() and is_research_source(member.name))
    if not expected or {name for name, _ in entries} != expected:
        raise ValueError("Registered revision does not supply its complete research sources")
    return entries


def validate_study_sources(directory: Path, manifest: dict):
    sources = archived_research_hashes(directory, manifest)
    if manifest["configuration"]["study_definition"]["research_sources"] != sources:
        raise ValueError("Study definition is not bound to its complete research source archive")
    root = Path(__file__).resolve().parents[2]
    if sources != research_hashes(committed_research_sources(root, manifest["source_revision"])):
        raise ValueError("Study sources do not match the complete registered Git revision")


def register_form_study(client, source_root: Path, output: Path | None = None, *, dry_run: bool = True) -> dict:
    if dry_run:
        sources = research_hashes((name, (source_root / name).read_bytes()) for name in source_file_names(source_root))
        return {"dry_run": True, "registered": False, "definition": study_definition(utc_now(), sources)}
    if output is None:
        raise ValueError("Study registration requires a new local output directory")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source_root, text=True).strip():
        raise ValueError("Register the reviewed study from a clean committed checkout")
    from src.rankings.archive_storage import publish_archive

    archive = InputArchive(output, source_root, {"capture_kind": FORM_STUDY_KIND})
    definition = study_definition(archive.manifest["started_at"], archived_research_hashes(output, archive.manifest))
    archive.manifest["configuration"]["study_definition"] = definition
    archive.finish(True)
    result = publish_archive(client, output, dry_run=False)
    return {**result, "definition": definition, "production_promotion": False}
