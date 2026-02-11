#!/usr/bin/env python3
"""Validate and package a skill into a distributable .skill file."""

import argparse
import os
import sys
import zipfile

import yaml


def validate_skill(skill_dir: str) -> list[str]:
    """Validate a skill directory and return a list of errors."""
    errors: list[str] = []

    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md_path):
        errors.append("Missing required file: SKILL.md")
        return errors

    with open(skill_md_path, "r") as f:
        content = f.read()

    # Parse frontmatter
    if not content.startswith("---"):
        errors.append("SKILL.md must start with YAML frontmatter (---)")
        return errors

    parts = content.split("---", 2)
    if len(parts) < 3:
        errors.append("SKILL.md frontmatter is malformed (missing closing ---)")
        return errors

    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML in frontmatter: {e}")
        return errors

    if not isinstance(frontmatter, dict):
        errors.append("Frontmatter must be a YAML mapping")
        return errors

    # Check required fields
    if "name" not in frontmatter:
        errors.append("Frontmatter missing required field: name")
    elif not frontmatter["name"] or not str(frontmatter["name"]).strip():
        errors.append("Frontmatter 'name' field cannot be empty")

    if "description" not in frontmatter:
        errors.append("Frontmatter missing required field: description")
    elif not frontmatter["description"] or not str(frontmatter["description"]).strip():
        errors.append("Frontmatter 'description' field cannot be empty")
    elif len(str(frontmatter["description"])) < 20:
        errors.append(
            "Frontmatter 'description' should be at least 20 characters to be useful for triggering"
        )

    # Check for TODO placeholders
    if "TODO" in parts[1]:
        errors.append("Frontmatter still contains TODO placeholders")

    body = parts[2].strip()
    if not body:
        errors.append("SKILL.md body is empty - add instructions")
    elif len(body) < 50:
        errors.append("SKILL.md body seems too short to be useful")

    if "TODO" in body:
        errors.append("SKILL.md body still contains TODO placeholders")

    # Check skill name matches directory name
    dir_name = os.path.basename(os.path.normpath(skill_dir))
    if "name" in frontmatter and frontmatter["name"] != dir_name:
        errors.append(
            f"Skill name '{frontmatter['name']}' doesn't match directory name '{dir_name}'"
        )

    # Check for extraneous files
    extraneous = {"README.md", "CHANGELOG.md", "INSTALLATION_GUIDE.md", "QUICK_REFERENCE.md"}
    for item in os.listdir(skill_dir):
        if item in extraneous:
            errors.append(f"Remove extraneous file: {item}")

    return errors


def package_skill(skill_dir: str, output_dir: str) -> str:
    """Package a validated skill into a .skill file.

    Args:
        skill_dir: Path to the skill directory.
        output_dir: Directory where the .skill file will be created.

    Returns:
        Path to the created .skill file.
    """
    skill_name = os.path.basename(os.path.normpath(skill_dir))
    output_path = os.path.join(output_dir, f"{skill_name}.skill")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(skill_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.join(
                    skill_name, os.path.relpath(file_path, skill_dir)
                )
                zf.write(file_path, arcname)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Validate and package a skill into a distributable .skill file."
    )
    parser.add_argument("skill_dir", help="Path to the skill directory")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Output directory for the .skill file (default: current directory)",
    )
    args = parser.parse_args()

    skill_dir = os.path.abspath(args.skill_dir)
    output_dir = os.path.abspath(args.output_dir)

    if not os.path.isdir(skill_dir):
        print(f"Error: Not a directory: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(output_dir):
        print(f"Error: Output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)

    # Validate
    print(f"Validating skill: {skill_dir}")
    errors = validate_skill(skill_dir)

    if errors:
        print(f"\nValidation failed with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print("Validation passed.")

    # Package
    output_path = package_skill(skill_dir, output_dir)
    print(f"Skill packaged: {output_path}")

    return output_path


if __name__ == "__main__":
    main()
