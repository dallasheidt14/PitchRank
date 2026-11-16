"""Derive committed execution dependencies for the default form or explicit research entrypoints."""

import ast
import re
from pathlib import Path

from src.predictions.form_policy import CALIBRATION_SNAPSHOT_FILES
from src.predictions.form_research import pinned_source_identity


def candidate_execution_paths(root: Path, *, entrypoints: list[str] | None = None) -> set[str]:
    root = root.resolve()
    # Default form mode also authenticates collector modules read as text by its runner.
    required = ({"frontend/lib/" + name for name in pinned_source_identity()["source_hashes"]}
                if entrypoints is None else set())
    pending = list(entrypoints) if entrypoints is not None else [
               "src/predictions/form_research.py", "src/predictions/form_archive_sources.py",
               "scripts/benchmark_compare_form.py",
               "frontend/lib/matchPredictor.ts", "frontend/scripts/run-form-research.ts",
               "frontend/scripts/verify-compare-source.ts"]
    visited = set()

    def imported_nodes(node):
        # Explicit entrypoints execute their CLI bodies; default form mode imports its Python modules as libraries.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main" and entrypoints is None:
            return
        yield node
        for child in ast.iter_child_nodes(node):
            yield from imported_nodes(child)

    def add(path):
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError("Candidate dependency escaped the source checkout")
        if path.is_file():
            pending.append(path.relative_to(root).as_posix())

    def python_module(parts):
        base = root.joinpath(*parts)
        if base.with_suffix(".py").is_file():
            add(base.with_suffix(".py"))
        elif (base / "__init__.py").is_file():
            add(base / "__init__.py")
        elif base.is_dir():
            pass  # Namespace packages execute no initializer.
        else:
            raise ValueError("Missing local candidate dependency: " + ".".join(parts))
        for length in range(1, len(parts)):
            if (root.joinpath(*parts[:length]) / "__init__.py").exists():
                add(root.joinpath(*parts[:length]) / "__init__.py")

    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        required.add(name)
        path = root / name
        source = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            for node in imported_nodes(ast.parse(source)):
                if isinstance(node, ast.Import):
                    for item in node.names:
                        parts = item.name.split(".")
                        if parts[0] in {"src", "scripts", "config"}:
                            python_module(parts)
                elif isinstance(node, ast.ImportFrom):
                    parts = (node.module or "").split(".") if node.module else []
                    if node.level:
                        parts = [*Path(name).parts[:-node.level], *parts]
                    if parts and parts[0] in {"src", "scripts", "config"}:
                        python_module(parts)
                        for item in node.names:
                            child = root.joinpath(*parts, item.name)
                            if child.with_suffix(".py").exists() or (child / "__init__.py").exists():
                                python_module([*parts, item.name])
        else:
            imports = re.findall(
                r"(?m)^\s*(?:import|export)\s+(?!\s*type\b)(?:(?!;)[\s\S])*?\bfrom\s+['\"]([^'\"]+)['\"]", source,
            )
            imports += re.findall(r"\bimport\s*(?:\(\s*)?['\"]([^'\"]+)['\"]", source)
            for module in imports:
                if module.startswith("."):
                    base = path.parent / module
                elif module.startswith("@/"):
                    base = root / "frontend" / module[2:]
                else:
                    continue
                for suffix in ("", ".ts", ".tsx", ".json", "/index.ts"):
                    target = Path(str(base) + suffix)
                    if target.is_file():
                        add(target)
                        break
                else:
                    raise ValueError("Missing local TypeScript dependency: " + module)
    required.add("requirements.lock")
    if entrypoints is None:
        required.add("frontend/package-lock.json")
        required.update("frontend/public/data/calibration/" + name for name in CALIBRATION_SNAPSHOT_FILES.values())
    if any(not (root / name).is_file() for name in required):
        raise ValueError("Candidate checkout is missing execution dependencies")
    return required
