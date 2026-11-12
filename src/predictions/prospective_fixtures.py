"""Read stored upcoming fixtures into the existing prospective forecast ledger."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

from src.predictions.collection_selection import select_fixture_candidates
from src.utils.merge_resolver import MergeResolver

PAGE_SIZE = 1000
GAME_FIELDS = (
    "id,game_date,home_team_master_id,away_team_master_id,home_provider_id,away_provider_id,"
    "home_score,away_score,provider_id,competition,division_name,event_name,source_url,is_excluded"
)


def paged(query_factory):
    offset = 0
    while True:
        rows = query_factory().range(offset, offset + PAGE_SIZE - 1).execute().data or []
        yield from rows
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE


def strict_resolver(client):
    resolver = MergeResolver(client)
    resolver.load_merge_map()
    if resolver.version == "error":
        raise RuntimeError("Cannot capture or settle without the merge map")
    return resolver


def canonical(resolver, team_id):
    seen = set()
    while team_id is not None:
        if team_id in seen:
            raise ValueError("Cyclic team merge")
        seen.add(team_id)
        resolved = resolver.resolve(team_id)
        if resolved == team_id:
            return resolved
        team_id = resolved
    return None


def source_fixture_identity(game):
    """Only provider fixture links prove that two same-day games are rematches."""
    if not game.get("provider_id") or not game.get("source_url"):
        return None
    try:
        url = urlsplit(game["source_url"])
        valid = re.compile(r"(?:[0-9]+|[a-f0-9]{8}-[a-f0-9-]{27})", re.I | re.ASCII)
        for key, value in parse_qsl(url.query):
            if re.fullmatch(r"(?:game|match|fixture)_?id", key, re.I | re.ASCII) and valid.fullmatch(value):
                return f"{game['provider_id']}|{url.netloc}{url.path}|{key.lower()}", value.lower()
        match = re.fullmatch(r"(.*\/(?:games?|match(?:es)?|fixtures?))/([^/]+)/?", url.path, re.I)
        if match and valid.fullmatch(match[2]):
            return f"{game['provider_id']}|{url.netloc}{match[1]}", match[2].lower()
    except ValueError:
        pass
    return None


def ambiguous_pair_games(games):
    if len(games) < 2:
        return False
    identities = [source_fixture_identity(game) for game in games]
    return (any(identity is None for identity in identities)
            or len({identity[0] for identity in identities if identity}) != 1
            or len(set(identities)) != len(games))


def evaluation_group(provider, game):
    # Only this known URL shape supplies an event ID; competition names are not IDs.
    match = re.search(r"/events/([0-9]+)(?:/|$)", urlsplit(game.get("source_url") or "").path)
    if match and provider == "gotsport":
        return "event", f"{provider}:{match[1]}", match[1]
    day = date.fromisoformat(game["game_date"])
    year, week, _ = day.isocalendar()
    competition = " ".join(str(game.get("competition") or game.get("event_name") or "unknown").lower().split())
    return "inferred_competition_week", f"{provider}:{competition}:{year}-W{week:02d}", None


def _team_rows(client, ids, table, fields, key):
    rows = {}
    ids = sorted(ids)
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        for row in paged(lambda: client.table(table).select(fields).in_(key, batch).order(key)):
            rows[row[key]] = row
    return rows


def history_band(count):
    if not isinstance(count, (int, float)) or isinstance(count, bool) or not math.isfinite(count) or count < 0:
        return "unknown"
    return "0" if count == 0 else "1-3" if count < 4 else "4-7" if count < 8 else "8+"


def database_fixture_inventory(client, *, today=None):
    """Read the complete available pool, retaining exclusion reasons and source denominators."""
    today = today or datetime.now(timezone.utc).date()
    first, last = [(today + timedelta(days=n)).isoformat() for n in (1, 7)]
    # Read scored rows too: a scored twin makes an unscored source ambiguous.
    games = list(paged(lambda: client.table("games").select(GAME_FIELDS)
                       .gte("game_date", first).lte("game_date", last).eq("is_excluded", False)
                       .order("game_date").order("id")))
    resolver = strict_resolver(client)
    providers = {row["id"]: row["code"] for row in paged(
        lambda: client.table("providers").select("id,code").order("id"))}
    existing_rows = list(paged(lambda: client.table("prospective_match_predictions")
                              .select("fixture_key,source_game_id,provider_code,heuristic_prediction_status,heuristic_prediction")
                              .gte("game_date", first).lte("game_date", last).order("id")))
    existing = {row["fixture_key"] for row in existing_rows}
    excluded = {canonical(resolver, row["team_id_master"]) for row in paged(
        lambda: client.table("team_ranking_exclusions").select("team_id_master").order("team_id_master"))}
    pairs = defaultdict(list)
    resolved = {}
    for game in games:
        home = canonical(resolver, game.get("home_team_master_id"))
        away = canonical(resolver, game.get("away_team_master_id"))
        resolved[game["id"]] = (home, away)
        if home and away:
            pairs[(game["game_date"], tuple(sorted((home, away))))].append(game)
    team_ids = {team for pair in resolved.values() for team in pair if team}
    teams = _team_rows(client, team_ids, "teams", "team_id_master,team_name,age_group,gender", "team_id_master")
    ratings = _team_rows(client, team_ids, "rankings_full", "team_id,power_score_final,status,games_played", "team_id")
    skipped = Counter()
    coverage = defaultdict(Counter)
    candidates = []
    strata_coverage = defaultdict(Counter)
    for game in games:
        home, away = resolved[game["id"]]
        provider = providers.get(game.get("provider_id"))
        cohort = "|".join(str(teams.get(home, {}).get(key) or "unknown") for key in ("age_group", "gender"))
        bucket = f"{provider or 'unknown'}|{cohort}"
        if game.get("home_score") is not None or game.get("away_score") is not None:
            continue
        coverage[bucket]["seen"] += 1
        team_ages = sorted({str(teams.get(team, {}).get("age_group") or "unknown") for team in (home, away)})
        team_genders = sorted({str(teams.get(team, {}).get("gender") or "unknown") for team in (home, away)})
        counts = [ratings.get(team, {}).get("games_played") for team in (home, away)]
        known_counts = all(isinstance(c, (int, float)) and not isinstance(c, bool)
                           and math.isfinite(c) and c >= 0 for c in counts)
        band = history_band(min(counts)) if known_counts else "unknown"
        stratum = {"provider": provider or "unknown", "age_group": "/".join(team_ages),
                   "gender": "/".join(team_genders), "rating_history_band": band}
        label = tuple(stratum.values())
        strata_coverage[label]["seen"] += 1
        key = f"database:{game['id']}"
        reason = None
        if key in existing:
            reason = "already_recorded"
        elif not home or not away or home == away or not provider:
            reason = "unresolved_identity"
        elif home in excluded or away in excluded:
            reason = "excluded_team"
        elif ambiguous_pair_games(pairs[(game["game_date"], tuple(sorted((home, away))))]):
            reason = "ambiguous_duplicate_fixture"
        elif any(team not in teams or not teams[team].get("team_name") or team not in ratings
                 or ratings[team].get("power_score_final") is None
                 or str(ratings[team].get("status", "")).lower() == "inactive" for team in (home, away)):
            reason = "missing_current_rating_or_team"
        if reason:
            skipped[reason] += 1
            coverage[bucket]["skipped"] += 1
            coverage[bucket][reason] += 1
            strata_coverage[label][reason] += 1
            continue
        coverage[bucket]["eligible"] += 1
        strata_coverage[label]["eligible"] += 1
        kind, group, event = evaluation_group(provider, game)
        candidates.append((bucket, {
            "fixture_key": key, "source_game_id": game["id"], "provider_code": provider,
            "source_system": "database_games", "source_event_id": event,
            "evaluation_group_kind": kind, "evaluation_group_key": group,
            "game_date": game["game_date"], "competition": game.get("competition"),
            "division_name": game.get("division_name"),
            "home_provider_team_id": game.get("home_provider_id"),
            "away_provider_team_id": game.get("away_provider_id"),
            "home_team_name": teams[home]["team_name"], "away_team_name": teams[away]["team_name"],
            "home_team_master_id": home, "away_team_master_id": away,
            "home_resolution_method": "database_canonical", "away_resolution_method": "database_canonical",
            "resolution_status": "resolved", "offline_prediction_status": "skipped",
            "fixture_payload": {"source_snapshot": game, "cohort": cohort, "merge_version": resolver.version,
                                "collection_stratum": stratum, "collection_policy": "balanced_v1"},
        }))
    return candidates, {"window_start": first, "window_end": last, "eligible": len(candidates),
                        "skipped": dict(skipped), "coverage": coverage, "strata": strata_coverage,
                        "providers": sorted(providers.values())}, existing_rows


def prepare_database_fixtures(client, *, limit=500, dry_run=True, today=None, selection="balanced"):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    candidates, summary, _ = database_fixture_inventory(client, today=today)
    selected = select_fixture_candidates(candidates, limit, selection)
    coverage = summary.pop("coverage")
    strata = summary.pop("strata")
    inserted = 0
    for bucket, row in selected:
        coverage[bucket]["selected"] += 1
        strata[tuple(row["fixture_payload"]["collection_stratum"].values())]["selected"] += 1
        row["fixture_payload"]["collection_policy"] = selection + "_v1"
    if not dry_run:
        for start in range(0, len(selected), 100):
            rows = [row for _, row in selected[start:start + 100]]
            # Never replay a stale copy over a worker's completed forecast.
            result = client.table("prospective_match_predictions").upsert(
                rows, on_conflict="fixture_key", ignore_duplicates=True).execute()
            inserted += len(result.data or [])
    return {"dry_run": dry_run, **summary, "selection": selection, "selected": len(selected), "inserted": inserted,
            "coverage": {key: dict(value) for key, value in sorted(coverage.items())},
            "strata": [{**dict(zip(("provider", "age_group", "gender", "rating_history_band"), key)), **value}
                       for key, value in sorted(strata.items())]}


def settlement_aliases(resolver):
    aliases = defaultdict(set)
    for team in resolver.get_deprecated_teams():
        aliases[canonical(resolver, team)].add(team)
    return aliases


def database_result(client, fixture, resolver, aliases_by_team=None):
    """Exact source settlement; never substitute a plausible different match."""
    response = client.table("games").select(GAME_FIELDS).eq("id", fixture["source_game_id"]).maybe_single().execute()
    game = response.data if response is not None else None
    if not game:
        return None, False, "source_missing"
    snapshot = (fixture.get("fixture_payload") or {}).get("source_snapshot", {})
    if (game["game_date"] != fixture["game_date"] or game.get("provider_id") != snapshot.get("provider_id")
            or game.get("source_url") != snapshot.get("source_url")):
        return None, False, "fixture_changed"
    home, away = [canonical(resolver, fixture.get(key)) for key in ("home_team_master_id", "away_team_master_id")]
    actual_pair = [canonical(resolver, game.get(key)) for key in ("home_team_master_id", "away_team_master_id")]
    if not home or not away or home == away or set(actual_pair) != {home, away}:
        return None, False, "fixture_changed"
    if aliases_by_team is None:
        aliases_by_team = settlement_aliases(resolver)
    aliases = {home} | aliases_by_team.get(home, set())
    pair_aliases = aliases | {away} | aliases_by_team.get(away, set())
    excluded = _team_rows(client, pair_aliases, "team_ranking_exclusions", "team_id_master", "team_id_master")
    if game.get("is_excluded") is not False or excluded:
        return None, False, "excluded_result"
    # Query every alias, including ones created after the forecast was frozen.
    possible = {}
    for start in range(0, len(aliases), 50):
        batch = sorted(aliases)[start:start + 50]
        for column in ("home_team_master_id", "away_team_master_id"):
            for candidate in paged(lambda: client.table("games").select(GAME_FIELDS)
                                   .eq("game_date", game["game_date"]).eq("is_excluded", False)
                                   .in_(column, batch).order("id")):
                pair = {canonical(resolver, candidate.get(key))
                        for key in ("home_team_master_id", "away_team_master_id")}
                if pair == {home, away}:
                    possible[candidate["id"]] = candidate
    if ambiguous_pair_games(list(possible.values())):
        return None, False, "ambiguous_result"
    scores = [game.get("home_score"), game.get("away_score")]
    if any(score is None for score in scores):
        return None, False, "result_not_found"
    if any(isinstance(score, bool) or not isinstance(score, int) or score < 0 for score in scores):
        return None, False, "invalid_result"
    return game, actual_pair[0] != home, "source_game_id"
