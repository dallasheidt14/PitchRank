"""Read-only selection replay; deliberately does not calculate new ratings."""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import select_games_balanced


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.freeze / "freeze-manifest.json").read_text())
    assert sha(args.freeze / "games.parquet") == manifest["games_sha256"]
    today = pd.Timestamp(manifest["today"])
    cfg = GlickoConfig()
    assert (cfg.MAX_GAMES, cfg.WINDOW_DAYS, cfg.WINDOW_GRACE_DAYS, cfg.BALANCED_SELECTION_ENABLED) == (
        30,
        365,
        0,
        False,
    )
    sources = {
        str(p): sha(ROOT / p)
        for p in ("src/etl/glicko_config.py", "src/etl/glicko_engine.py", "src/rankings/calculator.py")
    }
    raw = pd.read_parquet(args.freeze / "games.parquet")
    assert raw.date.max() <= today
    # This is the fetch-window delta over already-resolved saved rows, not a fresh database freeze.
    expired = raw.loc[raw.date < today - pd.Timedelta(days=365)]
    eligible_input = raw.loc[raw.date.between(today - pd.Timedelta(days=365), today)]
    teams = pd.read_parquet(
        args.baseline / "teams.parquet", columns=["team_id", "age", "gender", "status", "games_played"]
    )
    before = pd.read_parquet(args.baseline / "games-used.parquet", columns=["team_id", "game_id", "opp_id"])
    assert not before.duplicated(["team_id", "game_id"]).any()
    expected_counts = before.groupby("team_id").size().reindex(teams.team_id, fill_value=0).to_numpy()
    assert (expected_counts == teams.games_played.to_numpy()).all()
    ids = set(teams.team_id)
    selected_parts = []
    for index, (team_id, group) in enumerate(raw.loc[raw.team_id.isin(ids)].groupby("team_id", sort=False), 1):
        selected = select_games_balanced(group, team_id, cfg, today)
        # Independent date/ID ordering oracle checks the actual selector on every team.
        oracle = (
            group.loc[group.date.between(today - pd.Timedelta(days=365), today)]
            .sort_values(["date", "game_id", "id", "opp_id"], ascending=[False, True, True, True], kind="mergesort")
            .head(30)
        )
        assert selected.game_id.tolist() == oracle.game_id.tolist()
        selected_parts.append(selected[["team_id", "game_id", "opp_id", "date"]])
        if index % 20000 == 0:
            print(f"Verified selection for {index} teams", flush=True)
    after = pd.concat(selected_parts, ignore_index=True)
    assert not after.duplicated(["team_id", "game_id"]).any()
    delta = before.merge(after[["team_id", "game_id"]], how="outer", on=["team_id", "game_id"], indicator=True)
    removed = delta.loc[delta._merge == "left_only", ["team_id", "game_id", "opp_id"]]
    added = delta.loc[delta._merge == "right_only", ["team_id", "game_id"]].merge(after, on=["team_id", "game_id"])
    counts = after.groupby("team_id").size()
    last = after.groupby("team_id").date.max()
    teams["new_games"] = teams.team_id.map(counts).fillna(0).astype(int)
    teams["new_last_game"] = teams.team_id.map(last)
    teams["new_status"] = "Not Enough Ranked Games"
    teams.loc[teams.new_games >= cfg.MIN_GAMES_PROVISIONAL, "new_status"] = "Active"
    teams.loc[
        teams.new_last_game.isna() | (teams.new_last_game < today - pd.Timedelta(days=cfg.INACTIVE_DAYS)), "new_status"
    ] = "Inactive"
    changed_ids = set(removed.team_id) | set(added.team_id)
    teams["selection_changed"] = teams.team_id.isin(changed_ids)
    teams["removed"] = teams.team_id.map(removed.groupby("team_id").size()).fillna(0).astype(int)
    teams["added"] = teams.team_id.map(added.groupby("team_id").size()).fillna(0).astype(int)

    def counts_for(t):
        return dict(
            teams=len(t),
            active_before=int((t.status == "Active").sum()),
            selection_changed=int(t.selection_changed.sum()),
            active_selection_changed=int(((t.status == "Active") & t.selection_changed).sum()),
            removed_perspectives=int(t.removed.sum()),
            added_perspectives=int(t.added.sum()),
            crosses_12_down=int(((t.games_played >= 12) & (t.new_games < 12)).sum()),
            crosses_12_up=int(((t.games_played < 12) & (t.new_games >= 12)).sum()),
            active_to_ineligible=int(((t.status == "Active") & (t.new_status != "Active")).sum()),
            ineligible_to_active=int(((t.status != "Active") & (t.new_status == "Active")).sum()),
            reaches_zero=int(((t.games_played > 0) & (t.new_games == 0)).sum()),
        )

    output = dict(
        created_at=datetime.now(timezone.utc).isoformat(),
        as_of=str(today.date()),
        scope="Exact game-selection replay for the archived release team universe; no new ratings or publication",
        inputs={
            str(p): sha(p)
            for p in [
                args.freeze / "games.parquet",
                args.freeze / "freeze-manifest.json",
                args.baseline / "games-used.parquet",
                args.baseline / "teams.parquet",
            ]
        },
        source_sha256=sources,
        input_window=dict(
            before_perspectives=len(raw),
            after_perspectives=len(eligible_input),
            removed_perspectives=len(expired),
            removed_unique_games=expired.game_id.nunique(),
            removed_game_teams=len(set(expired.team_id) | set(expired.opp_id)),
            added_perspectives=0,
            deprecated_merge_drift=manifest["team_ids_deprecated_in_merge_map"],
        ),
        selection={
            **counts_for(teams),
            "before_perspectives": len(before),
            "after_perspectives": len(after),
            "unique_games_with_removed_perspective": removed.game_id.nunique(),
            "unique_games_with_added_perspective": added.game_id.nunique(),
            "counterpart_teams_on_changed_perspectives": len(set(removed.opp_id) | set(added.opp_id)),
        },
        boards=[
            dict(age=str(age), gender=str(gender), **counts_for(t))
            for (age, gender), t in teams.groupby(["age", "gender"])
        ],
        limits=[
            "Saved resolved rows cannot reveal current database or merge drift.",
            "This replays the 393-to-365-day fetch-window change, not a fresh production query.",
            "Final ranking movement and strength-of-schedule changes require a new full ranking calculation.",
            "No October outcomes or prediction scoring were accessed.",
        ],
    )
    assert len(output["boards"]) == 18
    assert len(before) - len(removed) + len(added) == len(after)
    assert all(sha(ROOT / p) == value for p, value in sources.items())
    for name, frame in [
        ("per-team.parquet", teams),
        ("removed.parquet", removed),
        ("added.parquet", added),
        ("selected.parquet", after),
    ]:
        frame.to_parquet(args.out / name, index=False)
    output["output_sha256"] = {p.name: sha(p) for p in args.out.glob("*.parquet")}
    (args.out / "completed.json").write_text(json.dumps(output, indent=2, default=int) + "\n")
    print(json.dumps(output["selection"], indent=2), flush=True)


if __name__ == "__main__":
    main()
