"""Require explicit execution and a new ignored path before saving private research."""
import subprocess
from pathlib import Path


def private_output_path(execute, output):
    if execute != (output is not None):
        raise ValueError("Execution and a private output path are required together")
    if output is None:
        return None
    destination = Path(output).resolve()
    subprocess.run(["git", "check-ignore", "-q", "--", str(destination)], cwd=destination.parent,
                   check=True, capture_output=True)
    if destination.exists():
        raise ValueError("Refusing to overwrite a private artifact")
    return destination
