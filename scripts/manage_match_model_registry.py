"""Register and explicitly activate reviewed MatchBalance model artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.predictions.model_registry import (  # noqa: E402
    activate_model_version,
    load_registry,
    register_model_version,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry-root",
        default="models/matchbalance_registry",
        help="Local immutable registry directory",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register", help="Register a new reviewed version")
    register.add_argument("--version", required=True)
    register.add_argument("--artifact", required=True)
    register.add_argument("--laboratory-manifest", required=True)
    register.add_argument("--candidate", required=True)
    register.add_argument("--prospective-scorecard")
    register.add_argument("--prospective-version")

    activate = commands.add_parser("activate", help="Activate a registered version")
    activate.add_argument("--version", required=True)

    commands.add_parser("list", help="Show registered versions and activation state")
    args = parser.parse_args()
    registry_root = Path(args.registry_root).resolve()

    if args.command == "register":
        result = register_model_version(
            registry_root=registry_root,
            version=args.version,
            artifact=args.artifact,
            laboratory_manifest=args.laboratory_manifest,
            candidate=args.candidate,
            prospective_scorecard=args.prospective_scorecard,
            prospective_version=args.prospective_version or "",
        )
    elif args.command == "activate":
        result = activate_model_version(
            registry_root=registry_root,
            version=args.version,
        )
    else:
        result = load_registry(registry_root)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
