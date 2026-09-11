"""Turn a scraped GotSport event roster into the pair the seeding intake runs on.

The seeding surface is built around ``(ParsedRoster, tuple[ResolvedTeam, ...])``
— the table, the manual-override rows, the scrape queue and the cohort sheet all
read that one pair. A scraped event therefore becomes the same pair a pasted list
does, rather than a second row type carried alongside it.

The scraper's advantage survives the conversion. It harvests each team's GotSport
provider id, which resolves by direct lookup at full confidence, so a team it
linked never reaches a name comparison at all. Only the teams it could not link —
the event publishes no rankings link for them, or we hold no row under the id it
published — go on to the name passes in ``resolve_unlinked``.

An unreadable division label costs a team its cohort, never its place in the
roster. The scraper keeps those teams with ``age_group``/``gender`` empty, and so
does this module; the counts are reported as warnings so the operator can see
what was withheld.

The module also owns ``resolve_master_ids``, the bulk provider-id lookup the tab
and the CLI both run first. It is the one part of this file that reaches a
database and reads credentials, and it answers with warnings rather than
exceptions.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence

from src.tournaments.gotsport_event_roster import EventRoster, printable_text, redact_secret
from src.tournaments.roster_paste import ParsedRoster, RosterRow
from src.tournaments.roster_resolver import (
    ExactNameLookup,
    GotsportSearch,
    ProviderIdLookup,
    ResolvedTeam,
    make_provider_id_lookup,
    resolve_row,
)
from src.utils.merge_resolver import MergeResolver
from supabase import create_client

__all__ = [
    "needs_name_lookup",
    "make_historical_name_lookup",
    "resolve_master_ids",
    "resolve_unlinked",
    "to_seeding_rows",
]

_WARNING_CAP = 10


def to_seeding_rows(
    roster: EventRoster,
    master_ids: Mapping[str, str],
    extra_warnings: Sequence[str] = (),
) -> tuple[ParsedRoster, tuple[ResolvedTeam, ...]]:
    """Convert a walked event into the roster/resolution pair the intake renders.

    A team the scraper linked and that ``master_ids`` maps is settled at
    ``gotsport_id``. Every other team is ``unresolved``, keeping the provider id
    where one was published so ``resolve_unlinked`` can tell the two apart.

    ``unresolved`` rather than ``review`` for a team whose id we hold no row for:
    a review row with no candidates is inert everywhere downstream — the enqueue
    path and the cohort sheet both need a ``team_id_master`` and drop it — so it
    would read as a decision awaiting an operator that no operator can make.
    """
    rows: list[RosterRow] = []
    resolved: list[ResolvedTeam] = []

    for team in roster.teams:
        name = printable_text(team.team_name)
        rows.append(
            RosterRow(
                source_index=team.source_index,
                club_raw="",
                team_name_raw=name,
                state="",
                section_age_group=team.age_group,
                section_gender=team.gender,
                team_name_stripped=name,
                has_star_marker=False,
                has_c_marker=False,
            )
        )
        provider_team_id = team.provider_team_id
        team_id_master = master_ids.get(provider_team_id or "")
        if provider_team_id and team_id_master:
            resolved.append(
                ResolvedTeam(
                    source_index=team.source_index,
                    status="gotsport_id",
                    team_id_master=team_id_master,
                    provider_team_id=provider_team_id,
                )
            )
        else:
            resolved.append(
                ResolvedTeam(
                    source_index=team.source_index,
                    status="unresolved",
                    provider_team_id=provider_team_id,
                )
            )

    return ParsedRoster(rows=tuple(rows), warnings=_warnings(roster, extra_warnings)), tuple(resolved)


def _warnings(roster: EventRoster, extra_warnings: Sequence[str]) -> tuple[str, ...]:
    """Order the warnings so the ones naming a broken collaborator survive the cap.

    ``extra_warnings`` carries the only signal that credentials or the merge map
    failed, and a walk that met a systematic per-team refusal produces one
    scraper warning per team — so the scraper's go last and capped, not first.
    """
    no_age = sum(1 for team in roster.teams if not team.age_group)
    no_gender = sum(1 for team in roster.teams if not team.gender)

    warnings = [printable_text(warning) for warning in extra_warnings]
    if no_age:
        warnings.append(f"{no_age} team(s) kept with no age group; their division label named no single board.")
    if no_gender:
        warnings.append(f"{no_gender} team(s) kept with no gender; their division label did not name one.")

    scraper_warnings = [printable_text(warning) for warning in roster.warnings]
    warnings.extend(scraper_warnings[:_WARNING_CAP])
    if len(scraper_warnings) > _WARNING_CAP:
        warnings.append(f"...and {len(scraper_warnings) - _WARNING_CAP} more from the walk.")
    return tuple(warnings)


def needs_name_lookup(parsed: ParsedRoster, resolved: Sequence[ResolvedTeam]) -> tuple[int, ...]:
    """Which rows still need a name pass, in roster order.

    Both kinds of unlinked team are here — one carrying a provider id we hold no
    row for, one with no id at all. ``resolve_unlinked`` decides which pass each
    of them takes.
    """
    by_index = {item.source_index: item for item in resolved}
    return tuple(
        row.source_index
        for row in parsed.rows
        if getattr(by_index.get(row.source_index), "status", None) == "unresolved"
    )


def resolve_unlinked(
    parsed: ParsedRoster,
    resolved: Sequence[ResolvedTeam],
    *,
    indices: Sequence[int],
    gotsport_search: GotsportSearch,
    lookup_provider_id: ProviderIdLookup,
    lookup_exact_name: ExactNameLookup,
    delay_seconds: float = 0.0,
    historical_context: bool = False,
) -> tuple[ResolvedTeam, ...]:
    """Give the teams the walk could not link a second, free pass.

    Two passes, because a scraped row can arrive holding a provider id where a
    pasted row never can:

    - **The id is known.** Retry the id lookup, then fall back to an exact local
      name inside the row's own cohort. A GotSport name search is never made for
      these: the authoritative id is already in hand, the search costs a request,
      and it can return a *different* id that ``resolve_row`` would then keep in
      place of the one the event published.
    - **No id.** Take the same GotSport search and exact-name passes a pasted
      roster takes, via ``resolve_row``.

    Nothing here scores names fuzzily — an unlinked team is recovered by an exact
    name or not at all.

    ``historical_context=True`` uses only an event-published ID for automatic
    matching. Its name lookup must be ``make_historical_name_lookup`` (or an
    equivalent read-only collaborator): it searches across today's age groups
    and offers every result for operator review, without a current rankings
    search that could substitute next season's same-name squad.
    """
    rows_by_index = {row.source_index: row for row in parsed.rows}
    outcomes = {item.source_index: item for item in resolved}

    for index in indices:
        row = rows_by_index.get(index)
        item = outcomes.get(index)
        if row is None or item is None:
            continue

        if historical_context:
            # Only the ID actually published by this event proves identity.
            # Today's age-filtered rankings search can name next season's squad;
            # historical name candidates are always a human decision.
            team_id = lookup_provider_id(item.provider_team_id) if item.provider_team_id else None
            if team_id:
                outcomes[index] = ResolvedTeam(
                    source_index=index, status="gotsport_id", team_id_master=team_id,
                    provider_team_id=item.provider_team_id,
                )
                continue
            candidates = lookup_exact_name(row.team_name_stripped, "", row.section_gender)
            if candidates:
                outcomes[index] = ResolvedTeam(
                    source_index=index, status="review", provider_team_id=item.provider_team_id,
                    candidates=tuple({"team_id_master": candidate} for candidate in dict.fromkeys(candidates)),
                )
            continue

        if item.provider_team_id:
            outcomes[index] = _relink_known_id(
                row,
                item,
                lookup_provider_id=lookup_provider_id,
                lookup_exact_name=lookup_exact_name,
            )
        elif row.section_age_group and row.section_gender:
            # ``build_search_params`` raises on either blank — ValueError on the
            # age, KeyError on the gender — so a cohort-less row is left alone
            # rather than aborting the pass for the rows after it.
            outcomes[index] = resolve_row(
                row,
                gotsport_search=gotsport_search,
                lookup_provider_id=lookup_provider_id,
                lookup_exact_name=lookup_exact_name,
            )
            if delay_seconds:
                time.sleep(delay_seconds)

    return tuple(outcomes[item.source_index] for item in resolved)


def make_historical_name_lookup(supabase_client, merge_resolver=None) -> ExactNameLookup:
    """Find review candidates by exact name without treating a past U-age as current.

    The age argument is intentionally unused. Multiple current cohorts may carry
    the same display name; every candidate remains review-only in the historical
    resolver. Final string equality also refuses SQL wildcard matches in a name.
    """
    def lookup(team_name: str, _age_group: str, gender: str) -> list[str]:
        if not team_name.strip():
            return []
        candidates: set[str] = set()
        offset = 0
        while True:
            query = (
                supabase_client.table("teams")
                .select("team_id_master,team_name")
                .ilike("team_name", team_name)
                .eq("is_deprecated", False)
                .order("team_id_master")
                .range(offset, offset + 999)
            )
            if gender in ("Male", "Female"):
                query = query.eq("gender", gender)
            rows = query.execute().data or []
            for row in rows:
                if str(row.get("team_name") or "").casefold() != team_name.casefold():
                    continue
                team_id = row.get("team_id_master")
                if team_id:
                    candidates.add((merge_resolver.resolve(team_id) or team_id) if merge_resolver else team_id)
            if len(rows) < 1000:
                break
            offset += 1000
        return sorted(candidates)

    return lookup


def _relink_known_id(
    row: RosterRow,
    item: ResolvedTeam,
    *,
    lookup_provider_id: ProviderIdLookup,
    lookup_exact_name: ExactNameLookup,
) -> ResolvedTeam:
    """Retry the id, then an exact name, keeping the published id either way.

    The id is retried rather than trusted absent: the bulk mapping is abandoned
    wholesale on any failure, so absence from it is not evidence of anything.
    """
    team_id_master = lookup_provider_id(item.provider_team_id or "")
    if team_id_master:
        return ResolvedTeam(
            source_index=row.source_index,
            status="gotsport_id",
            team_id_master=team_id_master,
            provider_team_id=item.provider_team_id,
        )

    local = lookup_exact_name(row.team_name_stripped, row.section_age_group, row.section_gender)
    if len(local) == 1:
        return ResolvedTeam(
            source_index=row.source_index,
            status="exact_name",
            team_id_master=local[0],
            provider_team_id=item.provider_team_id,
            matched_name=row.team_name_stripped,
        )
    if len(local) > 1:
        # Same shape ``resolve_row`` returns for an ambiguous name. Withholding it
        # here would hand the operator an empty paste box for a team the lookup
        # had in fact already found, twice.
        return ResolvedTeam(
            source_index=row.source_index,
            status="review",
            provider_team_id=item.provider_team_id,
            candidates=tuple({"team_id_master": team_id} for team_id in local),
        )
    return item


def resolve_master_ids(
    teams,
    *,
    enabled: bool,
    client_factory=create_client,
    resolver_factory=MergeResolver,
    lookup_factory=make_provider_id_lookup,
) -> tuple[dict[str, str], list[str]]:
    """Map each scraped provider id to our canonical team id.

    Returns the mapping and any warnings. A database failure here must not cost
    the walk: the roster is the paid artifact, and re-running resolution is free
    where re-running the scrape is not. Nothing in here raises.

    Because it discards the whole mapping on any failure, an id's absence from
    the result does not mean it is unmapped — only ``resolve_unlinked``'s retry
    can tell those apart.

    The three collaborators are injectable so each arm — including the one that
    redacts a credential out of a failure message — can be driven without a
    database. A redactor tested only as a pure function does not prove it is
    actually called here.
    """
    provider_ids = [team.provider_team_id for team in teams if team.provider_team_id]
    if not enabled or not provider_ids:
        return {}, []

    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY") or "").strip()
    if not (url and key):
        return {}, ["No Supabase credentials; provider ids were not resolved to PitchRank teams"]
    if any(character.isspace() for character in key):
        # Refuse before the key reaches any client. `MergeResolver.load_merge_map`
        # catches its own exception and logs the text unredacted, and `h11`
        # formats the offending header with `repr`, so a key soft-wrapped in
        # `.env.local` reaches stderr before `_redact` below is ever consulted.
        # The message names the variable and never the value.
        return {}, [
            "SUPABASE_SERVICE_ROLE_KEY has whitespace inside it, which no valid key "
            "does; provider ids were not resolved. Re-save it on a single line."
        ]

    warnings: list[str] = []
    try:
        supabase = client_factory(url, key)
        merge_resolver = resolver_factory(supabase)
        merge_resolver.load_merge_map()
        if getattr(merge_resolver, "version", None) == "error":
            # load_merge_map catches its own exceptions and returns normally, so
            # this is the only signal that merges were not applied. Without it a
            # team_id_master that was merged away is reported as resolved.
            warnings.append(
                "Merge map failed to load; ids were resolved without merge resolution "
                "and may name deprecated teams"
            )
        lookup = lookup_factory(supabase, merge_resolver)

        resolved = {}
        for provider_id in dict.fromkeys(provider_ids):
            master_id = lookup(provider_id)
            if master_id:
                resolved[provider_id] = master_id
        return resolved, warnings
    except Exception as exc:
        # This message is written into reports/, which is not gitignored, in a
        # public repo — and a key with a stray newline makes httpx raise
        # `Illegal header value b'<the key>'`, putting the key in the text.
        return {}, [f"Master-id resolution failed, roster kept without it: {redact_secret(exc, key)}"]
