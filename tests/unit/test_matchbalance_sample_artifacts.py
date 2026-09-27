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
