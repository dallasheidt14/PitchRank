#!/usr/bin/env python3
"""Initialize a new skill directory with template files."""

import argparse
import os
import sys
import textwrap


def create_skill(skill_name: str, output_dir: str) -> str:
    """Create a new skill directory with template structure.

    Args:
        skill_name: Name of the skill (used for directory and frontmatter).
        output_dir: Parent directory where the skill folder will be created.

    Returns:
        Path to the created skill directory.
    """
    skill_dir = os.path.join(output_dir, skill_name)

    if os.path.exists(skill_dir):
        print(f"Error: Directory already exists: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    # Create directory structure
    os.makedirs(skill_dir, exist_ok=True)
    os.makedirs(os.path.join(skill_dir, "scripts"), exist_ok=True)
    os.makedirs(os.path.join(skill_dir, "references"), exist_ok=True)
    os.makedirs(os.path.join(skill_dir, "assets"), exist_ok=True)

    # Create SKILL.md template
    skill_md = textwrap.dedent(f"""\
        ---
        name: {skill_name}
        description: TODO - Describe what this skill does and when to use it. Include specific triggers and contexts.
        ---

        # {skill_name.replace("-", " ").title()}

        ## Overview

        TODO - Brief description of this skill's purpose and capabilities.

        ## Usage

        TODO - Core workflow and instructions.

        ## Bundled Resources

        - **scripts/**: TODO - List executable scripts and their purpose, or remove if unused.
        - **references/**: TODO - List reference files and when to read them, or remove if unused.
        - **assets/**: TODO - List asset files and their purpose, or remove if unused.
    """)

    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write(skill_md)

    # Create example script
    example_script = textwrap.dedent("""\
        #!/usr/bin/env python3
        \"\"\"Example script - replace or delete this file.\"\"\"

        def main():
            print("Hello from the skill script!")

        if __name__ == "__main__":
            main()
    """)

    example_script_path = os.path.join(skill_dir, "scripts", "example.py")
    with open(example_script_path, "w") as f:
        f.write(example_script)
    os.chmod(example_script_path, 0o755)

    # Create example reference
    example_ref = textwrap.dedent("""\
        # Example Reference

        TODO - Replace this file with actual reference material, or delete if unused.

        This file is loaded into context only when Claude determines it's needed.
    """)

    with open(os.path.join(skill_dir, "references", "example.md"), "w") as f:
        f.write(example_ref)

    # Create example asset placeholder
    with open(os.path.join(skill_dir, "assets", ".gitkeep"), "w") as f:
        f.write("")

    print(f"Skill initialized: {skill_dir}")
    print(f"  SKILL.md          - Edit frontmatter and instructions")
    print(f"  scripts/example.py - Replace with real scripts or delete")
    print(f"  references/example.md - Replace with real references or delete")
    print(f"  assets/.gitkeep   - Add asset files or delete directory")

    return skill_dir


def main():
    parser = argparse.ArgumentParser(
        description="Initialize a new skill directory with template files."
    )
    parser.add_argument("skill_name", help="Name of the skill (e.g., my-skill)")
    parser.add_argument(
        "--path",
        default=".",
        help="Output directory where the skill folder will be created (default: current directory)",
    )
    args = parser.parse_args()

    # Validate skill name
    name = args.skill_name.strip()
    if not name:
        print("Error: Skill name cannot be empty.", file=sys.stderr)
        sys.exit(1)

    if " " in name:
        print(
            f"Error: Skill name should use hyphens, not spaces. Try: {name.replace(' ', '-')}",
            file=sys.stderr,
        )
        sys.exit(1)

    output_dir = os.path.abspath(args.path)
    if not os.path.isdir(output_dir):
        print(f"Error: Output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)

    create_skill(name, output_dir)


if __name__ == "__main__":
    main()
