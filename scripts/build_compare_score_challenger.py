"""Build private offline score candidates from frozen goal-rate batches; preview by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.predictions import score_challenger  # noqa: E402
from src.predictions.private_research_output import private_output_path  # noqa: E402


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Frozen baseline and learned-rate JSON batch")
    parser.add_argument(
        "--fit", required=True, type=Path, help="Frozen fitted-model JSON bound by the input's model_sha256"
    )
    parser.add_argument("--candidate", choices=score_challenger.CANDIDATES, default="blend_25")
    parser.add_argument("--execute", action="store_true", help="Write one new private local artifact")
    parser.add_argument("--output", type=Path, help="New gitignored file; required with --execute")
    args = parser.parse_args(argv)
    try:
        output = private_output_path(args.execute, args.output)
        input_raw, fit_raw = args.input.read_bytes(), args.fit.read_bytes()
        batch, fit = json.loads(input_raw), json.loads(fit_raw)
        if batch.get("model_sha256") != _sha(fit_raw):
            raise ValueError("Input batch does not bind the supplied fitted model")
        result = score_challenger.build_score_batch(batch, fit, candidate=args.candidate)
        code = Path(score_challenger.__file__).read_text(encoding="utf-8").encode()
        runner = Path(__file__).read_text(encoding="utf-8").encode()
        definition_raw = json.dumps(result["definition"], sort_keys=True, separators=(",", ":")).encode()
        result["provenance"] = {
            "input_sha256": _sha(input_raw), "fit_sha256": _sha(fit_raw),
            "module_sha256": _sha(code), "runner_sha256": _sha(runner),
            "candidate_signature": _sha(definition_raw + b"\n" + code + b"\n" + runner + b"\n" + fit_raw),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        encoded = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
        if output is not None:
            with output.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
        print(json.dumps({
            "dry_run": not args.execute, "candidate": args.candidate,
            "fixtures": len(result["rows"]), "coverage": result["coverage"],
            "candidate_signature": result["provenance"]["candidate_signature"],
            "winner_probabilities_preserved": True, "live_formula_changed": False,
            "formal_confirmation_registered": False,
        }, sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Score candidate refused: {exc}\n")


if __name__ == "__main__":
    main()
