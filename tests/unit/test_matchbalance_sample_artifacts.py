from pathlib import Path

from scripts.regenerate_matchbalance_samples import (
    _derived_local_python_dependencies,
    verify_committed_samples,
)


def test_renderer_dependencies_follow_transitive_local_imports(tmp_path: Path):
    package = tmp_path / "src" / "sample_renderer"
    package.mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text(
        "from .package_helper import SETTING\n",
        encoding="utf-8",
    )
    (package / "package_helper.py").write_text("SETTING = 'sample'\n", encoding="utf-8")
    (package / "entry.py").write_text(
        "from src.sample_renderer.helper import render\n",
        encoding="utf-8",
    )
    (package / "helper.py").write_text(
        "from .leaf import VALUE\n\ndef render():\n    return VALUE\n",
        encoding="utf-8",
    )
    (package / "leaf.py").write_text("VALUE = 'rendered'\n", encoding="utf-8")

    dependencies = _derived_local_python_dependencies(
        tmp_path,
        (Path("src/sample_renderer/entry.py"),),
    )

    assert dependencies == {
        Path("src/__init__.py"),
        Path("src/sample_renderer/__init__.py"),
        Path("src/sample_renderer/entry.py"),
        Path("src/sample_renderer/helper.py"),
        Path("src/sample_renderer/leaf.py"),
        Path("src/sample_renderer/package_helper.py"),
    }


def test_committed_matchbalance_samples_match_the_renderer_manifest():
    verify_committed_samples()


def test_public_sample_shows_practical_tiers_records_and_honest_coverage():
    from scripts.regenerate_matchbalance_samples import (
        SYNTHETIC_FIXTURE,
        _build_cohort,
        public_sample_note,
    )
    from src.tournaments.seeding_content import build_director_cohort
    from src.tournaments.seeding_sheet import render_sheet_html

    sheet = _build_cohort(SYNTHETIC_FIXTURE["cohorts"][0])
    content = build_director_cohort(sheet)
    guidance = sheet.tier_analysis.tier_guidance
    assert [division["size"] for division in guidance["divisions"]] == [6, 6]
    assert guidance["status"] == "primary_suggestion_for_assigned_subset"
    assert guidance["risky_pairings"] == []
    assert len(content.seeded) == 12
    assert len(content.rows) == 13
    assert all(row.team.record for row in content.seeded)
    assert content.seeded[0].team.record == "12-2-1"
    assert content.seeded[-1].team.record == "1-1-1"
    assert content.review_teams == ("Southside United 2013",)
    for division in guidance["divisions"]:
        selected = division["selected_format"]
        assert selected["display_name"] == "Round robin with semifinals"
        assert selected["pool_sizes"] == [3, 3]
        assert selected["minimum_games"] == 3
        assert selected["maximum_games"] == 4
        assert selected["total_matches"] == 10
    note = public_sample_note(sheet)
    html = render_sheet_html(
        SYNTHETIC_FIXTURE["public_event"], [sheet],
        generated_on="2026-09-25", ranking_run="2026-09-22",
        operator_notes={("u13", "Male"): note},
    )
    assert "pools 3 + 3" in html
    assert "3 guaranteed, up to 4 games" in html
    assert "fictional teams, records, ratings and matchup projections" in html
    assert "Not enough data to recommend a placement" in html
    assert "Matchup review needed" not in html
    assert "Small tier:" not in html
