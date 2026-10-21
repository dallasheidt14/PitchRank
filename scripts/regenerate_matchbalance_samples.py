"""Regenerate the public MatchBalance sample and workbook design artifacts.

The fixture is deliberately synthetic and frozen. The production HTML, PDF,
analysis, and workbook renderers still own every delivered layout and label.
Run this script on Windows with Excel, Node/Playwright, Poppler, and Pillow installed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import replace
from io import BytesIO
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tournaments.compare_predictor_bridge import ComparePrediction  # noqa: E402
from src.tournaments.seeding_format_library import load_format_library  # noqa: E402
from src.tournaments.seeding_pdf import render_seeding_pdf  # noqa: E402
from src.tournaments.seeding_sheet import CohortSheet, SheetTeam, render_sheet_html  # noqa: E402
from src.tournaments.seeding_tier_guidance import build_tier_guidance  # noqa: E402
from src.tournaments.seeding_tiers import (  # noqa: E402
    DATA_REVIEW,
    NO_CURRENT_RATING,
    NOT_FOUND,
    TierEntrant,
    TierPolicy,
    build_cheat_sheet_analysis,
)
from src.tournaments.seeding_workbook import (  # noqa: E402
    build_seeding_workbook,
    validate_seeding_workbook,
    workbook_sheet_titles,
)

MANIFEST_PATH = ROOT / "scripts" / "matchbalance_sample_manifest.json"
PUBLIC_PDF = ROOT / "frontend" / "public" / "matchbalance" / "sample-u13-boys.pdf"
PUBLIC_PNG = ROOT / "frontend" / "public" / "matchbalance" / "sample-u13-boys.png"
WORKBOOK = ROOT / "docs" / "design" / "matchbalance-excel" / "director-workbook-sample.xlsx"
WORKBOOK_PREVIEWS = {
    "u10-boys": ROOT / "docs" / "design" / "matchbalance-excel" / "u10-boys.png",
    "u12-girls": ROOT / "docs" / "design" / "matchbalance-excel" / "u12-girls.png",
}
OUTPUTS = (PUBLIC_PDF, PUBLIC_PNG, WORKBOOK, *WORKBOOK_PREVIEWS.values())
RENDERER_ENTRY_POINTS = (Path(__file__).relative_to(ROOT),)
RENDERER_ASSETS = (
    Path("scripts/render_matchbalance_workbook_previews.ps1"),
    Path("frontend/scripts/render-seeding-pdf.mjs"),
    Path("frontend/package-lock.json"),
    Path("requirements.lock"),
    Path("config/matchbalance_format_library.json"),
)

SYNTHETIC_FIXTURE: dict[str, Any] = {
    "generated_on": "2026-09-25",
    "ranking_run": "2026-09-22",
    "public_event": "MatchBalance Sample Invitational - Illustrative Data",
    "workbook_event": "MatchBalance Sample Invitational",
    "cohorts": [
        {
            "age_group": "u13",
            "gender": "Male",
            "teams": [
                ["u13-01", "Northstar FC 2013 Navy", "Northstar FC", 0.914, 3, "Texas", "Active"],
                ["u13-02", "Canyon United 2013 Gold", "Canyon United", 0.904, 8, "TX", "Active"],
                ["u13-03", "River City SC 2013 Blue", "River City SC", 0.894, 12, "Texas", "Active"],
                ["u13-04", "Lone Star Athletic 2013", "Lone Star Athletic", 0.884, 17, "TX", "Active"],
                ["u13-05", "Cedar Valley FC 2013", "Cedar Valley FC", 0.874, 22, "Texas", "Active"],
                ["u13-06", "Lakeview United 2013", "Lakeview United", 0.864, 28, "TX", "Active"],
                ["u13-07", "Hill Country FC 2013", "Hill Country FC", 0.714, 51, "Texas", "Active"],
                ["u13-08", "Prairie SC 2013", "Prairie SC", 0.704, 58, "TX", "Active"],
                ["u13-09", "Oak Grove FC 2013", "Oak Grove FC", 0.694, 64, "Texas", "Active"],
                ["u13-10", "Westside United 2013", "Westside United", 0.684, 72, "TX", "Active"],
                ["u13-11", "Meadow Athletic 2013", "Meadow Athletic", 0.674, 80, "Texas", "Active"],
                ["u13-12", "Southside United 2013", "Southside United", 0.664, None, "TX", "Not Enough Ranked Games"],
                ["u13-13", "Sample FC 2013 White", "Sample FC", None, None, "TX", None],
            ],
            "review": {
                "u13-13": ["No current rating.", NO_CURRENT_RATING],
            },
            "national_ranks": {
                "u13-01": 42,
                "u13-02": 105,
                "u13-03": 158,
                "u13-04": 260,
                "u13-05": 310,
                "u13-06": 380,
                "u13-07": 594,
                "u13-08": 660,
                "u13-09": 745,
                "u13-10": 810,
                "u13-11": 920,
            },
            "records": {
                "u13-01": "12-2-1",
                "u13-02": "11-3-1",
                "u13-03": "10-3-2",
                "u13-04": "10-4-1",
                "u13-05": "9-4-2",
                "u13-06": "8-5-2",
                "u13-07": "9-4-2",
                "u13-08": "8-5-2",
                "u13-09": "7-6-2",
                "u13-10": "6-6-3",
                "u13-11": "6-7-2",
                "u13-12": "1-1-1",
            },
            "note": ("Illustrative sample: fictional teams, records, ratings and matchup projections. "
                     "Not a real tournament or an accuracy claim."),
        },
        {
            "age_group": "u10",
            "gender": "Male",
            "teams": [
                ["u10-01", "Juniper FC 2016 Blue", "Juniper FC", 0.901, 2, "Arizona", "Active"],
                ["u10-02", "Copper State 2016", "Copper State", 0.872, 6, "AZ", "Active"],
                ["u10-03", "Desert United 2016", "Desert United", 0.846, 11, "Arizona", "Active"],
                ["u10-04", "Valley Athletic 2016", "Valley Athletic", 0.729, 24, "AZ", "Active"],
                ["u10-05", "Mesa Juniors 2016", "Mesa Juniors", 0.701, 32, "Arizona", "Active"],
                ["u10-06", "Sample Academy 2016", "Sample Academy", None, None, "AZ", None],
            ],
            "review": {"u10-06": ["Not found in PitchRank.", NOT_FOUND]},
            "note": "Sample workbook: use the yellow columns for the director's final decisions.",
        },
        {
            "age_group": "u12",
            "gender": "Female",
            "teams": [
                ["u12-01", "Summit SC 2014 Green", "Summit SC", 0.893, 4, "Colorado", "Active"],
                ["u12-02", "Front Range FC 2014", "Front Range FC", 0.865, 9, "CO", "Active"],
                ["u12-03", "Aspen Athletic 2014", "Aspen Athletic", 0.839, 15, "Colorado", "Active"],
                ["u12-04", "Peak United 2014", "Peak United", 0.716, 29, "CO", "Active"],
                ["u12-05", "Foothills FC 2014", "Foothills FC", 0.689, 37, "Colorado", "Active"],
                ["u12-06", "Sample Select 2014", "Sample Select", 0.674, 42, "CO", "Active"],
                ["u12-07", "Review United 2014", "Review United", 0.650, 50, "Colorado", "Active"],
            ],
            "review": {"u12-07": ["Confirm the team identity before seeding.", DATA_REVIEW]},
            "listed_division": {"u12-05": "Premier"},
            "note": "Sample data only. Strength markers are observations, not automatic divisions.",
        },
    ],
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_local_module(root: Path, module: str) -> set[Path]:
    """Resolve a local module and every package initializer Python executes."""
    if not module:
        return set()
    module_parts = module.split(".")
    base = root.joinpath(*module.split("."))
    candidates = (base.with_suffix(".py"), base / "__init__.py")
    for candidate in candidates:
        if candidate.is_file():
            files = {candidate.relative_to(root)}
            package_depth = len(module_parts) - 1
            for depth in range(1, package_depth + 1):
                initializer = root.joinpath(*module_parts[:depth], "__init__.py")
                if initializer.is_file():
                    files.add(initializer.relative_to(root))
            return files
    return set()


def _local_imports(root: Path, relative: Path) -> set[Path]:
    """Return local modules imported directly by one Python source file."""
    source = (root / relative).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative.as_posix())
    package = list(relative.with_suffix("").parts[:-1])
    imports: set[Path] = set()

    for node in ast.walk(tree):
        module_names: list[str] = []
        if isinstance(node, ast.Import):
            module_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parent_count = node.level - 1
                if parent_count > len(package):
                    continue
                base_parts = package[: len(package) - parent_count]
                if node.module:
                    base_parts.extend(node.module.split("."))
                base = ".".join(base_parts)
            else:
                base = node.module or ""
            if base:
                module_names.append(base)
            module_names.extend(f"{base}.{alias.name}" if base else alias.name for alias in node.names)

        for module_name in module_names:
            imports.update(_resolve_local_module(root, module_name))
    return imports


def _derived_local_python_dependencies(root: Path, entry_points: tuple[Path, ...]) -> set[Path]:
    """Derive the transitive local-import closure for renderer entry points."""
    pending = list(entry_points)
    dependencies: set[Path] = set()
    while pending:
        relative = pending.pop()
        if relative in dependencies:
            continue
        dependencies.add(relative)
        pending.extend(_local_imports(root, relative) - dependencies)
    return dependencies


def renderer_files() -> tuple[Path, ...]:
    """Return derived Python dependencies plus explicit non-imported assets."""
    files = _derived_local_python_dependencies(ROOT, RENDERER_ENTRY_POINTS)
    files.update(RENDERER_ASSETS)
    return tuple(sorted(files, key=lambda path: path.as_posix()))


def renderer_fingerprint() -> str:
    """Identify the frozen input and every source file that renders it."""
    digest = hashlib.sha256()
    fixture = json.dumps(
        SYNTHETIC_FIXTURE,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest.update(len(fixture).to_bytes(8, "big"))
    digest.update(fixture)
    for relative in renderer_files():
        name = relative.as_posix().encode("utf-8")
        contents = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def verify_committed_samples() -> None:
    """Fail loudly when renderers or committed outputs drift from the manifest."""
    command = "python scripts/regenerate_matchbalance_samples.py"
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionError(f"MatchBalance sample manifest is missing or invalid; run `{command}`.") from exc
    actual_renderer = renderer_fingerprint()
    if manifest.get("renderer_sha256") != actual_renderer:
        raise AssertionError(f"MatchBalance sample renderer changed; run `{command}` and commit its outputs.")
    expected_outputs = manifest.get("outputs")
    if not isinstance(expected_outputs, dict):
        raise AssertionError(f"MatchBalance sample output hashes are missing; run `{command}`.")
    for path in OUTPUTS:
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file() or expected_outputs.get(relative) != _sha256(path):
            raise AssertionError(f"Committed MatchBalance sample `{relative}` is stale; run `{command}`.")


def _prediction(first_score: float, second_score: float) -> ComparePrediction:
    margin = round((first_score - second_score) * 20, 6)
    blowout = min(0.55, max(0.04, abs(margin) / 6))
    return ComparePrediction(
        predicted_winner="team_a" if margin >= 0 else "team_b",
        win_probability_a=0.65 if margin >= 0 else 0.25,
        win_probability_b=0.25 if margin >= 0 else 0.65,
        draw_probability=0.10,
        expected_score={"teamA": 2 if margin >= 0 else 1, "teamB": 1 if margin >= 0 else 2},
        expected_margin=margin,
        expected_absolute_goal_difference=abs(margin),
        blowout_4plus_probability=blowout,
        confidence="high",
        confidence_score=0.82,
    )


def _build_cohort(fixture: dict[str, Any]) -> CohortSheet:
    reviews = fixture.get("review", {})
    teams = []
    entrants = []
    for entrant_id, name, club, score, rank, state, status in fixture["teams"]:
        review_reason, review_status = reviews.get(entrant_id, (None, DATA_REVIEW))
        teams.append(
            SheetTeam(
                team_name=name,
                club_name=club,
                power_score=score,
                state_rank=rank,
                record=fixture.get("records", {}).get(entrant_id, ""),
                national_rank=fixture.get("national_ranks", {}).get(entrant_id),
                national_rank_context=(
                    f"{fixture['plays_up'][entrant_id].upper()} "
                    f"{'Boys' if fixture['gender'] == 'Male' else 'Girls'}"
                    if entrant_id in fixture.get("national_ranks", {})
                    and entrant_id in fixture.get("plays_up", {}) else ""
                ),
                state=state,
                status=status,
                entrant_id=entrant_id,
                review_reason=review_reason,
                plays_up=entrant_id in fixture.get("plays_up", {}),
                play_up_from_age_group=fixture.get("plays_up", {}).get(entrant_id),
                requested_flight=fixture.get("requested_flight", {}).get(entrant_id),
                listed_division=fixture.get("listed_division", {}).get(entrant_id),
            )
        )
        entrants.append(
            TierEntrant(
                entrant_id,
                name,
                score,
                review_reason,
                limited_history=status == "Not Enough Ranked Games",
                review_status=review_status,
                evidence_game_count=(
                    sum(int(count) for count in fixture["records"][entrant_id].split("-"))
                    if entrant_id in fixture.get("records", {}) else None
                ),
            )
        )
    eligible = {item.entrant_id: item.power_score for item in entrants if not item.review_reason}
    predictions = {
        (first, second): _prediction(float(eligible[first]), float(eligible[second]))
        for first, second in combinations(sorted(eligible), 2)
    }
    analysis = build_cheat_sheet_analysis(entrants, predictions)
    analysis = replace(analysis, tier_guidance=build_tier_guidance(
        analysis, entrants, predictions, TierPolicy(), load_format_library(),
    ))
    rated = tuple(team for team in teams if team.power_score is not None)
    unrated = tuple(team for team in teams if team.power_score is None)
    return CohortSheet(fixture["age_group"], fixture["gender"], rated, unrated, analysis)


def public_sample_note(cohort: CohortSheet) -> str:
    """Describe the computed sample formats without duplicating a full catalog label."""
    divisions = cohort.tier_analysis.tier_guidance["divisions"]
    descriptions = []
    for division in divisions:
        selected = division["selected_format"]
        pools = " + ".join(str(size) for size in selected["pool_sizes"])
        descriptions.append(
            f"Seeds {division['start_seed']}-{division['end_seed']}: pools {pools}; "
            f"{selected['minimum_games']} guaranteed, up to {selected['maximum_games']} games "
            f"with semifinals and a final ({selected['total_matches']} matches)."
        )
    return " ".join((*descriptions, SYNTHETIC_FIXTURE["cohorts"][0]["note"]))


def _normalize_pdf(payload: bytes) -> bytes:
    generated = SYNTHETIC_FIXTURE["generated_on"].replace("-", "")
    normalized, replacements = re.subn(rb"D:\d{14}", f"D:{generated}000000".encode(), payload)
    if replacements < 2 or not normalized.startswith(b"%PDF-") or b"%%EOF" not in normalized[-1024:]:
        raise RuntimeError("The production PDF renderer returned an unexpected PDF structure.")
    return normalized


def _normalize_xlsx(payload: bytes) -> bytes:
    source = zipfile.ZipFile(BytesIO(payload), "r")
    output = BytesIO()
    with source, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for item in sorted(source.infolist(), key=lambda value: value.filename):
            normalized = zipfile.ZipInfo(item.filename, date_time=(1980, 1, 1, 0, 0, 0))
            normalized.compress_type = zipfile.ZIP_DEFLATED
            normalized.external_attr = item.external_attr
            normalized.create_system = item.create_system
            contents = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                generated = SYNTHETIC_FIXTURE["generated_on"]
                contents, replacements = re.subn(
                    rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                    f"{generated}T00:00:00Z".encode(),
                    contents,
                )
                if replacements != 2:
                    raise RuntimeError("The workbook renderer returned unexpected document timestamps.")
            target.writestr(normalized, contents)
    return output.getvalue()


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        raise RuntimeError(f"Artifact renderer failed: {' '.join(command)}\n{detail}")


def _render_png(pdf: Path, output: Path, pdftoppm: str) -> None:
    prefix = output.with_suffix("")
    _run([pdftoppm, "-f", "1", "-l", "1", "-singlefile", "-png", "-r", "144", str(pdf), str(prefix)])
    if not output.is_file():
        raise RuntimeError(f"Poppler did not produce {output}.")


def _crop_workbook_preview(path: Path) -> None:
    try:
        from PIL import Image, ImageChops
    except ImportError as exc:
        raise RuntimeError("Workbook preview regeneration needs Pillow (`pip install Pillow`).") from exc
    with Image.open(path) as source:
        image = source.convert("RGB")
    # Excel places the footer at the physical bottom of the page. The design
    # preview shows the worksheet itself, so find content above the footer and
    # crop to it with a stable margin.
    search_height = int(image.height * 0.85)
    search = image.crop((0, 0, image.width, search_height))
    background = Image.new("RGB", search.size, "white")
    bounds = ImageChops.difference(search, background).getbbox()
    if bounds is None:
        raise RuntimeError(f"Excel rendered an empty workbook preview for {path.name}.")
    left, top, right, bottom = bounds
    margin = 24
    crop = (
        max(0, left - margin),
        max(0, top - margin),
        min(image.width, right + margin),
        min(search_height, bottom + margin),
    )
    image.crop(crop).save(path, format="PNG", compress_level=9, optimize=False)


def regenerate() -> None:
    pdftoppm = shutil.which("pdftoppm")
    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if not pdftoppm:
        raise RuntimeError("Sample regeneration needs Poppler's pdftoppm on PATH.")
    if not powershell:
        raise RuntimeError("Workbook preview regeneration needs Windows PowerShell and Microsoft Excel.")

    cohorts = tuple(_build_cohort(item) for item in SYNTHETIC_FIXTURE["cohorts"])
    by_key = {(cohort.age_group, cohort.gender): cohort for cohort in cohorts}
    notes = {(item["age_group"], item["gender"]): item["note"] for item in SYNTHETIC_FIXTURE["cohorts"]}
    public = by_key[("u13", "Male")]
    document = render_sheet_html(
        SYNTHETIC_FIXTURE["public_event"],
        [public],
        generated_on=SYNTHETIC_FIXTURE["generated_on"],
        ranking_run=SYNTHETIC_FIXTURE["ranking_run"],
        operator_notes={("u13", "Male"): public_sample_note(public)},
    )
    PUBLIC_PDF.write_bytes(_normalize_pdf(render_seeding_pdf(document)))

    workbook_cohorts = [by_key[("u10", "Male")], by_key[("u12", "Female")]]
    workbook_notes = {key: value for key, value in notes.items() if key in {("u10", "Male"), ("u12", "Female")}}
    workbook_payload = _normalize_xlsx(
        build_seeding_workbook(
            SYNTHETIC_FIXTURE["workbook_event"],
            workbook_cohorts,
            generated_on=SYNTHETIC_FIXTURE["generated_on"],
            ranking_run=SYNTHETIC_FIXTURE["ranking_run"],
            operator_notes=workbook_notes,
        )
    )
    validate_seeding_workbook(workbook_payload, workbook_sheet_titles(workbook_cohorts))
    WORKBOOK.write_bytes(workbook_payload)

    with tempfile.TemporaryDirectory(prefix="matchbalance-samples-") as temporary:
        scratch = Path(temporary)
        _render_png(PUBLIC_PDF, scratch / PUBLIC_PNG.name, pdftoppm)
        PUBLIC_PNG.write_bytes((scratch / PUBLIC_PNG.name).read_bytes())
        helper = ROOT / "scripts" / "render_matchbalance_workbook_previews.ps1"
        _run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
                "-WorkbookPath",
                str(WORKBOOK),
                "-OutputDirectory",
                str(scratch),
            ]
        )
        for name, output in WORKBOOK_PREVIEWS.items():
            _render_png(scratch / f"{name}.pdf", scratch / output.name, pdftoppm)
            _crop_workbook_preview(scratch / output.name)
            output.write_bytes((scratch / output.name).read_bytes())

    manifest = {
        "renderer_sha256": renderer_fingerprint(),
        "outputs": {path.relative_to(ROOT).as_posix(): _sha256(path) for path in OUTPUTS},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_committed_samples()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the committed fingerprint and output hashes")
    args = parser.parse_args()
    if args.check:
        verify_committed_samples()
        print("MatchBalance sample artifacts match their renderer manifest.")
        return
    regenerate()
    print("Regenerated five MatchBalance sample artifacts and their manifest.")


if __name__ == "__main__":
    main()
