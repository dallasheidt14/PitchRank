import csv
import os
from pathlib import Path

from dotenv import load_dotenv

from supabase import create_client

CSV_PATH = Path("scrapers/modular11_scraper/output/modular11_results_20260318_161741.csv")


def norm_team_id(x) -> str:
    """
    Match the normalization logic used by the Modular11 UID generator:
    - turn numeric-like provider IDs into clean integer strings
    - otherwise keep as string (e.g. "name:foo")
    """
    if x is None:
        return ""
    s = str(x).strip()
    if s == "" or s.lower() == "none":
        return ""
    try:
        return str(int(float(s)))
    except Exception:
        return s


def make_modular11_uids(row: dict) -> tuple[str, str] | None:
    """
    Produce both UID formats that PitchRank uses for Modular11:

    1) New format (age+division suffix):
       modular11:{date}:{sorted_team1}:{sorted_team2}:{age_group}:{division}

    2) Legacy format (no age/division):
       modular11:{date}:{sorted_team1}:{sorted_team2}
    """
    provider = "modular11"
    game_date = (row.get("game_date") or "").strip()
    t1 = row.get("team_id") or ""
    t2 = row.get("opponent_id") or ""
    age = (row.get("age_group") or "").strip().upper()
    div = (row.get("mls_division") or "").strip().upper()

    a = norm_team_id(t1)
    b = norm_team_id(t2)
    if not game_date or not a or not b or not age or not div:
        return None

    s1, s2 = sorted([a, b])
    legacy_uid = f"{provider}:{game_date}:{s1}:{s2}"
    new_uid = f"{provider}:{game_date}:{s1}:{s2}:{age}:{div}"
    return new_uid, legacy_uid


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV not found: {CSV_PATH}")

    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not supabase_url or not supabase_key:
        raise SystemExit("Missing Supabase env vars (load .env.local)")

    supabase = create_client(supabase_url, supabase_key)

    providers_result = supabase.table("providers").select("id").eq("code", "modular11").execute()
    if not providers_result.data:
        raise SystemExit("Modular11 provider not found in providers table")
    modular11_provider_id = providers_result.data[0]["id"]

    unique_new_uids: set[str] = set()
    new_uid_to_legacy: dict[str, str] = {}

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uids = make_modular11_uids(row)
            if not uids:
                continue
            new_uid, legacy_uid = uids
            if new_uid not in unique_new_uids:
                unique_new_uids.add(new_uid)
                new_uid_to_legacy[new_uid] = legacy_uid

    new_uids = list(unique_new_uids)
    print(f"Unique U16 new game_uids in CSV: {len(new_uids)}")

    # Modular11 backward compat: DB may contain legacy game_uids without age/division.
    legacy_uids = list({new_uid_to_legacy[nu] for nu in new_uids})
    existing_legacy: set[str] = set()

    batch_size = 100
    for batch in chunked(legacy_uids, batch_size):
        res = (
            supabase.table("games")
            .select("game_uid")
            .eq("provider_id", modular11_provider_id)
            .in_("game_uid", batch)
            .execute()
        )
        for r in res.data or []:
            gid = r.get("game_uid")
            if gid:
                existing_legacy.add(gid)

    existing_new = {nu for nu, lu in new_uid_to_legacy.items() if lu in existing_legacy}
    missing_new = set(new_uids) - existing_new

    print(f"Already in DB (legacy matches): {len(existing_new)}")
    print(f"Missing from DB (would import, new_uids): {len(missing_new)}")

    out_dir = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    existing_path = out_dir / "modular11_u16_last120days_existing_game_uids.csv"
    missing_path = out_dir / "modular11_u16_last120days_missing_game_uids.csv"

    # Existing file: show both new and legacy uids for clarity.
    with open(existing_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_uid_new", "game_uid_legacy"])
        for nu in sorted(existing_new):
            w.writerow([nu, new_uid_to_legacy.get(nu, "")])

    with open(missing_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_uid_new"])
        for nu in sorted(missing_new):
            w.writerow([nu])

    print(f"Wrote: {existing_path}")
    print(f"Wrote: {missing_path}")

    print("\nExisting game_uids (already in DB, mapped from legacy):")
    for uid in sorted(existing_new):
        print(uid)


if __name__ == "__main__":
    main()
