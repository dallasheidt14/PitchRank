"""PDF worker contracts; actual rendering is verified with the artifact QA run."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.tournaments import seeding_pdf


def test_empty_sheet_fails_before_starting_a_process():
    with pytest.raises(seeding_pdf.SeedingPdfError, match="Build the seeding sheet"):
        seeding_pdf.render_seeding_pdf(" ")


def test_missing_node_explains_how_to_enable_pdf_export(monkeypatch):
    monkeypatch.setattr(seeding_pdf.shutil, "which", lambda _: None)
    with pytest.raises(seeding_pdf.SeedingPdfError, match="Node.js on PATH"):
        seeding_pdf.render_seeding_pdf("<html>Sheet</html>")


def test_worker_gets_exact_document_without_a_shell_and_temp_files_are_removed(monkeypatch):
    monkeypatch.setattr(seeding_pdf.shutil, "which", lambda _: "node")
    seen = []

    def run(args, **kwargs):
        seen.extend([Path(args[2]), Path(args[3])])
        assert Path(args[2]).read_text(encoding="utf-8") == "<html>Exact & approved</html>"
        assert args[:1] == ["node"]
        assert Path(args[1]).name == "render-seeding-pdf.mjs"
        assert kwargs.get("shell", False) is False
        assert kwargs["timeout"] == 90
        assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
        Path(args[3]).write_bytes(b"%PDF-1.7\nfake body for worker contract\n%%EOF\n")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(seeding_pdf.subprocess, "run", run)
    result = seeding_pdf.render_seeding_pdf("<html>Exact & approved</html>")
    assert result == b"%PDF-1.7\nfake body for worker contract\n%%EOF\n"
    assert len(seen) == 2
    assert all(not path.exists() for path in seen)


@pytest.mark.parametrize("failure", ["process", "timeout", "permission", "missing", "invalid"])
def test_failed_pdf_export_never_returns_html_or_an_empty_file(monkeypatch, failure):
    monkeypatch.setattr(seeding_pdf.shutil, "which", lambda _: "node")

    def run(args, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 90)
        if failure == "permission":
            raise PermissionError("blocked process")
        if failure == "invalid":
            Path(args[3]).write_bytes(b"<html>This is not a PDF</html>")
        return SimpleNamespace(returncode=1 if failure == "process" else 0,
                               stderr="Install Chromium", stdout="")

    monkeypatch.setattr(seeding_pdf.subprocess, "run", run)
    with pytest.raises(seeding_pdf.SeedingPdfError):
        seeding_pdf.render_seeding_pdf("<html>Sheet</html>")
