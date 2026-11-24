#!/usr/bin/env python3
"""
Opponent-frontier enqueue: queue GotSport teams that just appeared as someone
else's opponent and that we have never scraped ourselves this season, at
priority 2, via the enqueue_scrape_request RPC.

A team we never scrape holds only the games that happened to show up on other
teams' pages, so a fresh sighting as an opponent is the best sign it has games we
do not. On a day with none, the same candidates that we last scraped at least
--rescrape-after-days ago, and that have been sighted again since, are queued
instead, under their own request type so the two rules can be measured apart.

Every run in GitHub Actions logs counts only: the repo is public, and GotSport ids
are kept from public reads on purpose. A local dry run also lists the first 20
targets.

Does NOT scrape. process_missing_games (every 15min) drains.

Usage:
    python scripts/enqueue_opponent_frontier.py --dry-run
    python scripts/enqueue_opponent_frontier.py
    python scripts/enqueue_opponent_frontier.py --limit 500 --window-days 7 --rescrape-after-days 14
"""

import argparse
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

# Windows SSL workaround. Optional — CI runners use the system trust store.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv  # noqa: E402
from postgrest.exceptions import APIError  # noqa: E402

from supabase import create_client  # noqa: E402

load_dotenv(".env.local")
load_dotenv(".env")

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.enqueue_helpers import (  # noqa: E402
    PAGE_SIZE,
    _chunks,
    _keyset,
    expand_to_aliases,
    load_team_rows,
    resolve_merges,
)
from src.utils.placeholder_team_names import is_placeholder_team_name  # noqa: E402
from src.utils.provider_ids import is_blank_provider_id  # noqa: E402
from src.utils.team_utils import _soccer_season_year, scrape_excluded_birth_years  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
# httpx logs every PostgREST URL at INFO, team ids included, and Actions output is public.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

GOTSPORT_PROVIDER_CODE = "gotsport"
PRIORITY_OPPONENT_FRONTIER = 2
REQUEST_TYPE = "opponent_frontier"
RESCRAPE_REQUEST_TYPE = "opponent_frontier_rescrape"

DEFAULT_LIMIT = 1000
DEFAULT_WINDOW_DAYS = 7
DEFAULT_RESCRAPE_AFTER_DAYS = 14
ERROR_COOLDOWN_DAYS = 7

# config.settings.AGE_GROUPS, which cannot be imported under the workflow's install.
BOARD_AGE_GROUPS = frozenset({"u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19"})

MIN_CANDIDATES_FOR_LOG_GUARD = 100

SOURCE_ID_RE = re.compile(r"https://rankings\.gotsport\.com/teams/([0-9]{1,12})/")
GOTSPORT_ID_RE = re.compile(r"[0-9]{1,12}")

ALREADY_QUEUED = "23505"
STUCK_PROCESSING = "55000"

GAME_COLUMNS = (
    "id,game_date,created_at,home_team_master_id,away_team_master_id,"
    "home_provider_id,away_provider_id,home_score,away_score,is_excluded,source_url"
)
TEAM_COLUMNS = "team_id_master,team_name,provider_id,provider_team_id,age_group,birth_year,is_deprecated"
SCRAPED_STATUSES = frozenset({"success", "partial"})

GAME_SKIPS = (
    "home_score_null",
    "away_score_null",
    "excluded_game",
    "before_season",
    "after_today",
    "source_matches_neither",
    "source_matches_both",
    "opponent_master_null",
    "opponent_id_blank",
    "self_game",
)
TEAM_SKIPS = ("no_team_row", "deprecated", "not_on_board", "excluded_birth_year", "ranking_excluded")
CANDIDATE_SKIPS = (
    "recent_error",
    "id_not_linked",
    "id_malformed",
    "placeholder_name",
    "scraped_this_season",
    "rescrape_too_recent",
    "rescrape_no_new_sighting",
    "over_limit",
)
OUTCOMES = ("enqueued", "already_queued", "stuck_processing", "failed")


@dataclass
class Selection:
    targets: list = field(default_factory=list)
    list_name: str = "primary"
    raw_rows: int = 0
    kept_rows: int = 0
    folded_teams: int = 0
    candidates: int = 0
    verdict: str | None = None
    stats: Counter = field(default_factory=Counter)


def get_gotsport_provider_id(supabase):
    r = supabase.table("providers").select("id").eq("code", GOTSPORT_PROVIDER_CODE).single().execute()
    if not r.data:
        raise RuntimeError(f"Provider '{GOTSPORT_PROVIDER_CODE}' not found")
    return r.data["id"]


def season_start_date(today):
    """Aug 1 of today's season, for comparing with games.game_date."""
    return date(_soccer_season_year(today), 8, 1)


def season_start_instant(today):
    """Aug 1 of today's season at 00:00 UTC, for comparing with timestamps."""
    return datetime(_soccer_season_year(today), 8, 1, tzinfo=timezone.utc)


def _instant(value):
    """A PostgREST timestamp as an aware UTC datetime; a naive one is read as UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_window_games(supabase, provider_id, since_iso):
    """The provider's games saved at or after since_iso, each once.

    Ordered by created_at then id, which idx_games_created_at serves; ordered by id
    alone the read walks the primary key and filters millions of rows. Offset paging
    holds because neither filter column changes after insert. An import committing
    mid-read can shift later pages, repeating a few rows (dropped here) and leaving
    its own rows to the next day's overlapping window.
    """
    games, seen, offset = [], set(), 0
    while True:
        page = (
            supabase.table("games")
            .select(GAME_COLUMNS)
            .eq("provider_id", provider_id)
            .gte("created_at", since_iso)
            .order("created_at")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        for g in page:
            if g["id"] not in seen:
                seen.add(g["id"])
                games.append(g)
        if len(page) < PAGE_SIZE:
            return games
        offset += PAGE_SIZE


def _game_skip(game, season_day, today):
    if game["home_score"] is None:
        return "home_score_null"
    if game["away_score"] is None:
        return "away_score_null"
    if game["is_excluded"] is True:
        return "excluded_game"
    game_day = date.fromisoformat(game["game_date"])
    if game_day < season_day:
        return "before_season"
    # A scored row dated in the future is not evidence the team played.
    if game_day > today:
        return "after_today"
    return None


def _sighting(game, season_day, today):
    """(skip reason, None), or (None, (opponent master, source master or None, opponent GotSport id, created_at)).

    A team-page import names its own team in source_url, so the other side is the
    opponent that page revealed. A row whose source names neither side (the event
    scraper writes schedule URLs) or both cannot say which side was revealed.
    """
    reason = _game_skip(game, season_day, today)
    if reason is not None:
        return reason, None
    match = SOURCE_ID_RE.match(game["source_url"] or "")
    source_id = match.group(1) if match else None
    home_is_source = source_id is not None and game["home_provider_id"] == source_id
    away_is_source = source_id is not None and game["away_provider_id"] == source_id
    if home_is_source and away_is_source:
        return "source_matches_both", None
    if not (home_is_source or away_is_source):
        return "source_matches_neither", None
    source, opponent = ("home", "away") if home_is_source else ("away", "home")
    if game[f"{opponent}_team_master_id"] is None:
        return "opponent_master_null", None
    if is_blank_provider_id(game[f"{opponent}_provider_id"]):
        return "opponent_id_blank", None
    return None, (
        game[f"{opponent}_team_master_id"],
        game[f"{source}_team_master_id"],
        game[f"{opponent}_provider_id"],
        _instant(game["created_at"]),
    )


def opponent_sightings(games, season_day, today):
    """Each unskipped game's sighting, and a count of the games skipped for each reason."""
    rows, skips = [], Counter()
    for game in games:
        reason, sighting = _sighting(game, season_day, today)
        if reason is None:
            rows.append(sighting)
        else:
            skips[reason] += 1
    return rows, skips


def ranking_excluded_canonicals(supabase):
    """Survivors of every team_ranking_exclusions row: the ranking run drops every game they touch."""
    rows = _keyset(lambda: supabase.table("team_ranking_exclusions").select("team_id_master"), key="team_id_master")
    return set(resolve_merges(supabase, {r["team_id_master"] for r in rows}).values())


def _team_skip(row, team_id, excluded_years, excluded_teams):
    if row is None:
        return "no_team_row"
    # The SQL selectors test is_deprecated = false, so NULL counts as deprecated.
    if row["is_deprecated"] is not False:
        return "deprecated"
    if (row["age_group"] or "").strip().lower() not in BOARD_AGE_GROUPS:
        return "not_on_board"
    if row["birth_year"] in excluded_years:
        return "excluded_birth_year"
    if team_id in excluded_teams:
        return "ranking_excluded"
    return None


def own_scrape_status(supabase, provider_id, group, season_at, cooldown_start):
    """Each candidate's newest own GotSport scrape this season, and who errored since cooldown_start.

    team_scrape_log is not repointed by merges, so it is read under every id in the
    merge group. Also returns the number of rows read, of any status.
    """
    since = min(season_at, cooldown_start).isoformat()
    newest, errors, read = {}, set(), 0
    for batch in _chunks(sorted(group)):
        rows = _keyset(
            lambda batch=batch: (
                supabase.table("team_scrape_log")
                .select("id,team_id,status,scraped_at")
                .eq("provider_id", provider_id)
                .in_("team_id", batch)
                .gte("scraped_at", since)
            )
        )
        read += len(rows)
        for r in rows:
            team = group[r["team_id"]]
            at = _instant(r["scraped_at"])
            if r["status"] in SCRAPED_STATUSES and at >= season_at and (team not in newest or at > newest[team]):
                newest[team] = at
            if r["status"] == "error" and at >= cooldown_start:
                errors.add(team)
    return newest, errors, read


def recently_failed(supabase, group, cooldown_start):
    """Candidates holding a request that failed since cooldown_start, under any provider.

    Every scrape is a GotSport scrape whatever provider the row names, and this also
    covers a failure whose log write was lost.
    """
    since = cooldown_start.isoformat()
    failed = set()
    for batch in _chunks(sorted(group)):
        rows = _keyset(
            lambda batch=batch: (
                supabase.table("scrape_requests")
                .select("id,team_id_master")
                .eq("status", "failed")
                .gte("completed_at", since)
                .in_("team_id_master", batch)
            )
        )
        failed.update(group[r["team_id_master"]] for r in rows)
    return failed


def linked_gotsport_ids(supabase, provider_id, team_rows, group):
    """Each candidate's own GotSport id plus its approved GotSport aliases."""
    linked = defaultdict(set)
    for team_id, row in team_rows.items():
        if row["provider_id"] == provider_id and not is_blank_provider_id(row["provider_team_id"]):
            linked[team_id].add(row["provider_team_id"])
    for batch in _chunks(sorted(group)):
        rows = (
            supabase.table("team_alias_map")
            .select("team_id_master,provider_team_id")
            .eq("provider_id", provider_id)
            .eq("review_status", "approved")
            .in_("team_id_master", batch)
            .execute()
            .data
            or []
        )
        for r in rows:
            if not is_blank_provider_id(r["provider_team_id"]):
                linked[group[r["team_id_master"]]].add(r["provider_team_id"])
    return linked


def _most_seen(counts):
    """The id with the most sightings, ties to the smallest string."""
    return min(counts, key=lambda gotsport_id: (-counts[gotsport_id], gotsport_id))


def _pick(row, counts, request_type, order_key, stats):
    """The target for row's most-seen id, or None when the team's name is a placeholder for that id."""
    chosen = _most_seen(counts)
    if is_placeholder_team_name(row["team_name"], chosen):
        stats["placeholder_name"] += 1
        return None
    return {
        "team_id_master": row["team_id_master"],
        "team_name": row["team_name"],
        "provider_team_id": chosen,
        "request_type": request_type,
        "order_key": order_key,
    }


def select_targets(supabase, provider_id, now, window_days, rescrape_after_days, limit):
    """The day's targets, which list they came from, and a count for every row and team left out."""
    today = now.date()
    season_day = season_start_date(today)
    season_at = season_start_instant(today)
    cooldown_start = now - timedelta(days=ERROR_COOLDOWN_DAYS)
    result = Selection()

    games = fetch_window_games(supabase, provider_id, (now - timedelta(days=window_days)).isoformat())
    result.raw_rows = len(games)
    if not games:
        result.verdict = "no_games_read"
        return result

    rows, skips = opponent_sightings(games, season_day, today)
    result.stats.update(skips)
    masters = {opponent for opponent, _, _, _ in rows} | {source for _, source, _, _ in rows if source is not None}
    canonical = resolve_merges(supabase, masters)
    sightings = defaultdict(lambda: defaultdict(list))
    for opponent, source, gotsport_id, created_at in rows:
        team_id = canonical[opponent]
        if source is None:
            result.stats["source_master_null"] += 1
        elif canonical[source] == team_id:
            result.stats["self_game"] += 1
            continue
        sightings[team_id][gotsport_id].append(created_at)
        result.kept_rows += 1
    for by_id in sightings.values():
        for times in by_id.values():
            times.sort()

    result.folded_teams = len(sightings)
    if not sightings:
        return result
    team_rows = load_team_rows(supabase, set(sightings), TEAM_COLUMNS)
    excluded_years = set(scrape_excluded_birth_years(today))
    excluded_teams = ranking_excluded_canonicals(supabase)
    candidates = {}
    for team_id in sorted(sightings):
        reason = _team_skip(team_rows.get(team_id), team_id, excluded_years, excluded_teams)
        if reason is None:
            candidates[team_id] = team_rows[team_id]
        else:
            result.stats[reason] += 1
    result.candidates = len(candidates)
    if not candidates:
        return result

    group = expand_to_aliases(supabase, {t: t for t in candidates})
    newest_scrape, errored, log_rows = own_scrape_status(supabase, provider_id, group, season_at, cooldown_start)
    # An empty read would make every candidate look never scraped and fill the cap daily, green.
    if log_rows == 0 and len(candidates) >= MIN_CANDIDATES_FOR_LOG_GUARD:
        result.verdict = "scrape_log_empty"
        return result
    failed = recently_failed(supabase, group, cooldown_start)
    linked = linked_gotsport_ids(supabase, provider_id, candidates, group)

    usable = {}
    for team_id in sorted(candidates):
        if team_id in errored or team_id in failed:
            result.stats["recent_error"] += 1
            continue
        linked_ids = [gid for gid in sightings[team_id] if gid in linked.get(team_id, ())]
        # A malformed id scrapes nothing and logs partial, which would retire the team for the season.
        valid = {gid: sightings[team_id][gid] for gid in linked_ids if GOTSPORT_ID_RE.fullmatch(gid)}
        if not linked_ids:
            result.stats["id_not_linked"] += 1
        elif not valid:
            result.stats["id_malformed"] += 1
        else:
            usable[team_id] = valid

    primary = []
    for team_id, by_id in usable.items():
        if team_id in newest_scrape:
            continue
        counts = {gid: len(times) for gid, times in by_id.items()}
        first_seen = min(times[0] for times in by_id.values())
        target = _pick(candidates[team_id], counts, REQUEST_TYPE, first_seen, result.stats)
        if target is not None:
            primary.append(target)

    if primary:
        result.stats["scraped_this_season"] += sum(1 for team_id in usable if team_id in newest_scrape)
        targets = primary
    else:
        result.list_name = "rescrape"
        rescrape_before = now - timedelta(days=rescrape_after_days)
        targets = []
        for team_id, by_id in usable.items():
            if team_id not in newest_scrape:
                continue
            newest = newest_scrape[team_id]
            if newest > rescrape_before:
                result.stats["rescrape_too_recent"] += 1
                continue
            later = {gid: sum(1 for t in times if t > newest) for gid, times in by_id.items()}
            later = {gid: n for gid, n in later.items() if n}
            if not later:
                result.stats["rescrape_no_new_sighting"] += 1
                continue
            target = _pick(candidates[team_id], later, RESCRAPE_REQUEST_TYPE, newest, result.stats)
            if target is not None:
                targets.append(target)

    targets.sort(key=lambda t: (t["order_key"], t["team_id_master"]))
    if len(targets) > limit:
        result.stats["over_limit"] += len(targets) - limit
        targets = targets[:limit]
    result.targets = targets
    return result


def enqueue_team(supabase, target, provider_id, today_iso, dry_run):
    """Queue one target, returning its outcome.

    scrape_requests.game_date is NOT NULL, so it anchors on today; the drainer scrapes
    from the earlier of Aug 1 and 90 days before that date. A waiting compatible row is
    reused and only promoted, keeping its request_type and place in line.
    """
    if dry_run:
        return "would_enqueue"
    try:
        supabase.rpc(
            "enqueue_scrape_request",
            {
                "p_team_id_master": target["team_id_master"],
                "p_team_name": target["team_name"],
                "p_provider_id": provider_id,
                "p_provider_team_id": target["provider_team_id"],
                "p_game_date": today_iso,
                "p_request_type": target["request_type"],
                "p_priority": PRIORITY_OPPONENT_FRONTIER,
            },
        ).execute()
    except APIError as e:
        if e.code == ALREADY_QUEUED:
            return "already_queued"
        if e.code == STUCK_PROCESSING:
            return "stuck_processing"
        # Only PostgREST's own errors carry a string code and roll back. postgrest-py's int-coded error for
        # a body it could not parse (a gateway's 502 page) may, like the exceptions below, follow a committed call.
        if isinstance(e.code, str):
            logger.warning(f"Enqueue refused: APIError {e.code}")
        else:
            logger.warning(f"Enqueue outcome unknown: APIError {e.code}")
        return "failed"
    except Exception as e:
        logger.warning(f"Enqueue outcome unknown: {type(e).__name__}")
        return "failed"
    return "enqueued"


def _counts(stats, names):
    return ", ".join(f"{name} {stats[name]}" for name in names)


def summary_line(selection, outcomes, dry_run):
    s = selection.stats
    writer = f"would_enqueue {outcomes['would_enqueue']}" if dry_run else _counts(outcomes, OUTCOMES)
    return (
        f"Opponent frontier ran the {selection.list_name} list: {len(selection.targets)} targets. "
        f"Game rows: {selection.raw_rows} read = {selection.kept_rows} kept "
        f"({s['source_master_null']} with no source team) + {_counts(s, GAME_SKIPS)}. "
        f"Teams: {selection.folded_teams} sighted = {selection.candidates} candidates + {_counts(s, TEAM_SKIPS)}. "
        f"Candidates: {selection.candidates} = {len(selection.targets)} targets + {_counts(s, CANDIDATE_SKIPS)}. "
        f"Writer: {writer}."
    )


def _bounded_int(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}, got {number}")
        return number

    parse.__name__ = "integer"  # argparse names the type in its error: "invalid integer value"
    return parse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run every read and check without enqueueing")
    parser.add_argument("--limit", type=_bounded_int(1, 5000), default=DEFAULT_LIMIT)
    parser.add_argument(
        "--window-days",
        type=_bounded_int(1, 30),
        default=DEFAULT_WINDOW_DAYS,
        help=f"Read opponents from games saved within this many days (default {DEFAULT_WINDOW_DAYS})",
    )
    parser.add_argument(
        "--rescrape-after-days",
        type=_bounded_int(1, 90),
        default=DEFAULT_RESCRAPE_AFTER_DAYS,
        help=f"On a day with no never-scraped team, re-queue teams last scraped this many days ago "
        f"(default {DEFAULT_RESCRAPE_AFTER_DAYS})",
    )
    args = parser.parse_args()

    # The service-role key only: team_ranking_exclusions is closed to the anon key.
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    supabase = create_client(url, key)
    provider_id = get_gotsport_provider_id(supabase)
    now = datetime.now(timezone.utc)

    selection = select_targets(
        supabase,
        provider_id,
        now,
        window_days=args.window_days,
        rescrape_after_days=args.rescrape_after_days,
        limit=args.limit,
    )
    if selection.verdict == "no_games_read":
        logger.error(
            "Stopped before selecting: no GotSport games read from the window, which a working read never returns"
        )
        sys.exit(1)
    if selection.verdict == "scrape_log_empty":
        logger.error(
            f"Stopped before selecting: {selection.raw_rows} game rows and {selection.candidates} candidates read, "
            "but no team_scrape_log rows; refusing to treat every candidate as never scraped"
        )
        sys.exit(1)

    if args.dry_run and os.environ.get("GITHUB_ACTIONS") != "true":
        for t in selection.targets[:20]:
            logger.info(f"  WOULD ENQUEUE: {t['provider_team_id']} ({t['team_name']}) as {t['request_type']}")
        logger.info(f"...({len(selection.targets)} total)")

    today_iso = now.date().isoformat()
    outcomes = Counter()
    for t in selection.targets:
        outcomes[enqueue_team(supabase, t, provider_id, today_iso, args.dry_run)] += 1

    logger.info(summary_line(selection, outcomes, args.dry_run))
    if outcomes["stuck_processing"]:
        logger.error(
            f"{outcomes['stuck_processing']} teams hold a processing row older than 24h; "
            "clear them with scripts/retire_stranded_scrape_requests.py"
        )
    if outcomes["failed"] or outcomes["stuck_processing"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
