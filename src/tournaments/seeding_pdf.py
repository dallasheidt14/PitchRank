"""Export the same reviewed seeding HTML to a real, searchable Letter PDF."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

__all__ = ["SeedingPdfError", "render_seeding_pdf"]


class SeedingPdfError(RuntimeError):
    """PDF rendering failed; the operator can still use the printable HTML."""


def render_seeding_pdf(document: str) -> bytes:
    """Render a self-contained HTML document without opening a visible browser.

    Uses the frontend's existing Playwright dependency and installed Chromium,
    Edge or Chrome. No server, credentials, remote page, or application deployment
    is involved. A failed renderer never returns HTML under a PDF filename.
    """
    if not isinstance(document, str) or not document.strip():
        raise SeedingPdfError("Build the seeding sheet before exporting its PDF.")
    node = shutil.which("node")
    if node is None:
        raise SeedingPdfError("PDF export needs Node.js on PATH. Install Node.js, then restart Seeding Intake.")
    script = Path(__file__).resolve().parents[2] / "frontend" / "scripts" / "render-seeding-pdf.mjs"
    if not script.is_file():
        raise SeedingPdfError("The PDF renderer is missing. Update this checkout and try again.")

    with tempfile.TemporaryDirectory(prefix="matchbalance-pdf-") as temporary:
        input_path = Path(temporary) / "sheet.html"
        output_path = Path(temporary) / "sheet.pdf"
        input_path.write_text(document, encoding="utf-8")
        try:
            result = subprocess.run(
                [node, str(script), str(input_path), str(output_path)],
                cwd=str(script.parent.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise SeedingPdfError(
                "PDF export timed out. Try a smaller cohort pack or restart the application."
            ) from exc
        except OSError as exc:
            raise SeedingPdfError(
                "Could not start the PDF renderer. Check Node.js and local process permissions."
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Unknown renderer error").strip()[-1400:]
            raise SeedingPdfError(f"PDF export failed: {detail}")
        try:
            pdf = output_path.read_bytes()
        except OSError as exc:
            raise SeedingPdfError("PDF export produced no file. Rebuild the sheet and try again.") from exc
        if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-1024:]:
            raise SeedingPdfError("The renderer produced an invalid PDF. Rebuild the sheet and try again.")
        return pdf
