#!/usr/bin/env python3
"""SincSports team discovery driver.

Seeds ``teams`` + ``team_alias_map`` with Boys/Men + Girls/Women U10–U19
club teams across the 50 US states + DC by driving the discovery scraper
at ``src/scrapers/sincsports_clubs.py``. Discovered teams flow through
``SincSportsGameMatcher`` in ``discovery_mode=True`` so sub-0.91 fuzzy
results auto-create instead of piling into the review queue.

Shape mirrors ``scripts/extract_and_import_tgs_teams.py`` (env load,
Supabase bootstrap, batch pre-check, 23505 fallback, rich summary). The
two departures are:

- Per-combo manifest at ``data/exports/sincsports_teams_discovery_<ts>_manifest.json``
  replaces row-count checkpoints so resume is reliable.
- Low-confidence audit CSV captures the suppressed-review signal for
  operator spot-check.

CLI examples:

    python scripts/discover_sincsports_teams.py --states AZ --ages u12 --genders male --dry-run
    python scripts/discover_sincsports_teams.py --states AZ,NC --ages u12,u13 --genders male,female
    python scripts/discover_sincsports_teams.py --resume data/exports/sincsports_teams_discovery_20260424T171511Z

Operational precondition: discovery's metadata-enrichment UPDATE is only
race-free once ``scripts/match_state_from_club.py:617`` gates on
``state_code IS NULL``. Until that lands, DO NOT run this script
concurrently with ``data-hygiene-weekly.yml``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.progress import track  # noqa: E402
from rich.table import Table  # noqa: E402

from config.settings import AGE_GROUPS  # noqa: E402
from src.models.sincsports_matcher import SincSportsGameMatcher  # noqa: E402
from src.scrapers.sincsports_clubs import (  # noqa: E402
    CaptchaOrBlockError,
    SincSportsClubsScraper,
)
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402
from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

# Load env (mirrors extract_and_import_tgs_teams.py:39-44).
_env_local = Path(".env.local")
if _env_local.exists():
    load_dotenv(_env_local)
else:
    load_dotenv()

# Derived from the repo's canonical AGE_GROUPS (u10..u17 + u19 — u18 merges into
# u19 per gotcha_no_u18_age_group.md). The SincSports filter exposes a separate
# U18 option, but inserting teams with age_group="u18" would break the rest of
# PitchRank's pipeline — scraping u19 alone is the correct fit.
DEFAULT_AGES = sorted(AGE_GROUPS.keys())
DEFAULT_GENDERS = ["male", "female"]
_GENDER_CANONICAL = {"male": "Male", "female": "Female", "m": "Male", "f": "Female"}

EXPORTS_DIR = Path("data/exports")
FIXTURES_OBSERVATIONS = Path("tests/fixtures/sincsports_clubs/observations.json")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def ensure_provider_exists(supabase) -> Optional[str]:
    """Ensure SincSports provider exists; return provider UUID.

    Synchronous copy of ``scripts/import_sincsports_teams.py::ensure_provider_exists``.
    """
    result = supabase.table("providers").select("id").eq("code", "sincsports").execute()
    if result.data:
        return result.data[0]["id"]
    console.print("  [yellow]⚠[/yellow] Provider not found, creating...")
    new_provider = {"code": "sincsports", "name": "SincSports", "base_url": "https://soccer.sincsports.com"}
    result = supabase.table("providers").insert(new_provider).execute()
    if result.data:
        pid = result.data[0]["id"]
        console.print(f"  [green]✓[/green] Created provider (ID: {pid})")
        return pid
    return None


def parse_csv_arg(raw: Optional[str], default: List[str]) -> List[str]:
    if not raw:
        return list(default)
    return [s.strip() for s in raw.split(",") if s.strip()]


def canonicalize_states(raw: List[str]) -> List[str]:
    out: List[str] = []
    for s in raw:
        s = s.upper()
        if s not in STATE_CODE_TO_NAME:
            raise SystemExit(f"Unknown state code: {s!r}")
        out.append(s)
    return out


def canonicalize_genders(raw: List[str]) -> List[str]:
    out: List[str] = []
    for g in raw:
        canonical = _GENDER_CANONICAL.get(g.lower())
        if canonical is None:
            raise SystemExit(f"Unknown gender: {g!r}")
        out.append(canonical)
    return out


def canonicalize_ages(raw: List[str]) -> List[str]:
    out: List[str] = []
    for a in raw:
        v = a.lower().strip()
        if v not in AGE_GROUPS:
            # U18 merges into U19 per the repo's AGE_GROUPS; other unknown keys
            # are caught by the same membership check so the driver can't smuggle
            # a value that will later be rejected at INSERT time.
            raise SystemExit(f"Unsupported age group: {a!r} (must be one of {sorted(AGE_GROUPS.keys())})")
        out.append(v)
    return out


def compute_scope_fingerprint(states: List[str], ages: List[str], genders: List[str]) -> str:
    payload = json.dumps({"states": sorted(states), "ages": sorted(ages), "genders": sorted(genders)}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` via a temp file + ``os.replace`` sequence."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_observations() -> Dict:
    if not FIXTURES_OBSERVATIONS.exists():
        raise SystemExit(
            "Cannot start discovery: "
            f"{FIXTURES_OBSERVATIONS} is missing/malformed. Complete Step 3 reconnaissance first."
        )
    try:
        data = json.loads(FIXTURES_OBSERVATIONS.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"Cannot parse {FIXTURES_OBSERVATIONS}: {e}")
    required = [
        "schema_version",
        "state_field_mode",
        "pagination_mode",
        "form_fields",
        "response_markers",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        raise SystemExit(f"{FIXTURES_OBSERVATIONS} missing required fields: {missing}")
    return data


# ----------------------------------------------------------------------
# Manifest + CSV
# ----------------------------------------------------------------------
CSV_COLUMNS = ["provider_team_id", "team_name", "club_name", "age_group", "gender", "state_code"]
LOW_CONFIDENCE_COLUMNS = [
    "provider_team_id",
    "team_name",
    "age_group",
    "gender",
    "state_code",
    "club_name",
    "suppressed_review_method",
    "suppressed_review_confidence",
]


def load_resume_artifacts(prefix: Path, force: bool) -> Dict:
    """Load prior run's CSV + manifest for resume."""
    csv_path = prefix.with_suffix(".csv")
    manifest_path = prefix.parent / (prefix.name + "_manifest.json")

    if not csv_path.exists():
        raise SystemExit(
            f"--resume {prefix} requires {csv_path}; missing. Cannot resume — CSV is the source of truth. "
            "Start a fresh run."
        )

    manifest: Optional[Dict] = None
    if not manifest_path.exists():
        if not force:
            raise SystemExit(
                f"--resume {prefix} requires both {csv_path} and {manifest_path}; manifest missing. "
                "Use --force-resume to rebuild from CSV alone, or start a fresh run."
            )
        console.print(
            "[yellow]Manifest missing; rebuilding from CSV via dedup. All combos will be re-scraped.[/yellow]"
        )
        manifest = {"schema_version": 1, "mode": None, "scope_fingerprint": None, "combos": []}
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    seeded: Dict[str, Dict[str, str]] = {}
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("provider_team_id")
            if pid:
                seeded[pid] = row
    return {
        "csv_path": csv_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "teams_dict": seeded,
    }


def write_csv(path: Path, teams_dict: Dict[str, Dict]) -> None:
    buf_path = path
    tmp_path = buf_path.with_suffix(buf_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for pid in sorted(teams_dict.keys()):
            row = teams_dict[pid]
            writer.writerow({k: (row.get(k) or "") for k in CSV_COLUMNS})
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, buf_path)


def write_manifest(path: Path, manifest: Dict) -> None:
    atomic_write(path, json.dumps(manifest, indent=2, sort_keys=True))


def append_low_confidence_row(path: Path, row: Dict) -> None:
    """Append a single low-confidence audit row, writing the header on first call."""
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOW_CONFIDENCE_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: (row.get(k) if row.get(k) is not None else "") for k in LOW_CONFIDENCE_COLUMNS})


# ----------------------------------------------------------------------
# Bulk alias pre-check (mirrors extract_and_import_tgs_teams.py:148-161)
# ----------------------------------------------------------------------
def bulk_existing_aliases(supabase, provider_id: str, provider_team_ids: List[str]) -> Dict[str, str]:
    existing: Dict[str, str] = {}
    for i in range(0, len(provider_team_ids), 100):
        batch = provider_team_ids[i : i + 100]
        try:
            result = (
                supabase.table("team_alias_map")
                .select("provider_team_id, team_id_master")
                .eq("provider_id", provider_id)
                .in_("provider_team_id", batch)
                .execute()
            )
            for row in result.data or []:
                existing[str(row["provider_team_id"])] = row["team_id_master"]
        except Exception as e:
            logger.warning(f"Error checking existing aliases (batch {i // 100 + 1}): {e}")
    return existing


def enrich_state_codes(supabase, existing: Dict[str, str], teams_dict: Dict[str, Dict]) -> int:
    """Monotonic UPDATE of ``teams.state_code`` for already-aliased teams.

    Groups team_id_masters by their discovered state_code and issues one
    UPDATE per state (at most 51), using ``.in_(team_id_master, batch)`` +
    ``.is_("state_code", "null")`` so discovery never overwrites a non-null
    value. Cross-workflow coordination (vs ``data-hygiene-weekly.yml``) is
    enforced upstream by the GHA pre-flight check — see plan Step 6.
    """
    buckets: Dict[str, List[str]] = {}
    for provider_team_id, team_id_master in existing.items():
        record = teams_dict.get(provider_team_id)
        if not record or not record.get("state_code"):
            continue
        buckets.setdefault(record["state_code"], []).append(team_id_master)

    updated = 0
    failures = 0
    for state_code, team_ids in buckets.items():
        # Chunk to stay under PostgREST query-string limits.
        for i in range(0, len(team_ids), 100):
            chunk = team_ids[i : i + 100]
            try:
                result = (
                    supabase.table("teams")
                    .update({"state_code": state_code})
                    .in_("team_id_master", chunk)
                    .is_("state_code", "null")
                    .execute()
                )
                if result.data:
                    updated += len(result.data)
            except Exception as e:
                failures += 1
                logger.debug(f"enrich state_code batch ({state_code}, n={len(chunk)}): {e}")
    if failures:
        logger.warning(f"enrich_state_codes: {failures} batch failures (non-blocking)")
    return updated


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--states", default="", help="CSV of postal codes. Blank = all 50+DC.")
    p.add_argument("--ages", default="", help="CSV of age groups (u10..u19). Blank = all.")
    p.add_argument("--genders", default="", help="CSV of male,female. Blank = both.")
    p.add_argument("--resume", metavar="PREFIX", help="Resume from <prefix>.csv + <prefix>_manifest.json.")
    p.add_argument("--force-resume", action="store_true", help="Override checkpoint integrity mismatch.")
    p.add_argument("--dry-run", action="store_true", help="Scrape + CSV only; no DB writes.")
    p.add_argument("--confirm-full-grid", action="store_true", help="Non-interactive confirm for 1,020-combo run.")
    p.add_argument("--max-combos", type=int, default=None, help="Testing cap — stop after N combos.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    observations = load_observations()
    mode = "B" if observations["state_field_mode"] == "multi" else "A"

    states_raw = parse_csv_arg(args.states, list(STATE_CODE_TO_NAME.keys()))
    ages_raw = parse_csv_arg(args.ages, DEFAULT_AGES)
    genders_raw = parse_csv_arg(args.genders, DEFAULT_GENDERS)

    states = canonicalize_states(states_raw)
    ages = canonicalize_ages(ages_raw)
    genders = canonicalize_genders(genders_raw)

    full_grid = not args.states and not args.ages and not args.genders
    if full_grid and not args.dry_run:
        if sys.stdin.isatty():
            resp = console.input(
                "[yellow]⚠ About to scrape full 1,020-combo grid (~45-60 min). Continue? [y/N] [/yellow]"
            )
            if resp.strip().lower() != "y":
                console.print("[red]Aborted by user.[/red]")
                return 1
        elif not args.confirm_full_grid:
            console.print("[red]Refusing to run full grid non-interactively without --confirm-full-grid.[/red]")
            return 1

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Single run_ts reused by CSV / manifest / low-confidence audit.
    run_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    csv_path = EXPORTS_DIR / f"sincsports_teams_discovery_{run_ts}.csv"
    manifest_path = EXPORTS_DIR / f"sincsports_teams_discovery_{run_ts}_manifest.json"
    low_conf_path = EXPORTS_DIR / f"sincsports_low_confidence_{run_ts}.csv"

    teams_dict: Dict[str, Dict] = {}
    manifest: Dict = {
        "schema_version": 1,
        "mode": mode,
        "scope_fingerprint": compute_scope_fingerprint(states, ages, genders),
        "combos": [],
    }

    resumed_completed: Set[tuple] = set()
    if args.resume:
        loaded = load_resume_artifacts(Path(args.resume), force=args.force_resume)
        csv_path = loaded["csv_path"]
        manifest_path = loaded["manifest_path"]
        prior = loaded["manifest"]
        # Mode gate — HARD FAIL, not bypassable.
        if prior.get("mode") and prior["mode"] != mode:
            console.print(
                f"[red]Cannot resume: manifest was Mode {prior['mode']}, current run is Mode {mode}. "
                "Mode mismatch indicates Step 3 observations changed; start a fresh run. "
                "(--force-resume does NOT bypass this.)[/red]"
            )
            return 1
        # Scope-fingerprint gate — guard against resuming into a different grid.
        prior_fp = prior.get("scope_fingerprint")
        current_fp = compute_scope_fingerprint(states, ages, genders)
        if prior_fp and prior_fp != current_fp and not args.force_resume:
            console.print(
                "[red]Cannot resume: scope fingerprint mismatch. The prior run's "
                "(states, ages, genders) set differs from this run's. Either use the "
                "same scope as the original run, or pass --force-resume to merge scopes "
                "(CSV dedup by provider_team_id handles the overlap).[/red]"
            )
            return 1
        # Relaxed integrity check — crash-during-write is tolerated.
        csv_row_count = len(loaded["teams_dict"])
        completed_sum = sum(c.get("team_count", 0) for c in prior.get("combos", []) if c.get("status") == "completed")
        if csv_row_count < completed_sum and not args.force_resume:
            console.print(
                f"[red]checkpoint integrity mismatch: CSV has {csv_row_count} rows but manifest claims "
                f"{completed_sum} rows across completed combos. Use --force-resume to override "
                "(may skip real data).[/red]"
            )
            return 1

        teams_dict = loaded["teams_dict"]
        manifest = prior if prior.get("mode") else manifest
        for c in manifest.get("combos", []):
            if c.get("status") == "completed":
                resumed_completed.add((c.get("state"), c.get("age"), c.get("gender")))
        console.print(
            f"[green]Resuming from {csv_path.name} ({csv_row_count} teams), "
            f"{len(resumed_completed)} combos already completed.[/green]"
        )

    # Supabase client — skip DB init when dry-run.
    supabase = None
    provider_id: Optional[str] = None
    if not args.dry_run:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set[/red]")
            return 1
        supabase = create_client(supabase_url, supabase_key)
        provider_id = ensure_provider_exists(supabase)
        if not provider_id:
            console.print("[red]Cannot proceed without SincSports provider.[/red]")
            return 1

    # Build combo grid.
    combos: List[tuple] = []
    for state in states:
        for age in ages:
            for gender in genders:
                if (state, age, gender) in resumed_completed:
                    continue
                combos.append((state, age, gender))
    if args.max_combos is not None:
        combos = combos[: args.max_combos]
    console.print(
        Panel.fit(
            f"[bold cyan]SincSports Team Discovery — Mode {mode}[/bold cyan]\n"
            f"States: {len(states)} | Ages: {len(ages)} | Genders: {len(genders)} | "
            f"Combos pending: {len(combos)} | Dry run: {args.dry_run}",
            style="cyan",
        )
    )

    scraper = SincSportsClubsScraper()
    combo_status: Dict[tuple, Dict] = {
        (c["state"], c["age"], c["gender"]): c for c in manifest.get("combos", []) if "state" in c
    }

    # Scrape phase.
    halted_by_block = False
    for state, age, gender in track(combos, description="Scraping combos"):
        entry = {"state": state, "age": age, "gender": gender, "status": "in_progress"}
        combo_status[(state, age, gender)] = entry
        try:
            records = list(scraper.discover_teams(states=[state], ages=[age], genders=[gender]))
        except CaptchaOrBlockError as e:
            console.print(f"[red]Scraper blocked ({e}). Halting for manual intervention.[/red]")
            halted_by_block = True
            break
        except Exception as e:
            logger.error(f"Combo ({state}, {age}, {gender}) failed: {e}")
            entry["status"] = "in_progress"  # retained; will retry on next resume
            entry["error"] = str(e)
            continue

        for r in records:
            teams_dict[r.provider_team_id] = {
                "provider_team_id": r.provider_team_id,
                "team_name": r.team_name,
                "club_name": r.club_name or "",
                "age_group": r.age_group,
                "gender": r.gender,
                "state_code": r.state_code or "",
            }

        entry["status"] = "completed"
        entry["pages_fetched"] = 1  # no pagination on this site — always 1 page
        entry["team_count"] = len(records)
        entry["completed_at"] = datetime.utcnow().isoformat() + "Z"

        manifest["combos"] = list(combo_status.values())
        # Flush CSV first, manifest second — atomic renames, per-file ordering.
        write_csv(csv_path, teams_dict)
        write_manifest(manifest_path, manifest)

    console.print(
        f"\n[bold]Scrape summary:[/bold] {len(teams_dict)} unique teams, "
        f"{len([c for c in manifest['combos'] if c.get('status') == 'completed'])} combos completed, "
        f"{len(scraper.errors)} scraper errors."
    )

    if halted_by_block or args.dry_run:
        console.print(f"[green]CSV saved: {csv_path}[/green]")
        console.print(f"[green]Manifest saved: {manifest_path}[/green]")
        return 1 if halted_by_block else 0

    # Match phase.
    matcher = SincSportsGameMatcher(supabase, provider_id=provider_id, discovery_mode=True)
    existing = bulk_existing_aliases(supabase, provider_id, list(teams_dict.keys()))
    console.print(f"[yellow]{len(existing)} teams already aliased — skipping create path.[/yellow]")

    # Metadata enrichment for pre-existing aliases.
    enriched = enrich_state_codes(supabase, existing, teams_dict)
    console.print(f"[cyan]Enriched state_code on {enriched} pre-existing teams.[/cyan]")

    buckets = {
        "direct_alias_hit": 0,
        "fuzzy_auto_linked": 0,
        "created_new": 0,
        "low_confidence_auto_created": 0,
        "errors": 0,
    }
    for pid, record in track(teams_dict.items(), description="Matching teams"):
        if pid in existing:
            continue
        try:
            result = matcher._match_team(
                provider_id=provider_id,
                provider_team_id=pid,
                team_name=record["team_name"],
                age_group=record["age_group"],
                gender=record["gender"],
                club_name=record["club_name"] or None,
                state_code=record["state_code"] or None,
            )
        except Exception as e:
            logger.error(f"match error for {pid}: {e}")
            buckets["errors"] += 1
            continue

        created = result.get("created", False)
        method = result.get("method")
        suppressed = result.get("suppressed_review_method")

        # Base matcher returns several non-create methods depending on the tier
        # that hit: "direct_id" (alias by provider_team_id), "provider_id"
        # (legacy), and "alias" (alias by team_name). All three are
        # discovery-equivalent to an already-aliased team; the bucket name
        # tracks the operator-facing bucket, not the underlying tier.
        if created is False and method in ("direct_id", "provider_id", "alias"):
            buckets["direct_alias_hit"] += 1
        elif created is False and method == "fuzzy_auto":
            buckets["fuzzy_auto_linked"] += 1
        elif created is True and suppressed is None:
            buckets["created_new"] += 1
        elif created is True and suppressed in ("fuzzy_review", "fuzzy_review_low"):
            buckets["low_confidence_auto_created"] += 1
            append_low_confidence_row(
                low_conf_path,
                {
                    "provider_team_id": pid,
                    "team_name": record["team_name"],
                    "age_group": record["age_group"],
                    "gender": record["gender"],
                    "state_code": record["state_code"],
                    "club_name": record["club_name"],
                    "suppressed_review_method": suppressed,
                    "suppressed_review_confidence": result.get("suppressed_review_confidence"),
                },
            )
        else:
            # An unknown (created, method, suppressed) shape means the matcher
            # return contract drifted. Fail loud so the driver doesn't silently
            # drop teams from every bucket.
            logger.error(
                f"Unclassified match result for {pid}: created={created!r} method={method!r} suppressed={suppressed!r}"
            )
            buckets["errors"] += 1

    # Summary.
    table = Table(title="SincSports Discovery Summary")
    table.add_column("Bucket")
    table.add_column("Count", justify="right")
    table.add_row("Teams scraped", str(len(teams_dict)))
    table.add_row("Skipped (existing alias)", str(len(existing)))
    for k, v in buckets.items():
        table.add_row(k, str(v))
    console.print(table)

    console.print(f"[green]CSV: {csv_path}[/green]")
    console.print(f"[green]Manifest: {manifest_path}[/green]")
    if low_conf_path.exists():
        console.print(f"[yellow]Low-confidence audit CSV: {low_conf_path}[/yellow]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
