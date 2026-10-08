"""Frozen-input shadow boards for the PitchRank ranking engine.

freeze  Reads production inputs once through a GET-only client: the games the production fetch
        returns for a pinned date (or a saved engine-format games snapshot), then the team
        metadata and merge map compute_all_cohorts reads mid-run.
board   Runs compute_all_cohorts once from a chosen code root on a freeze. The database client is
        a frozen in-memory stand-in that serves exactly the reads the engine makes with games
        passed in, and raises BlockedCall (a BaseException, so the pipeline's catch-and-continue
        cannot swallow it) on anything else, including every write. A board never runs the games
        fetch, so a change inside it does not reach a board.

  python shadow_harness.py freeze --code-root DIR --env-file FILE --today YYYY-MM-DD --out DIR
                                  [--games-from GAMES.parquet]
  python shadow_harness.py board --code-root DIR --freeze DIR --out DIR
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow.parquet as pq
from c1_validation import StageCapture

ENGINE_FILES = [
    "src/etl/glicko_engine.py",
    "src/etl/glicko_config.py",
    "src/rankings/calculator.py",
    "src/rankings/constants.py",
    "src/rankings/layer13_predictive_adjustment.py",
    "src/rankings/data_adapter.py",
    "src/rankings/shared.py",
    "src/utils/merge_resolver.py",
    "config/settings.py",
]
# The games fetch runs only in a freeze; a board reports when its code root changed the fetch's own
# files, the helpers it calls from elsewhere, or the fetch window (recorded as a value, since the
# window's files are ones most ranking changes edit).
FETCH_FILES = ["src/rankings/data_adapter.py", "src/utils/merge_resolver.py"]
FETCH_FUNCTIONS = [("src.rankings.shared", "normalize_gender")]
# fetch_games_for_rankings' output; the engine's own cache files add selection columns and hold one cohort.
ENGINE_GAME_COLUMNS = {
    "age",
    "date",
    "ga",
    "game_id",
    "gender",
    "gf",
    "home_team_master_id",
    "id",
    "opp_age",
    "opp_gender",
    "opp_id",
    "team_id",
}
# Cleared before a board so both runs use code defaults, whatever the shell exports.
ENV_DIAL_PREFIXES = ("SCF_", "SOS_CREDIT_", "RECORD_RECONCILE_", "ML_", "USE_LOCAL_SUPABASE")
FROZEN_FILES = {
    "games.parquet": "games_sha256",
    "teams-metadata.parquet": "teams_metadata_sha256",
    "merge-map.parquet": "merge_map_sha256",
}


class BlockedCall(BaseException):
    """A read the frozen stand-in does not serve, or any write attempt."""


def digest(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, default=str, allow_nan=False)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, encoding="utf-8")


def fetch_fingerprint(code_root: Path) -> dict[str, str]:
    prints = {f: digest(code_root / f) for f in FETCH_FILES}
    for module_name, name in FETCH_FUNCTIONS:
        source = inspect.getsource(getattr(importlib.import_module(module_name), name))
        prints[f"{module_name}.{name}"] = hashlib.sha256(source.encode()).hexdigest()
    return prints


def load_freeze(freeze_dir: Path) -> dict:
    manifest = json.loads((freeze_dir / "freeze-manifest.json").read_text(encoding="utf-8"))
    for name, key in FROZEN_FILES.items():
        if digest(freeze_dir / name) != manifest[key]:
            raise SystemExit(f"{name} does not match its freeze manifest")
    return manifest


def check_games_snapshot(path: Path, today: pd.Timestamp, lookback_days: int) -> None:
    columns = set(pq.read_schema(path).names)
    if columns != ENGINE_GAME_COLUMNS:
        raise SystemExit(
            f"{path} is not a ranking input snapshot; columns differ by {sorted(columns ^ ENGINE_GAME_COLUMNS)}"
        )
    dates = pd.to_datetime(pd.read_parquet(path, columns=["date"])["date"])
    earliest = today - pd.Timedelta(days=lookback_days)
    if dates.min() < earliest or dates.max() > today:
        raise SystemExit(
            f"{path} holds games from {dates.min().date()} to {dates.max().date()}, outside "
            f"{earliest.date()} to {today.date()}; pass the --today the run that saved it used"
        )


# --------------------------------------------------------------------------- freeze
def fetch_merge_map(client) -> list[dict]:
    merges: list[dict] = []
    offset = 0
    while True:
        page = (
            client.table("team_merge_map")
            .select("deprecated_team_id, canonical_team_id")
            .order("deprecated_team_id")
            .range(offset, offset + 999)
            .execute()
            .data
            or []
        )
        merges.extend(page)
        if len(page) < 1000:
            return merges
        offset += 1000


def cmd_freeze(args) -> None:
    code_root = Path(args.code_root).resolve()
    out = Path(args.out).resolve()
    today = pd.Timestamp(args.today)

    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=True)
    sys.path.insert(0, str(code_root))
    import httpx
    from supabase.lib.client_options import SyncClientOptions

    from src.rankings.calculator import _effective_fetch_lookback_days
    from src.rankings.data_adapter import batch_fetch_rows, fetch_games_for_rankings
    from src.utils.merge_resolver import MergeResolver
    from supabase import create_client

    lookback_days = _effective_fetch_lookback_days(365, use_glicko=True)
    if args.games_from:
        check_games_snapshot(Path(args.games_from), today, lookback_days)
    out.mkdir(parents=True, exist_ok=False)

    def reject_writes(request):
        if request.method not in {"GET", "HEAD"}:
            raise BlockedCall(f"freeze blocked HTTP {request.method} {request.url}")

    with httpx.Client(
        event_hooks={"request": [reject_writes]}, timeout=120, transport=httpx.HTTPTransport(retries=3)
    ) as http:
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            options=SyncClientOptions(httpx_client=http),
        )
        if args.games_from:
            # Copied byte for byte, so the recorded sha256 matches the source file's.
            shutil.copyfile(args.games_from, out / "games.parquet")
            games_source = str(Path(args.games_from).resolve())
        else:
            resolver = MergeResolver(client)
            resolver.load_merge_map()
            games = asyncio.run(
                fetch_games_for_rankings(client, lookback_days=lookback_days, today=today, merge_resolver=resolver)
            )
            games.to_parquet(out / "games.parquet", index=False)
            games_source = f"fetch_games_for_rankings over {lookback_days} days to {today.date()}"
        games = pd.read_parquet(out / "games.parquet", columns=["team_id", "opp_id"])
        ids = sorted(set(games["team_id"].dropna().astype(str)) | set(games["opp_id"].dropna().astype(str)))
        rows = batch_fetch_rows(
            client, "teams", "team_id_master, state_code, league, is_deprecated", "team_id_master", ids
        )
        merges = fetch_merge_map(client)

    snapshot = {str(m["deprecated_team_id"]): str(m["canonical_team_id"]) for m in merges}
    if not args.games_from and (resolver.version in ("error", "no_merges") or snapshot != resolver._merge_map):
        raise SystemExit("the merge map failed to load or changed while freezing; freeze again")
    teams = pd.DataFrame(rows)
    teams["team_id_master"] = teams["team_id_master"].astype(str)
    if teams["team_id_master"].duplicated().any():
        raise SystemExit("duplicate team_id_master in the teams snapshot")
    merge_map = pd.DataFrame(merges)
    if merge_map["deprecated_team_id"].duplicated().any():
        raise SystemExit("duplicate deprecated_team_id in the merge snapshot")
    teams.to_parquet(out / "teams-metadata.parquet", index=False)
    merge_map.to_parquet(out / "merge-map.parquet", index=False)
    write_json(
        out / "freeze-manifest.json",
        {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "today": str(today.date()),
            "code_head": git(code_root, "rev-parse", "HEAD").strip(),
            "games_source": games_source,
            "games_rows": len(games),
            "fetch_lookback_days": lookback_days,
            # None when the games were reused: their fetch code is unknown.
            "fetch_code_sha256": None if args.games_from else fetch_fingerprint(code_root),
            "metadata_ids_requested": len(ids),
            # Game team ids merged away since the games were resolved; drift when they were reused.
            "team_ids_deprecated_in_merge_map": len(set(ids) & set(snapshot)),
            "teams_rows": len(teams),
            "teams_missing": len(set(ids) - set(teams["team_id_master"])),
            "teams_with_state": int(teams["state_code"].fillna("").astype(str).str.strip().ne("").sum()),
            "teams_with_league": int(teams["league"].notna().sum()),
            "teams_deprecated": int(teams["is_deprecated"].fillna(False).astype(bool).sum()),
            "merge_rows": len(merge_map),
            **{key: digest(out / name) for name, key in FROZEN_FILES.items()},
            "network_policy": "GET/HEAD only",
        },
    )
    print((out / "freeze-manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- frozen stand-in
class FrozenQuery:
    """Accepts only the calls the engine makes, once each; anything wider raises BlockedCall.

    A TypeError from a stricter signature would be an ordinary Exception, which the engine's
    deprecated-team check catches and skips.
    """

    def __init__(self, client: FrozenClient, table: str):
        self._client = client
        self._table = table
        self._columns: list[str] | None = None
        self._in: tuple[str, set[str]] | None = None
        self._eq: list[tuple[str, object]] = []
        self._order: str | None = None
        self._range: tuple[int, int] | None = None

    def _refuse(self, call: str) -> BlockedCall:
        return BlockedCall(f"{call} on {self._table} is not served")

    def select(self, *columns, **options):
        if options or len(columns) != 1 or self._columns is not None:
            raise self._refuse(f"select{columns} {options}")
        self._columns = [c.strip() for c in columns[0].split(",")]
        return self

    def in_(self, column, values, *rest, **options):
        if rest or options or self._in is not None:
            raise self._refuse(f"in_({column!r}, ..., {rest}, {options})")
        self._in = (column, {str(v) for v in values})
        return self

    def eq(self, column, value, *rest, **options):
        if rest or options:
            raise self._refuse(f"eq({column!r}, {value!r}, {rest}, {options})")
        self._eq.append((column, value))
        return self

    def order(self, column, *rest, desc=False, **options):
        if rest or options or desc or self._order is not None:
            raise self._refuse(f"order({column!r}, {rest}, desc={desc}, {options})")
        self._order = column
        return self

    def range(self, start, end, *rest, **options):
        # postgrest-py appends a second offset/limit pair to a reused builder; refuse it here too.
        if rest or options or self._range is not None:
            raise self._refuse(f"range({start}, {end}, {rest}, {options})")
        self._range = (start, end)
        return self

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise self._refuse(f"query method {name!r}")

    def execute(self):
        shape = self._shape()
        try:
            rows = self._client.serve(self._table, shape, self)
        except BlockedCall:
            raise
        except Exception as error:
            raise BlockedCall(f"serving {shape} failed: {error!r}") from error
        self._client.calls[shape] = self._client.calls.get(shape, 0) + 1
        return SimpleNamespace(data=rows, count=None)

    def _shape(self) -> str:
        parts = [self._table, "select(" + ",".join(self._columns or []) + ")"]
        if self._in:
            parts.append(f"in_({self._in[0]})")
        parts.extend(f"eq({c})" for c, _ in self._eq)
        if self._order:
            parts.append(f"order({self._order})")
        if self._range:
            parts.append("range")
        return ".".join(parts)


class FrozenClient:
    """Serves the three read shapes compute_all_cohorts and MergeResolver make with games passed in."""

    TEAMS_METADATA = "teams.select(team_id_master,state_code,league).in_(team_id_master)"
    TEAMS_DEPRECATED = "teams.select(team_id_master).in_(team_id_master).eq(is_deprecated)"
    MERGE_PAGE = "team_merge_map.select(deprecated_team_id,canonical_team_id).range"

    def __init__(self, teams: pd.DataFrame, merge_map: pd.DataFrame):
        # PostgREST returns JSON null, never NaN: a NaN state_code is truthy and would
        # become a fake state in compute_all_cohorts' metadata map.
        teams = teams.astype(object).where(teams.notna(), None)
        self._teams = {row["team_id_master"]: row for row in teams.to_dict("records")}
        self._merges = sorted(merge_map.to_dict("records"), key=lambda r: str(r["deprecated_team_id"]))
        self.calls: dict[str, int] = {}

    def table(self, name: str):
        if name not in {"teams", "team_merge_map"}:
            raise BlockedCall(f"table {name!r} is not served")
        return FrozenQuery(self, name)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise BlockedCall(f"client attribute {name!r} is not served")

    def serve(self, table: str, shape: str, query: FrozenQuery) -> list[dict]:
        if shape == self.MERGE_PAGE:
            start, end = query._range
            return [{c: r[c] for c in query._columns} for r in self._merges[start : end + 1]]
        if shape in (self.TEAMS_METADATA, self.TEAMS_DEPRECATED):
            column, values = query._in
            if column != "team_id_master":
                raise BlockedCall(f"in_ on {column!r} is not served")
            if len(values) > 100:
                raise BlockedCall("in_ batch above 100 ids (production batches at 100)")
            hits = [self._teams[v] for v in values if v in self._teams]
            for col, val in query._eq:
                if col != "is_deprecated" or val is not True:
                    raise BlockedCall(f"eq({col}={val!r}) is not served")
                hits = [r for r in hits if r.get("is_deprecated") is not None and bool(r["is_deprecated"])]
            return [{c: r.get(c) for c in query._columns} for r in hits]
        raise BlockedCall(f"query shape {shape!r} is not served")


# ---------------------------------------------------------------------------- board
def environment(layer13) -> dict:
    versions = {}
    for package in ("pandas", "numpy", "xgboost", "scikit-learn"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    # Layer 13 falls back to RandomForest without xgboost, and skips ML without either.
    return {
        "python": platform.python_version(),
        **versions,
        "ml_available": bool(layer13._HAS_ML),
        "xgboost_used": bool(layer13._HAS_XGB),
    }


def loaded_module_sha256(code_root: Path) -> dict[str, str]:
    loaded = {}
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path and code_root in Path(path).resolve().parents:
            loaded[Path(path).resolve().relative_to(code_root).as_posix()] = digest(Path(path))
    return dict(sorted(loaded.items()))


def cmd_board(args) -> None:
    code_root = Path(args.code_root).resolve()
    freeze_dir = Path(args.freeze).resolve()
    out = Path(args.out).resolve()
    manifest = load_freeze(freeze_dir)
    today = manifest.get("today")
    if not today:
        raise SystemExit("the freeze manifest records no today; freeze again with this script")
    out.mkdir(parents=True, exist_ok=False)
    os.chdir(out)  # the engine's results cache writes to ./data/cache

    cleared = sorted(k for k in os.environ if k.startswith(ENV_DIAL_PREFIXES))
    for key in cleared:
        os.environ.pop(key)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=[logging.FileHandler(out / "run.log", encoding="utf-8"), logging.StreamHandler()],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("shadow")

    sys.path.insert(0, str(code_root))
    from dataclasses import asdict

    from src.etl import glicko_engine
    from src.etl.glicko_config import GlickoConfig
    from src.rankings import calculator
    from src.rankings import layer13_predictive_adjustment as layer13
    from src.utils.merge_resolver import MergeResolver

    # config/settings.py loads the code root's .env and .env.local on import, which can refill cleared dials.
    reloaded = sorted(k for k in os.environ if k.startswith(ENV_DIAL_PREFIXES))
    if reloaded:
        raise SystemExit(f"{reloaded} were reloaded from {code_root}'s .env or .env.local; remove them there")
    for module in (calculator, glicko_engine):
        if code_root not in Path(module.__file__).resolve().parents:
            raise SystemExit(f"{module.__name__} imported from {module.__file__}, not {code_root}")

    client = FrozenClient(
        pd.read_parquet(freeze_dir / "teams-metadata.parquet"), pd.read_parquet(freeze_dir / "merge-map.parquet")
    )
    resolver = MergeResolver(client)
    resolver.load_merge_map()
    if resolver.version in ("error", "no_merges"):
        raise SystemExit(f"merge map did not load from the frozen snapshot (version {resolver.version})")

    fetch_sha = manifest.get("fetch_code_sha256")
    fetch_not_measured = None
    if fetch_sha is not None:
        candidate_prints = fetch_fingerprint(code_root)
        fetch_not_measured = sorted(k for k, sha in fetch_sha.items() if candidate_prints.get(k) != sha)
    window = calculator._effective_fetch_lookback_days(365, use_glicko=True)
    if manifest.get("fetch_lookback_days") not in (None, window):
        fetch_not_measured = [
            *(fetch_not_measured or []),
            f"fetch window {manifest['fetch_lookback_days']} -> {window} days",
        ]
    if fetch_not_measured:
        log.warning(
            "games-fetch code differs from the freeze's and is not measured by this board: %s", fetch_not_measured
        )
    pinned = pd.Timestamp(today, tz="UTC")
    write_json(
        out / "provenance.json",
        {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "today": today,
            "last_calculated_pinned_to": str(pinned),
            "code_root": str(code_root),
            "code_head": git(code_root, "rev-parse", "HEAD").strip(),
            "code_diff_sha256": hashlib.sha256(git(code_root, "diff", "HEAD").encode()).hexdigest(),
            "engine_file_sha256": {f: digest(code_root / f) for f in ENGINE_FILES},
            "fetch_code_not_measured": fetch_not_measured,
            "games_sha256": manifest["games_sha256"],
            "freeze_dir": str(freeze_dir),
            "freeze_manifest": manifest,
            "merge_version": resolver.version,
            "env_dials_cleared": cleared,
            "environment": environment(layer13),
            "glicko_config": asdict(GlickoConfig()),
            "ml_config": asdict(layer13.Layer13Config()),
            "persistence": "all flags false; frozen in-memory client; no network",
            "ceiling_connectivity_enabled": bool(getattr(args, "ceiling_connectivity", False)),
            "capture_stages": bool(getattr(args, "capture_stages", False)),
            "tool_sha256": {
                name: digest(Path(__file__).with_name(name))
                for name in ("shadow_harness.py", "c1_validation.py")
            },
        },
    )

    captured: list[str] = []
    original_caps = calculator._compute_publication_cap_scores
    original_v2 = calculator.compute_rankings_v2
    stages = StageCapture(calculator, out) if getattr(args, "capture_stages", False) else None
    if stages:
        stages.install()

    def capture_caps(teams_age, base):
        frame = teams_age.copy(deep=True)
        frame["shadow_pre_cap_score"] = base
        age = int(frame["age_num"].iloc[0])
        path = out / f"pre-cap-u{age}.parquet"
        if path.exists():
            raise BlockedCall(f"duplicate pre-cap capture for age {age}")
        frame.to_parquet(path, index=False)
        captured.append(path.name)
        return original_caps(teams_age, base)

    def stamp_pinned_day(*call_args, **call_kwargs):
        result = original_v2(*call_args, **call_kwargs)
        # The engine rates as of the freeze's day but stamps the wall clock, which the evidence gates
        # read; production's run day is both, so pin the stamp to keep boards from different days comparable.
        result["teams"]["last_calculated"] = pinned
        if stages:
            stages.engine(result, call_kwargs)
        return result

    calculator._compute_publication_cap_scores = capture_caps
    calculator.compute_rankings_v2 = stamp_pinned_day
    games_df = pd.read_parquet(freeze_dir / "games.parquet")
    log.info("shadow board: %s rows from frozen games, code root %s", f"{len(games_df):,}", code_root)
    result = asyncio.run(
        calculator.compute_all_cohorts(
            client,
            games_df=games_df,
            today=pd.Timestamp(today),
            fetch_from_supabase=False,
            lookback_days=365,
            force_rebuild=True,
            merge_resolver=resolver,
            use_glicko=True,
            persist_game_residuals=False,
            persist_game_explainability=False,
            calculate_rank_changes_enabled=False,
            save_snapshot=False,
            **({"ceiling_connectivity_enabled": True} if getattr(args, "ceiling_connectivity", False) else {}),
        )
    )
    calculator._compute_publication_cap_scores = original_caps
    calculator.compute_rankings_v2 = original_v2
    if not captured:
        raise SystemExit("the engine produced no pre-cap checkpoints")
    stage_capture = stages.close() if stages else None

    if getattr(args, "ceiling_connectivity", False):
        connectivity = result.get("ceiling_connectivity")
        calculator._validate_ceiling_connectivity(connectivity)
        if set(connectivity["team_id"]) != set(result["teams"]["team_id"]):
            raise SystemExit("Ceiling connectivity coverage differs from output teams")
        connectivity.to_parquet(out / "ceiling-connectivity.parquet", index=False)

    result["teams"].to_parquet(out / "teams.parquet", index=False)
    for key, name, columns in (
        (
            "games_used",
            "games-used.parquet",
            ("team_id", "opp_id", "game_id", "id", "date", "age", "opp_age", "selection_bucket"),
        ),
        (
            "game_explainability",
            "explainability.parquet",
            ("team_id", "opp_id", "game_id", "id", "game_date", "team_mu", "opp_mu", "opp_sigma"),
        ),
    ):
        frame = result[key]
        frame[[c for c in columns if c in frame.columns]].to_parquet(out / name, index=False)
    write_json(
        out / "completed.json",
        {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "teams": len(result["teams"]),
            "pre_cap_files": {name: digest(out / name) for name in sorted(captured)},
            "teams_sha256": digest(out / "teams.parquet"),
            "frozen_client_calls": client.calls,
            "loaded_module_sha256": loaded_module_sha256(code_root),
            "stage_capture": stage_capture,
            "output_sha256": {
                name: digest(out / name)
                for name in ("teams.parquet", "games-used.parquet", "explainability.parquet")
            },
            **({"ceiling_connectivity_sha256": digest(out / "ceiling-connectivity.parquet")}
               if getattr(args, "ceiling_connectivity", False) else {}),
        },
    )
    log.info("shadow board complete: %s teams; frozen client calls %s", f"{len(result['teams']):,}", client.calls)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    freeze = sub.add_parser("freeze", help="read production inputs once, GET only")
    freeze.add_argument("--code-root", required=True, help="worktree at origin/main whose fetch reads the games")
    freeze.add_argument("--env-file", required=True, help="root .env with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    freeze.add_argument("--today", required=True, help="pinned as-of date, YYYY-MM-DD; normally today's UTC date")
    freeze.add_argument("--out", required=True, help="new freeze directory; must not exist")
    freeze.add_argument("--games-from", help="reuse this saved games snapshot instead of fetching games")
    board = sub.add_parser("board", help="one engine run on a freeze")
    board.add_argument("--code-root", required=True, help="worktree holding the code version to run")
    board.add_argument("--freeze", required=True, help="freeze directory from the freeze command")
    board.add_argument("--out", required=True, help="new run directory; must not exist")
    board.add_argument("--capture-stages", action="store_true", help="capture both passes and upstream adjustments")
    board.add_argument("--ceiling-connectivity", action="store_true", help="C1: restore connectivity only to ceilings")
    args = parser.parse_args()
    if getattr(args, "ceiling_connectivity", False) and not args.capture_stages:
        parser.error("--ceiling-connectivity requires --capture-stages")
    {"freeze": cmd_freeze, "board": cmd_board}[args.cmd](args)


if __name__ == "__main__":
    main()
