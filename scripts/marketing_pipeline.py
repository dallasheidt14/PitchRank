#!/usr/bin/env python3
"""
Marketing Pipeline — Automated newsletter + social drafts after rankings update

Chains to Calculate Rankings workflow. Fetches ranking highlights from Supabase,
generates a newsletter, publishes to Beehiiv, and drafts X + Instagram + trend
social posts to Postiz for operator approval before publish.

Run: python3 scripts/marketing_pipeline.py [--dry-run]
"""

import argparse
import base64
import json
import logging
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
env_local = Path(__file__).parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
if env_path.exists():
    load_dotenv(env_path, override=True)

import requests  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("marketing_pipeline")

PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "templates"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
PITCHRANK_URL = os.getenv("PITCHRANK_URL", "https://pitchrank.io")

# Mountain Time offset (UTC-7 MST, UTC-6 MDT)
# Use -6 during daylight saving (March-November)
MT_OFFSET = timezone(timedelta(hours=-6))

# Postiz API
POSTIZ_API_URL = "https://api.postiz.com/public/v1"

# Beehiiv API
BEEHIIV_API_URL = "https://api.beehiiv.com/v2"

# Restrict the newsletter/blog state spotlight to deep states, where every age/gender
# cohort has enough ranked teams to fill a clean Top 5. Small states surface provisional
# ("Not Enough Ranked Games") teams, which we don't want in public copy.
SPOTLIGHT_STATES = ("CA", "TX", "AZ", "FL", "PA", "NJ", "OK", "OH")
# Fixed Monday epoch so the rotation advances exactly one step per week with no
# year-boundary jump.
STATE_COHORT_EPOCH = datetime(2026, 1, 5)

# States with a pillar guide — must stay in sync with STATE_PILLAR_SLUGS in
# frontend/lib/cohort-seo.ts (19 states as of 2026-06).
PILLAR_STATES = (
    "AZ", "CA", "CO", "CT", "FL", "GA", "IL", "MA", "MD", "MI",
    "MN", "NJ", "NY", "NC", "OH", "PA", "TX", "VA", "WA",
)
STATE_DISPLAY_NAMES = {
    "AZ": "Arizona", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "FL": "Florida", "GA": "Georgia", "IL": "Illinois", "MA": "Massachusetts",
    "MD": "Maryland", "MI": "Michigan", "MN": "Minnesota", "NJ": "New Jersey",
    "NY": "New York", "NC": "North Carolina", "OH": "Ohio", "PA": "Pennsylvania",
    "TX": "Texas", "VA": "Virginia", "WA": "Washington",
}
# Tuesday Top-10 age pool: u10-u17 + u19 (u18 merges into u19 platform-wide).
TOP10_AGES = (10, 11, 12, 13, 14, 15, 16, 17, 19)

# Thursday big-games slate is restricted to deeper states so matchups are
# genuine marquee games, not thin small-state #1-vs-#2 pairings.
BIG_GAMES_STATES = (
    "CA", "MA", "TX", "FL", "NJ", "AZ", "PA", "GA", "VA", "MD",
    "OH", "OK", "CO", "NC", "IL", "WA", "NV", "NY",
)


def weekly_top10_combos(monday: datetime) -> list[tuple[str, int, str]]:
    """Return the week's 3 deterministic (state, age, gender) Top-10 combos.

    States walk PILLAR_STATES in blocks of 3, so every 19 consecutive picks cover
    all 19 states before any repeats (19 % 3 != 0 means one week per cycle mixes
    the cycle boundary — expected, not a bug). Ages and genders shift by week so
    cohorts vary.
    """
    week = (monday.date() - STATE_COHORT_EPOCH.date()).days // 7
    return [
        (
            PILLAR_STATES[(week * 3 + i) % len(PILLAR_STATES)],
            TOP10_AGES[(week + i) % len(TOP10_AGES)],
            ("male", "female")[(week + i) % 2],
        )
        for i in range(3)
    ]


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------


def get_supabase_client():
    """Initialize Supabase client."""
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")

    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    return create_client(url, key)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


MILESTONE_THRESHOLDS = [10, 25, 50, 100]


def fetch_milestone_movers(supabase) -> list[dict]:
    """Find teams that crossed into top 10/25/50/100 in their cohort this week.

    Uses the published final rank (current) and rank_change_7d to compute previous rank.
    A milestone crossing means: current <= threshold AND previous > threshold.
    """
    log.info("Fetching milestone movers from Supabase...")

    # All teams in top 100 that improved this week, with >= 8 games (matches the
    # get_biggest_movers reliability gate). rank_in_cohort_final is the published rank
    # and the basis rank_change_7d is computed against (ranking_history.py), so
    # `previous = current + change` only holds when current is the final rank.
    resp = (
        supabase.table("rankings_full")
        .select("team_id, age_group, gender, state_code, rank_in_cohort_final, rank_change_7d")
        .lte("rank_in_cohort_final", max(MILESTONE_THRESHOLDS))
        .gt("rank_change_7d", 0)
        .gte("games_played", 8)
        .neq("status", "Not Enough Ranked Games")
        .order("rank_in_cohort_final")
        .execute()
    )

    # Detect milestone crossings — assign highest threshold crossed
    milestones = []
    for team in resp.data or []:
        current = team.get("rank_in_cohort_final") or 0
        change = team.get("rank_change_7d") or 0
        previous = current + change  # rank_change_7d = previous - current (positive = improved)
        for threshold in MILESTONE_THRESHOLDS:
            if current <= threshold < previous:
                milestones.append(
                    {**team, "rank_in_cohort": current, "milestone": threshold, "previous_rank": previous}
                )
                break  # Only count the highest (most impressive) milestone

    if not milestones:
        log.info("No milestone crossings this week")
        return []

    # Fetch team names (rankings_full has no team_name)
    team_ids = list({m["team_id"] for m in milestones})
    names_resp = supabase.table("teams").select("team_id_master, team_name").in_("team_id_master", team_ids).execute()
    name_map = {t["team_id_master"]: t["team_name"] for t in (names_resp.data or [])}
    for m in milestones:
        m["team_name"] = name_map.get(m["team_id"], "Unknown")

    # Sort: top 10 first, then top 25, etc. Within tier, by rank
    milestones.sort(key=lambda m: (m["milestone"], m["rank_in_cohort"]))
    log.info(
        f"Found {len(milestones)} milestone crossings: "
        f"{sum(1 for m in milestones if m['milestone'] == 10)} top-10, "
        f"{sum(1 for m in milestones if m['milestone'] == 25)} top-25, "
        f"{sum(1 for m in milestones if m['milestone'] == 50)} top-50, "
        f"{sum(1 for m in milestones if m['milestone'] == 100)} top-100"
    )
    return milestones


def fetch_ranking_highlights(supabase) -> dict:
    """Fetch weekly movers, stats, and state spotlight from Supabase."""
    log.info("Fetching ranking highlights from Supabase...")

    # Top 5 climbers
    climbers_resp = supabase.rpc(
        "get_biggest_movers",
        {
            "p_days": 7,
            "p_limit": 5,
            "p_direction": "up",
        },
    ).execute()
    climbers = climbers_resp.data or []

    # Top 5 fallers
    fallers_resp = supabase.rpc(
        "get_biggest_movers",
        {
            "p_days": 7,
            "p_limit": 5,
            "p_direction": "down",
        },
    ).execute()
    fallers = fallers_resp.data or []

    # Total ranked teams
    count_resp = (
        supabase.table("rankings_full")
        .select("team_id", count="exact")
        .neq("status", "Not Enough Ranked Games")
        .execute()
    )
    total_teams = count_resp.count or 0

    # Biggest single jump
    biggest_jump = 0
    if climbers:
        biggest_jump = max(abs(t.get("rank_change", 0)) for t in climbers)

    # State spotlight — state with most total rank movement
    spotlight_state = ""
    spotlight_teams = []
    try:
        state_resp = supabase.rpc(
            "get_biggest_movers",
            {
                "p_days": 7,
                "p_limit": 20,
                "p_direction": "up",
            },
        ).execute()
        if state_resp.data:
            # Count movement by state
            state_movement: dict[str, int] = {}
            for team in state_resp.data:
                st = team.get("state_code") or team.get("state", "")
                if st and st in SPOTLIGHT_STATES:
                    state_movement[st] = state_movement.get(st, 0) + abs(team.get("rank_change", 0))
            if state_movement:
                spotlight_state = max(state_movement, key=state_movement.get)
                # Prefer state-cohort movers (believable deltas); fall back to the
                # national movers filtered by state if the state RPC isn't available yet,
                # so the spotlight stays populated instead of emitting a mismatched post.
                try:
                    spotlight_teams = fetch_state_movers(supabase, spotlight_state)["climbers"][:3]
                except Exception as e:
                    log.warning(f"State movers RPC unavailable for spotlight; using national movers: {e}")
                    spotlight_teams = [
                        t for t in state_resp.data if (t.get("state_code") or t.get("state", "")) == spotlight_state
                    ][:3]
    except Exception as e:
        log.warning(f"Could not determine state spotlight: {e}")

    data = {
        "climbers": climbers,
        "fallers": fallers,
        "total_teams": total_teams,
        "biggest_jump": biggest_jump,
        "spotlight_state": spotlight_state,
        "spotlight_teams": spotlight_teams,
        "date": datetime.now(MT_OFFSET),
    }

    # Milestone movers — teams that crossed into top 10/25/50/100 in cohort
    milestones = []
    try:
        milestones = fetch_milestone_movers(supabase)
    except Exception as e:
        log.warning(f"Could not fetch milestone movers: {e}")

    data = {
        "climbers": climbers,
        "fallers": fallers,
        "total_teams": total_teams,
        "biggest_jump": biggest_jump,
        "spotlight_state": spotlight_state,
        "spotlight_teams": spotlight_teams,
        "milestones": milestones,
        "date": datetime.now(MT_OFFSET),
    }

    # Instagram week inputs: live Active count, Tuesday Top-10 cohorts, weekend slate
    data["active_team_count"] = fetch_active_team_count(supabase)
    data["top10_combos"] = weekly_top10_combos(data["date"])
    data["top10_cohorts"] = fetch_top10_cohorts(supabase, data["top10_combos"])
    data["big_games_window"] = next_weekend_window(datetime.now(MT_OFFSET))
    data["big_games"] = fetch_big_weekend_games(supabase, *data["big_games_window"])

    log.info(
        f"Highlights: {len(climbers)} climbers, {len(fallers)} fallers, "
        f"{total_teams} total teams, spotlight: {spotlight_state}, "
        f"{len(milestones)} milestone crossings, {data['active_team_count']} active teams, "
        f"{len(data['top10_cohorts'])} top-10 cohorts, {len(data['big_games'])} big games"
    )
    return data


def fetch_active_team_count(supabase) -> int:
    """Live Active-team count via the same RPC the rankings-live graphic uses.

    One shared source means the Monday caption and graphic can never disagree.
    This is the published-rank denominator (Active only) — deliberately smaller
    than the legacy total_teams count, which includes other statuses.
    """
    try:
        resp = supabase.rpc("get_national_active_count").execute()
        return int(resp.data or 0)
    except Exception as e:
        log.warning(f"Active team count RPC failed: {e}")
        return 0


def fetch_rankings_last_calculated(supabase) -> datetime | None:
    """Return MAX(last_calculated) from rankings_full, or None when unavailable."""
    try:
        resp = (
            supabase.table("rankings_full")
            .select("last_calculated")
            .order("last_calculated", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        raw = rows[0].get("last_calculated") if rows else None
        if not raw:
            return None
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception as e:
        log.warning(f"Rankings freshness lookup failed: {e}")
        return None


def rankings_are_stale(last_calculated: datetime | None, now: datetime | None = None, max_age_days: int = 8) -> bool:
    """True when rankings are too old to announce as new.

    The threshold is sized to the weekly recalc cadence plus margin — a healthy
    dataset can legitimately be several days old by the time the pipeline runs.
    """
    if last_calculated is None:
        return True
    now = now or datetime.now(timezone.utc)
    return now - last_calculated > timedelta(days=max_age_days)


def fetch_top10_cohorts(supabase, combos: list[tuple[str, int, str]]) -> list[dict]:
    """Resolve each (state, age, gender) combo to its state Top 10 via get_state_rankings.

    Mirrors getStateTopTeams() in frontend/app/api/infographic/state/route.tsx:
    over-fetch, keep Active teams with a state rank, slice 10. A combo with a thin
    cohort advances deterministically to the next pillar state (same age/gender).
    """
    cohorts = []
    for state, age, gender in combos:
        start = PILLAR_STATES.index(state)
        chosen = None
        for step in range(len(PILLAR_STATES)):
            candidate = PILLAR_STATES[(start + step) % len(PILLAR_STATES)]
            try:
                resp = supabase.rpc(
                    "get_state_rankings",
                    {
                        "p_state": candidate,
                        # Bare number, not "u14" — the RPC casts p_age::INTEGER
                        "p_age": str(age),
                        "p_gender": "M" if gender == "male" else "F",
                        "p_limit": 55,
                        "p_offset": 0,
                    },
                ).execute()
            except Exception as e:
                log.warning(f"get_state_rankings failed for {candidate} u{age} {gender}: {e}")
                continue
            teams = [
                t
                for t in (resp.data or [])
                if t.get("status") == "Active" and t.get("rank_in_state_final") is not None
            ][:10]
            if len(teams) >= 10:
                if step:
                    log.info(f"Top-10 combo {state} u{age} {gender} thin; re-picked {candidate}")
                chosen = {"state": candidate, "age": age, "gender": gender, "teams": teams}
                break
        if chosen:
            cohorts.append(chosen)
        else:
            log.warning(f"No viable Top-10 cohort for u{age} {gender} in any pillar state")
    return cohorts


def next_weekend_window(now: datetime) -> tuple:
    """Return (friday, sunday) dates of the next upcoming Fri-Sun window."""
    days_to_friday = (4 - now.weekday()) % 7 or 7
    friday = (now + timedelta(days=days_to_friday)).date()
    return friday, friday + timedelta(days=2)


def fetch_big_weekend_games(supabase, start_date, end_date, states=BIG_GAMES_STATES) -> list[dict]:
    """Weekend games where both sides are ranked top-25 in the same state cohort.

    Restricted to `states` (the bigger-state list) so the slate is marquee
    matchups rather than thin small-state pairings.
    """
    try:
        resp = supabase.rpc(
            "get_big_weekend_games",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
                "p_states": list(states) if states else None,
            },
        ).execute()
        return resp.data or []
    except Exception as e:
        log.warning(f"Big weekend games RPC failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Newsletter generation (uses blog post content)
# ---------------------------------------------------------------------------


def _markdown_to_email_html(md_text: str) -> str:
    """Convert markdown to email-safe HTML with inline styles.

    `markdown` is imported lazily: the package is only listed in the GHA workflow's
    explicit pip install line for the marketing pipeline, not in requirements.lock,
    so the CI test runner doesn't have it. Tests cover the post-translation helpers
    only and don't reach this path.
    """
    import markdown as md_lib

    raw_html = md_lib.markdown(md_text, extensions=["tables"])

    # Add inline styles for email clients
    replacements = [
        (
            "<h2>",
            '<h2 style="margin:20px 0 12px;font-size:16px;font-weight:700;'
            'color:#0B5345;text-transform:uppercase;letter-spacing:0.5px;">',
        ),
        ("<h3>", '<h3 style="margin:16px 0 8px;font-size:15px;font-weight:700;color:#0B5345;">'),
        ("<p>", '<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#1a1a1a;">'),
        ("<table>", '<table style="width:100%;border-collapse:collapse;margin:0 0 16px;">'),
        ("<thead>", "<thead>"),
        (
            "<th>",
            '<th style="padding:8px 10px;font-size:11px;font-weight:700;color:#ffffff;'
            'text-transform:uppercase;background-color:#0B5345;text-align:left;">',
        ),
        ("<td>", '<td style="padding:8px 10px;font-size:13px;border-bottom:1px solid #eee;">'),
        ("<strong>", '<strong style="font-weight:700;color:#0B5345;">'),
        ("<ul>", '<ul style="margin:0 0 12px;padding-left:20px;">'),
        ("<li>", '<li style="margin:0 0 6px;font-size:14px;line-height:1.5;">'),
        ("<a ", '<a style="color:#0B5345;font-weight:600;text-decoration:none;" '),
    ]
    for old, new in replacements:
        raw_html = raw_html.replace(old, new)

    # Alternate row backgrounds on table rows
    def _stripe_rows(match: re.Match) -> str:
        rows = re.findall(r"<tr>(.*?)</tr>", match.group(0), re.DOTALL)
        out = []
        for i, row_content in enumerate(rows):
            bg = "#ffffff" if i % 2 == 0 else "#f8f9fa"
            out.append(f'<tr style="background-color:{bg};">{row_content}</tr>')
        return "\n".join(out)

    raw_html = re.sub(r"<tbody>(.*?)</tbody>", _stripe_rows, raw_html, flags=re.DOTALL)

    return raw_html


def generate_newsletter_html(data: dict, blog_body_md: str) -> str:
    """Wrap blog post content in the branded newsletter template."""
    template_path = TEMPLATE_DIR / "newsletter_weekly.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Newsletter template not found: {template_path}")

    template_str = template_path.read_text(encoding="utf-8")
    tmpl = Template(template_str)

    dt = data["date"]
    date_display = f"Week of {dt.strftime('%b %d, %Y')}"
    # Drop the count sentence entirely when the live count is unavailable —
    # never a made-up number.
    total_teams_line = (
        f'<p style="margin:12px 0 0;font-size:13px;color:#888;">{data["total_teams"]:,} teams. '
        "13-layer algorithm. Updated every Monday.</p>"
        if data["total_teams"]
        else ""
    )

    blog_content_html = _markdown_to_email_html(blog_body_md)

    # Rotating engagement hooks
    engagement_hooks = [
        "Know a soccer parent who checks rankings at 11pm? Forward this email.",
        "What do you wish rankings could tell you? Reply and let us know.",
        "Is your team climbing or falling? Check your full trend in Premium.",
        "Tryout season is coming. Compare clubs before you commit.",
    ]
    week_num = dt.isocalendar()[1]
    engagement_hook = engagement_hooks[week_num % len(engagement_hooks)]

    html = tmpl.safe_substitute(
        date_display=date_display,
        blog_content_html=blog_content_html,
        total_teams_line=total_teams_line,
        engagement_hook=engagement_hook,
    )

    log.info(f"Newsletter generated ({len(html):,} bytes)")
    return html


def generate_newsletter_subject(data: dict, blog_title: str = "") -> str:
    """Generate subject line from blog title or top mover."""
    dt = data["date"]
    date_str = dt.strftime("%b %d")

    if blog_title:
        # Truncate for subject line readability
        title = blog_title if len(blog_title) <= 50 else blog_title[:47] + "..."
        return f"PitchRank Weekly: {title} | {date_str}"

    top = data["climbers"][0] if data["climbers"] else None
    if top:
        name = top.get("team_name", "A team")
        if len(name) > 30:
            name = name[:27] + "..."
        change = abs(top.get("rank_change", 0))
        return f"PitchRank Weekly: {name} jumped {change} spots | {date_str}"

    return f"PitchRank Weekly Rankings Update | {date_str}"


# ---------------------------------------------------------------------------
# Beehiiv publishing
# ---------------------------------------------------------------------------


def get_beehiiv_publication_id() -> str:
    """Get Beehiiv publication ID from env or API."""
    pub_id = os.getenv("BEEHIIV_PUBLICATION_ID")
    if pub_id:
        return pub_id

    # Fallback: fetch from API
    api_key = os.getenv("BEEHIIV_API_KEY")
    if not api_key:
        raise RuntimeError("BEEHIIV_API_KEY must be set")

    log.info("BEEHIIV_PUBLICATION_ID not set, fetching from API...")
    resp = requests.get(
        f"{BEEHIIV_API_URL}/publications",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    pubs = resp.json().get("data", [])
    if not pubs:
        raise RuntimeError("No Beehiiv publications found")

    pub_id = pubs[0]["id"]
    log.info(f"Found Beehiiv publication: {pub_id} — add as BEEHIIV_PUBLICATION_ID to avoid this lookup")
    return pub_id


def publish_to_beehiiv(html: str, subject: str) -> bool:
    """Publish newsletter to Beehiiv and send to all subscribers."""
    api_key = os.getenv("BEEHIIV_API_KEY")
    if not api_key:
        log.error("BEEHIIV_API_KEY not set, skipping newsletter")
        return False

    pub_id = get_beehiiv_publication_id()

    payload = {
        "title": subject,
        "subtitle": "Weekly rankings movers and highlights",
        "status": "confirmed",
        "content_html": html,
    }

    resp = requests.post(
        f"{BEEHIIV_API_URL}/publications/{pub_id}/posts",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )

    if resp.status_code in (200, 201):
        post_id = resp.json().get("data", {}).get("id", "unknown")
        log.info(f"Newsletter published to Beehiiv (post_id={post_id})")
        return True

    log.error(f"Beehiiv publish failed ({resp.status_code}): {resp.text[:500]}")
    return False


# ---------------------------------------------------------------------------
# Blog post generation
# ---------------------------------------------------------------------------

BLOG_DIR = PROJECT_ROOT / "frontend" / "content" / "blog"
BLOG_TOPICS_PATH = PROJECT_ROOT / "brand" / "blog-topics.json"


def load_blog_topic_queue() -> list[dict]:
    """Load SEO topic queue from brand/blog-topics.json."""
    if not BLOG_TOPICS_PATH.exists():
        log.warning(f"Blog topic queue not found: {BLOG_TOPICS_PATH}")
        return []
    return json.loads(BLOG_TOPICS_PATH.read_text(encoding="utf-8"))


def get_next_blog_topic(week_num: int) -> dict:
    """Pick the next blog topic from the SEO queue by week number."""
    queue = load_blog_topic_queue()
    if not queue:
        return {
            "type": "weekly_movers",
            "title": "This Week's Biggest Movers",
            "slug_prefix": "weekly-movers",
            "target_keyword": "youth soccer rankings",
            "tags": ["Rankings"],
            "faq": [],
        }
    return queue[week_num % len(queue)]


def _movers_table(teams: list[dict], direction: str = "up") -> str:
    """Build a markdown table of movers."""
    prefix = "+" if direction == "up" else "-"
    rows = [
        f"| #{t.get('current_rank', '?')} | {t.get('team_name', '')} "
        f"| {t.get('state_code', t.get('state', ''))} "
        f"| {prefix}{abs(t.get('rank_change', 0))} |"
        for t in teams
    ]
    header = "| Rank | Team | State | Change |\n|------|------|-------|--------|\n"
    return header + "\n".join(rows)


def _faq_section(faq_items: list[dict]) -> str:
    """Build a markdown FAQ section from topic FAQ entries."""
    if not faq_items:
        return ""
    lines = ["## Frequently Asked Questions\n"]
    for item in faq_items:
        lines.append(f"**{item['q']}**\n")
        lines.append(f"{item['a']}\n")
    return "\n".join(lines)


def _filter_by_state(teams: list[dict], state: str) -> list[dict]:
    """Filter team list to a specific state code."""
    return [t for t in teams if (t.get("state_code") or t.get("state", "")) == state]


def _build_blog_body(data: dict, topic: dict) -> str:
    """Build blog post body based on topic type."""
    topic_type = topic.get("type", "weekly_movers")
    # None when unavailable; each branch drops its count sentence rather than
    # publishing a made-up number.
    total = f"{data['total_teams']:,}" if data["total_teams"] else None
    biggest = data.get("biggest_jump", 0)
    keyword = topic.get("target_keyword", "youth soccer rankings")
    climbers_table = _movers_table(data["climbers"], "up")
    fallers_table = _movers_table(data["fallers"], "down")
    faq = _faq_section(topic.get("faq", []))
    spotlight_state = data.get("spotlight_state", "USA")

    if topic_type == "state_rankings":
        state = topic["state"]
        state_climbers = _filter_by_state(data["climbers"], state)
        state_fallers = _filter_by_state(data["fallers"], state)
        ct = _movers_table(state_climbers or data["climbers"], "up")
        ft = _movers_table(state_fallers or data["fallers"], "down")
        tracking_line = (
            f"We track {total} teams nationally, and here's what moved in {state} this week.\n\n"
            if total
            else f"Here's what moved in {state} this week.\n\n"
        )
        return (
            f"Every Monday, PitchRank updates {keyword} across all leagues.\n"
            f"{tracking_line}"
            f"## Top Movers in {state} This Week\n\n{ct}\n\n"
            f"## Biggest Drops in {state}\n\n{ft}\n\n"
            f"## How {state} Compares Nationally\n\n"
            f"{state} is one of the most competitive states in youth soccer.\n"
            f"PitchRank ranks every team in {state} on the same scale as teams\n"
            f"in all 50 states — same algorithm, same methodology, real game data.\n\n"
            f"## What This Means for {state} Parents\n\n"
            f"If your team is climbing, the data shows consistent results against\n"
            f"quality opponents. If you're dropping, look at upcoming strength of\n"
            f"schedule. Rankings shift every week.\n\n"
            f"{faq}\n"
            f"**[See all {state} rankings →](https://pitchrank.io/rankings)**\n"
        )

    if topic_type == "league_comparison":
        across = f" across {total} teams" if total else ""
        return (
            f"One of the most common questions in youth soccer: {keyword} — which\n"
            f"league is better? PitchRank's cross-league calibration makes a\n"
            f"data-driven comparison possible{across}.\n\n"
            f"## This Week's Top Movers\n\n{climbers_table}\n\n"
            f"## How PitchRank Compares Leagues\n\n"
            f"PitchRank uses a 13-layer algorithm that normalizes across leagues.\n"
            f"Whether your team plays ECNL, MLS NEXT, GA, or a state league,\n"
            f"the same methodology applies: real game results, strength of schedule,\n"
            f"and margin analysis.\n\n"
            f"## Biggest Drops\n\n{fallers_table}\n\n"
            f"## What Parents Should Know\n\n"
            f"League labels don't tell the whole story. Some state league teams\n"
            f"outperform ECNL teams at the same age group. The data changes weekly.\n\n"
            f"{faq}\n"
            f"**[Compare leagues →](https://pitchrank.io/rankings)**\n"
        )

    if topic_type == "methodology":
        ranked_intro = f"ranked {total} youth soccer teams" if total else "ranked youth soccer teams"
        teams_bullet = f"- **{total}** teams ranked\n" if total else ""
        return (
            f"This week, PitchRank {ranked_intro} across\n"
            f"all 50 states. Here's how we did it and what the data showed.\n\n"
            f"## This Week by the Numbers\n\n"
            f"{teams_bullet}"
            f"- **50** states covered\n"
            f"- **+{biggest}** biggest single rank jump\n"
            f"- Rankings updated every Monday\n\n"
            f"## How the Algorithm Works\n\n"
            f"PitchRank's 13-layer algorithm (v53e + ML) analyzes real game\n"
            f"results across every league. It factors in strength of schedule,\n"
            f"margin of victory, opponent quality, and cross-league calibration.\n"
            f"No tournament points. No politics. Just data.\n\n"
            f"## Top Movers This Week\n\n{climbers_table}\n\n"
            f"{faq}\n"
            f"**[See the full rankings →](https://pitchrank.io/rankings)**\n"
        )

    if topic_type == "age_group":
        age_group = topic.get("age_group", "U14")
        ranks_clause = f"ranks {total} teams" if total else "ranks teams"
        return (
            f"Looking for the {keyword}? PitchRank {ranks_clause} across\n"
            f"all age groups every Monday. Here's what moved at {age_group} this week.\n\n"
            f"## Top {age_group} Movers This Week\n\n{climbers_table}\n\n"
            f"## Biggest Drops at {age_group}\n\n{fallers_table}\n\n"
            f"## State Spotlight: {spotlight_state}\n\n"
            f"{spotlight_state} saw the most rank movement this week across all age groups.\n\n"
            f"{faq}\n"
            f"**[See {age_group} rankings →](https://pitchrank.io/rankings)**\n"
        )

    # weekly_movers (default fallback)
    top = data["climbers"][0] if data["climbers"] else {}
    top_attr = ""
    if top:
        top_attr = f", earned by **{top.get('team_name', '')}** from {top.get('state_code') or top.get('state', '')}"
    for_teams = f"for {total} teams" if total else "for teams"
    return (
        f"Every Monday, PitchRank updates youth soccer rankings {for_teams}\n"
        f"across all 50 states. Here are this week's biggest movers.\n\n"
        f"## Biggest Climbers\n\n{climbers_table}\n\n"
        f"## Biggest Drops\n\n{fallers_table}\n\n"
        f"## What Drove the Movement\n\n"
        f"The biggest single jump this week was **+{biggest} spots**{top_attr}.\n"
        f"Rankings factor in strength of schedule, margin of victory, and opponent quality.\n\n"
        f"{faq}\n"
        f"**[See the full rankings →](https://pitchrank.io/rankings)**\n"
    )


def fetch_age_group_movers(supabase, age_group: str, limit: int = 5) -> dict:
    """Fetch climbers/fallers scoped to one age group via get_biggest_movers.

    The age_group template labels its tables "Top {age_group} Movers", so the
    movers must be age-scoped — the global data["climbers"]/["fallers"] mix ages.
    """

    def _movers(direction: str) -> list[dict]:
        resp = supabase.rpc(
            "get_biggest_movers",
            {"p_days": 7, "p_limit": limit, "p_direction": direction, "p_age_group": age_group},
        ).execute()
        return resp.data or []

    return {"climbers": _movers("up"), "fallers": _movers("down")}


def fetch_state_movers(supabase, state: str, limit: int = 5) -> dict:
    """Fetch climbers/fallers scoped to one state cohort via get_biggest_state_movers.

    State cohorts are far smaller than national ones, so the deltas are believable
    and current_rank is the team's rank within its state, not nationally.
    """

    def _movers(direction: str) -> list[dict]:
        resp = supabase.rpc(
            "get_biggest_state_movers",
            {"p_state": state, "p_limit": limit, "p_direction": direction},
        ).execute()
        return resp.data or []

    return {"climbers": _movers("up"), "fallers": _movers("down")}


def generate_blog_post(data: dict, supabase=None) -> tuple[str, str]:
    """Generate a weekly SEO-targeted blog post from ranking data.

    Reads the topic queue from brand/blog-topics.json and picks the next
    topic based on ISO week number. Returns (filename, markdown_content).
    age_group topics scope their movers to that age via Supabase when available.
    """
    dt = data["date"]
    week_num = dt.isocalendar()[1]
    date_str = dt.strftime("%Y-%m-%d")
    date_display = dt.strftime("%B %d, %Y")
    total = f"{data['total_teams']:,}" if data["total_teams"] else None

    topic = get_next_blog_topic(week_num)
    title = topic.get("title", "Youth Soccer Rankings Update")
    if total:
        title = title.replace("{total}", total)
    else:
        # Count-free title variant — collapse the placeholder and any doubled spaces
        title = " ".join(title.replace("{total}", "").split())
    slug = f"{date_str}-{topic.get('slug_prefix', 'weekly-update')}"
    tags = topic.get("tags", ["Rankings"])
    target_keyword = topic.get("target_keyword", "youth soccer rankings")

    # State and age posts label their movers by that scope, so fetch scoped movers.
    body_data = data
    if supabase is not None:
        try:
            if topic.get("type") == "age_group":
                body_data = {**data, **fetch_age_group_movers(supabase, topic["age_group"])}
            elif topic.get("type") == "state_rankings":
                body_data = {**data, **fetch_state_movers(supabase, topic["state"])}
        except Exception as e:
            log.warning(f"Scoped movers fetch failed ({topic.get('type')}); falling back to national movers: {e}")

    # Build body using the topic type's template
    body = _build_blog_body(body_data, topic)

    # Estimate reading time
    word_count = len(body.split())
    reading_time = f"{max(1, word_count // 200)} min read"

    # Build SEO-optimized excerpt
    state = topic.get("state", "")
    age_group = topic.get("age_group", "")
    if state:
        moved_clause = (
            f" See which {state} teams moved the most across {total} ranked teams."
            if total
            else f" See which {state} teams moved the most this week."
        )
        excerpt = f"This week's {state} youth soccer rankings update.{moved_clause}"
    elif age_group:
        rankings_clause = (
            f"Rankings for {total} teams updated every Monday." if total else "Rankings updated every Monday."
        )
        excerpt = f"Best {age_group} soccer teams this week. {rankings_clause}"
    elif total:
        excerpt = f"Weekly youth soccer rankings update for {date_display}. {total} teams ranked across all 50 states."
    else:
        excerpt = f"Weekly youth soccer rankings update for {date_display}. Teams ranked across all 50 states."

    # Build full markdown with frontmatter
    frontmatter = {
        "title": title,
        "slug": slug,
        "excerpt": excerpt,
        "author": "PitchRank Team",
        "date": date_str,
        "readingTime": reading_time,
        "tags": tags,
        "target_keyword": target_keyword,
        "image": "/api/infographic/movers?platform=twitter",
    }

    # Serialize frontmatter as JSON values for safety (gray-matter parses both)
    fm_lines = []
    for k, v in frontmatter.items():
        fm_lines.append(f"{k}: {json.dumps(v)}")
    fm_yaml = "\n".join(fm_lines)
    markdown = f"---\n{fm_yaml}\n---\n\n# {title}\n\n{body}"

    topic_type = topic.get("type", "weekly_movers")
    filename = f"{slug}.md"
    log.info(f"Blog post generated: {filename} ({word_count} words, topic={topic_type}, keyword={target_keyword})")
    return filename, markdown


def commit_and_push_blog_post(filename: str, content: str) -> bool:
    """Write blog post to frontend/content/blog/ and push to main.

    Uses [skip ci] in the commit message to prevent GitHub Actions loops.
    Note: GITHUB_TOKEN pushes don't trigger third-party webhooks. If Vercel
    doesn't auto-deploy, configure a Vercel deploy hook as a workaround.
    """
    BLOG_DIR.mkdir(parents=True, exist_ok=True)
    filepath = BLOG_DIR / filename
    filepath.write_text(content, encoding="utf-8")
    log.info(f"Wrote blog post: {filepath}")

    try:
        subprocess.run(
            ["git", "add", str(filepath)],
            check=True,
            cwd=PROJECT_ROOT,
            timeout=30,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"[blog] Weekly: {filename} [skip ci]"],
            check=True,
            cwd=PROJECT_ROOT,
            timeout=30,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            check=True,
            cwd=PROJECT_ROOT,
            timeout=60,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "push", "origin", "main"],
            check=True,
            cwd=PROJECT_ROOT,
            timeout=120,
            capture_output=True,
            text=True,
        )
        log.info("Blog post committed and pushed to main")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = getattr(e, "stderr", "")
        log.error(f"Git operation failed: {e}\n{stderr}")
        return False


# ---------------------------------------------------------------------------
# Social post generation
# ---------------------------------------------------------------------------

SOCIAL_TEMPLATES = {
    "rankings_live": [
        (
            "New rankings are live.\n\n"
            "Where does your team stand?\n\n"
            "pitchrank.io/rankings\n\n"
            "#YouthSoccer #ClubSoccer #SoccerRankings"
        ),
        (
            "Monday means new rankings.\n\n"
            "{active_team_count} teams updated.\n\n"
            "pitchrank.io/rankings\n\n"
            "#YouthSoccer #SoccerRankings"
        ),
    ],
}


def format_rankings_live_caption(template: str, active_team_count: int) -> str:
    """Fill the live count, or drop the count line entirely — never a made-up number."""
    if "{active_team_count}" not in template:
        return template
    if active_team_count:
        return template.format(active_team_count=f"{active_team_count:,}")
    return "\n\n".join(seg for seg in template.split("\n\n") if "{active_team_count}" not in seg)


def build_top10_caption(state: str, age: int, gender: str) -> str:
    state_name = STATE_DISPLAY_NAMES.get(state, state)
    gender_label = "Boys" if gender == "male" else "Girls"
    return (
        f"{state_name} U{age} {gender_label} — Top 10 in the state.\n\n"
        "Full rankings: pitchrank.io/rankings\n\n"
        f"#YouthSoccer #SoccerRankings #{state}Soccer"
    )


def _matchup_cohort_label(game: dict) -> str:
    age = re.sub(r"\D", "", game.get("age_group") or "")
    gender_label = "Boys" if game.get("gender") == "M" else "Girls"
    return f"{game['state_code']} U{age} {gender_label}"


def build_big_games_caption(games: list[dict]) -> str:
    lines = "\n".join(
        f"⚔️ {g['home_team_name']} vs {g['away_team_name']} ({_matchup_cohort_label(g)})" for g in games[:5]
    )
    return (
        "Big games this weekend. Ranked vs ranked.\n\n"
        f"{lines}\n\n"
        "Full rankings: pitchrank.io/rankings\n\n"
        "#YouthSoccer #SoccerRankings"
    )


# Explicit labels instead of strftime('%a') — day names must not vary with locale.
_DAY_LABELS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _format_window_range(start_date, end_date) -> str:
    if start_date.month == end_date.month:
        return f"{start_date.strftime('%b')} {start_date.day}–{end_date.day}, {end_date.year}"
    return f"{start_date.strftime('%b')} {start_date.day} – {end_date.strftime('%b')} {end_date.day}, {end_date.year}"


def encode_big_games_payload(matchups: list[dict], start_date, end_date) -> str:
    """Base64url JSON consumed by /api/infographic/big-games (a pure renderer).

    Owns all label derivation: the RPC returns a bare DATE, so the day labels and
    the human range string are formatted here and rendered verbatim by the route.
    """
    games = []
    for m in matchups[:5]:
        gd = m["game_date"]
        if isinstance(gd, str):
            gd = datetime.strptime(gd, "%Y-%m-%d").date()
        age = re.sub(r"\D", "", m.get("age_group") or "")
        gender_label = "BOYS" if m.get("gender") == "M" else "GIRLS"
        games.append(
            {
                "cohort": f"{m['state_code']} · U{age} {gender_label}",
                "day": _DAY_LABELS[gd.weekday()],
                "home": {
                    "name": m["home_team_name"],
                    "club": m.get("home_club_name") or "",
                    "rank": m["home_state_rank"],
                },
                "away": {
                    "name": m["away_team_name"],
                    "club": m.get("away_club_name") or "",
                    "rank": m["away_state_rank"],
                },
                "state": m["state_code"],
            }
        )
    payload = {"v": 1, "range": _format_window_range(start_date, end_date), "games": games}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_social_posts(data: dict) -> list[dict]:
    """Generate the 5-post Instagram week: Mon live, 3x Tue Top-10, Thu big games."""
    posts = []
    monday = data["date"].replace(hour=12, minute=0, second=0, microsecond=0)

    # Ensure monday is actually a Monday; adjust if needed
    while monday.weekday() != 0:
        monday += timedelta(days=1)

    tuesday = monday + timedelta(days=1)
    tuesday_slots = [
        tuesday.replace(hour=9, minute=0),
        tuesday.replace(hour=12, minute=0),
        tuesday.replace(hour=17, minute=0),
    ]
    thursday = monday + timedelta(days=3, hours=7, minutes=30)  # Thu 7:30 PM MT

    # Post 1: Monday noon — Rankings announcement (mover-independent)
    template = random.choice(SOCIAL_TEMPLATES["rankings_live"])
    posts.append(
        {
            "text": format_rankings_live_caption(template, data.get("active_team_count") or 0),
            "media_url": f"{PITCHRANK_URL}/api/infographic/rankings-live?platform=instagram",
            "scheduled_at": monday,
            "type": "rankings_live",
        }
    )

    # Posts 2-4: Tuesday — rotating state Top-10s with team tagging
    for slot, cohort in zip(tuesday_slots, data.get("top10_cohorts") or []):
        posts.append(
            {
                "text": build_top10_caption(cohort["state"], cohort["age"], cohort["gender"]),
                "media_url": (
                    f"{PITCHRANK_URL}/api/infographic/state?state={cohort['state']}"
                    f"&age=u{cohort['age']}&gender={cohort['gender']}&platform=instagram"
                ),
                "scheduled_at": slot,
                "type": "top10",
                "_tag_target_ids": [t["team_id_master"] for t in cohort["teams"] if t.get("team_id_master")],
            }
        )

    # Post 5: Thursday evening — big weekend games (skipped when nothing qualifies)
    big_games = data.get("big_games") or []
    if big_games:
        window_start, window_end = data["big_games_window"]
        payload = encode_big_games_payload(big_games, window_start, window_end)
        posts.append(
            {
                "text": build_big_games_caption(big_games),
                "media_url": f"{PITCHRANK_URL}/api/infographic/big-games?platform=instagram&m={payload}",
                "scheduled_at": thursday,
                "type": "big_games",
                "_tag_target_ids": [
                    g[k]
                    for g in big_games[:5]
                    for k in ("home_team_id_master", "away_team_id_master")
                    if g.get(k)
                ],
            }
        )
    else:
        log.info("Big-games post skipped: no qualifying matchups this weekend")

    log.info(f"Generated {len(posts)} social posts")
    return posts


def generate_trend_posts(week_iso: str, data: dict) -> list[dict]:
    """Generate up to 3 trend-reaction X posts from brand/trend-research/<week>.json.

    User runs /last30days manually and writes the JSON each week. Schema:
        {"week": "2026-W23", "posts": [{"topic": ..., "hook": ..., "suggested_tweet": ..., "source_url": ...}]}
    """
    path = PROJECT_ROOT / "brand" / "trend-research" / f"{week_iso}.json"
    if not path.exists():
        log.error(f"Trend research file missing for {week_iso}: brand/trend-research/{week_iso}.json")
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error(f"Trend research file malformed ({path.name}): {e}")
        return []

    if payload.get("week") != week_iso:
        log.error(f"Trend research week mismatch: expected {week_iso}, got {payload.get('week')}")
        return []

    entries = payload.get("posts") or []
    valid: list[dict] = []
    for entry in entries:
        tweet = entry.get("suggested_tweet")
        if not isinstance(tweet, str) or not tweet.strip():
            log.warning(f"Skipping trend entry without suggested_tweet: {entry.get('topic', '?')}")
            continue
        valid.append(entry)

    if not valid:
        log.error(f"No valid trend entries in {path.name}")
        return []

    if len(valid) > 3:
        log.warning(f"Trend research has {len(valid)} valid entries; using first 3")
        valid = valid[:3]

    # Schedule across the week (MT)
    monday = data["date"].replace(hour=0, minute=0, second=0, microsecond=0)
    while monday.weekday() != 0:
        monday += timedelta(days=1)
    slots = [
        monday + timedelta(days=2, hours=12, minutes=30),  # Wed 12:30 PM MT
        monday + timedelta(days=4, hours=9),  # Fri 9:00 AM MT
        monday + timedelta(days=5, hours=11),  # Sat 11:00 AM MT
    ]

    posts = []
    for entry, when in zip(valid, slots):
        posts.append(
            {
                "text": entry["suggested_tweet"],
                "media_url": None,
                "scheduled_at": when,
                "type": "trend",
            }
        )

    log.info(f"Generated {len(posts)} trend posts for {week_iso}")
    return posts


# ---------------------------------------------------------------------------
# Postiz drafting
# ---------------------------------------------------------------------------


_IG_IDENTIFIERS = ("instagram", "instagram-standalone")


def get_postiz_integrations() -> dict[str, dict[str, str]]:
    """Fetch Postiz integrations and return {platform: {"id", "__type"}} for the platforms we use.

    `platform` is the logical name ("x" or "instagram"); `__type` carries the actual Postiz
    identifier ("instagram" for FB-linked, "instagram-standalone" for Instagram Login).
    Hardcoding `__type: "instagram"` would break drafts when the connected IG channel is
    the standalone variant — carry the identifier through to the payload to stay in sync.

    Fail-loud: returns {} on non-200, and only-found-platforms on partial discovery
    so the router can log per-post errors and exit-code reflects the partial outage.
    """
    api_key = os.getenv("POSTIZ_API_KEY")
    if not api_key:
        log.error("POSTIZ_API_KEY not set")
        return {}

    resp = requests.get(
        f"{POSTIZ_API_URL}/integrations",
        headers={"Authorization": api_key},
        timeout=60,
    )

    if resp.status_code != 200:
        log.error(f"Postiz integrations fetch failed ({resp.status_code}): {resp.text[:500]}")
        return {}

    found: dict[str, dict[str, str]] = {}
    for row in resp.json() or []:
        ident = row.get("identifier")
        rid = row.get("id")
        if not ident or not rid:
            continue
        if ident == "x" and "x" not in found:
            found["x"] = {"id": rid, "__type": "x"}
        elif ident in _IG_IDENTIFIERS and "instagram" not in found:
            found["instagram"] = {"id": rid, "__type": ident}

    missing = [p for p in ("x", "instagram") if p not in found]
    if missing:
        log.error(f"Postiz integrations missing required platform(s): {missing}")

    return found


def _upload_to_postiz(media_url: str, api_key: str) -> dict | None:
    """Fetch a public media URL and upload it to Postiz, returning {"id", "path"}.

    Postiz's POST /posts endpoint does NOT accept arbitrary public URLs in the
    image array — it requires a pre-uploaded media object from POST /upload.
    Returns None on any failure; caller should treat that as a draft failure.
    """
    try:
        media_resp = requests.get(media_url, timeout=60)
    except Exception as e:
        log.error(f"Media fetch failed for {media_url}: {e}")
        return None

    if media_resp.status_code != 200:
        log.error(f"Media fetch failed for {media_url} ({media_resp.status_code})")
        return None

    # Postiz validates by file extension, not Content-Type. Our @vercel/og infographic
    # URLs have no extension (e.g. "/api/infographic/movers?platform=instagram"), so we
    # derive one from the response Content-Type and append it to the filename.
    content_type = media_resp.headers.get("Content-Type", "image/png").split(";")[0].strip().lower()
    ext_by_type = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
        "video/mp4": ".mp4",
    }
    ext = ext_by_type.get(content_type, ".png")

    raw_name = media_url.rsplit("/", 1)[-1].split("?")[0] or "image"
    filename = raw_name if "." in raw_name else f"{raw_name}{ext}"

    try:
        upload_resp = requests.post(
            f"{POSTIZ_API_URL}/upload",
            headers={"Authorization": api_key},
            files={"file": (filename, media_resp.content, content_type)},
            timeout=120,
        )
    except Exception as e:
        log.error(f"Postiz upload exception: {e}")
        return None

    if upload_resp.status_code not in (200, 201):
        log.error(f"Postiz upload failed ({upload_resp.status_code}): {upload_resp.text[:500]}")
        return None

    data = upload_resp.json()
    if not data.get("id") or not data.get("path"):
        log.error(f"Postiz upload returned unexpected shape: {str(data)[:300]}")
        return None
    return {"id": data["id"], "path": data["path"]}


def _to_postiz_payload(post: dict, integration_id: str, settings_type: str) -> dict:
    """Translate a canonical post dict into a Postiz POST /posts request envelope.

    `settings_type` is the Postiz integration identifier ("x", "instagram", "instagram-standalone").
    It becomes the post settings `__type`, and also selects which platform branch to build.

    For IG posts, the caller is responsible for uploading media via _upload_to_postiz first
    and stashing the result in post["_uploaded_media"]. We do NOT pass raw media_url through
    here — Postiz rejects arbitrary URLs in the image array.
    """
    if settings_type == "x":
        parts = post.get("thread_parts") or [post["text"]]
        value = [{"content": t, "image": []} for t in parts]
        settings = {"__type": "x", "who_can_reply_post": "everyone"}
    elif settings_type in _IG_IDENTIFIERS:
        uploaded = post.get("_uploaded_media")
        image = [{"id": uploaded["id"], "path": uploaded["path"]}] if uploaded else []
        value = [{"content": post["text"], "image": image}]
        settings = {
            "__type": settings_type,
            "post_type": "post",
            "is_trial_reel": False,
            "collaborators": [],
        }
    else:
        raise ValueError(f"Unsupported Postiz platform: {settings_type}")

    return {
        "type": "draft",
        "date": post["scheduled_at"].isoformat(),
        "shortLink": False,
        "tags": [],
        "posts": [
            {
                "integration": {"id": integration_id},
                "value": value,
                "settings": settings,
            }
        ],
    }


def draft_to_postiz(posts: list[dict], integrations: dict[str, dict[str, str]], dry_run: bool) -> list[bool]:
    """Create Postiz drafts for each post; return per-post success list."""
    api_key = os.getenv("POSTIZ_API_KEY") if not dry_run else None
    if not dry_run and not api_key:
        log.error("POSTIZ_API_KEY not set, skipping Postiz drafts")
        return [False] * len(posts)

    results = []
    for post in posts:
        # Trend posts and X threads route to X; everything else to Instagram.
        platform = "x" if post["type"] in ("x_thread", "trend") else "instagram"
        integration = integrations.get(platform)
        if not integration:
            log.error(f"No Postiz integration for routed platform; skipping [{post['type']}]")
            results.append(False)
            continue

        # IG posts must upload media to Postiz first; raw URLs are rejected by POST /posts.
        if not dry_run and platform == "instagram" and post.get("media_url"):
            uploaded = _upload_to_postiz(post["media_url"], api_key)
            if not uploaded:
                log.error(f"IG media upload failed; skipping draft [{post['type']}]")
                results.append(False)
                continue
            post["_uploaded_media"] = uploaded

        payload = _to_postiz_payload(post, integration["id"], integration["__type"])

        if dry_run:
            results.append(True)
            continue

        resp = requests.post(
            f"{POSTIZ_API_URL}/posts",
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )

        if resp.status_code in (200, 201):
            log.info(
                f"Drafted [{post['type']}] to Postiz ({integration['__type']}) "
                f"for {post['scheduled_at'].strftime('%A %I:%M %p MT')}"
            )
            results.append(True)
        else:
            log.error(f"Postiz draft failed [{post['type']}] ({resp.status_code}): {resp.text[:500]}")
            results.append(False)

    return results


def enrich_post_with_handles(post: dict, supabase, target_team_ids: list[str]) -> dict:
    """Append `\\n\\nTagging: @h1 @h2 ...` to post['text'] using confirmed IG handles.

    Mutates post in place and writes post['_tag_stats'] for downstream visibility.
    Picks one handle per team (team-level preferred, club-level fallback). Note:
    this differs from the site's caption builder in
    frontend/hooks/useInstagramHandles.ts:collectHandlesForCaption, which pushes
    both team AND club handles when both exist — Postiz drafts stay lean.
    """
    target_count = len(target_team_ids)
    if not target_team_ids:
        post["_tag_stats"] = {"tagged_count": 0, "target_count": 0, "missing_team_ids": []}
        return post

    statuses = ["confirmed"]
    if os.getenv("POSTIZ_TAG_INCLUDE_AUTO_APPROVED", "false").lower() == "true":
        statuses.append("auto_approved")

    try:
        resp = (
            supabase.from_("team_instagram_handles")
            .select("team_id, handle, profile_level")
            .in_("team_id", target_team_ids)
            .in_("review_status", statuses)
            .execute()
        )
        rows = resp.data or []
    except Exception as e:
        log.warning(f"IG handle lookup failed for [{post['type']}]: {e}")
        post["_tag_stats"] = {
            "tagged_count": 0,
            "target_count": target_count,
            "missing_team_ids": list(target_team_ids),
            "error": str(e),
        }
        return post

    # Bucket by team_id: prefer team-level, fall back to club-level
    per_team: dict[str, dict[str, str]] = {}
    for row in rows:
        bucket = per_team.setdefault(row["team_id"], {"team": None, "club": None})
        bucket[row["profile_level"]] = row["handle"]

    seen: set[str] = set()
    handles: list[str] = []
    tagged_ids: set[str] = set()
    for tid in target_team_ids:
        bucket = per_team.get(tid)
        if not bucket:
            continue
        chosen = bucket.get("team") or bucket.get("club")
        if not chosen:
            continue
        key = chosen.lower()
        if key in seen:
            tagged_ids.add(tid)
            continue
        seen.add(key)
        handles.append(f"@{chosen}")
        tagged_ids.add(tid)

    if not handles:
        post["_tag_stats"] = {
            "tagged_count": 0,
            "target_count": target_count,
            "missing_team_ids": list(target_team_ids),
        }
        return post

    # Cap mentions at 10 for naturalness (IG hard limit is 20)
    if len(handles) > 10:
        handles = handles[:10]

    # IG caption hard limit is 2,200 chars
    suffix = "\n\nTagging: " + " ".join(handles)
    dropped = 0
    while handles and len(post["text"]) + len(suffix) > 2200:
        handles.pop()
        dropped += 1
        suffix = "\n\nTagging: " + " ".join(handles)
    if dropped:
        log.warning(f"Truncated {dropped} IG @-mentions to stay under 2,200 chars [{post['type']}]")

    if handles:
        post["text"] = post["text"] + suffix

    missing = [tid for tid in target_team_ids if tid not in tagged_ids]
    post["_tag_stats"] = {
        "tagged_count": len(handles),
        "target_count": target_count,
        "missing_team_ids": missing,
    }
    return post


def _resolve_tag_targets(post_type: str, data: dict) -> list[str]:
    """Tag targets for post types that don't carry their own _tag_target_ids.

    rankings_live is generic (no team claims); top10/big_games supply their own
    ids at generation. The remaining types (x_thread, trend) are never tagged.
    """
    return []


# ---------------------------------------------------------------------------
# X thread composition
# ---------------------------------------------------------------------------


def _format_cohort(team: dict) -> str:
    """Format age group + gender as e.g. 'U14 Boys'."""
    ag = (team.get("age_group") or "").upper()
    g = team.get("gender", "")
    gender_label = "Boys" if g == "Male" else "Girls" if g == "Female" else ""
    return f"{ag} {gender_label}".strip()


def _milestone_line(m: dict) -> str:
    """Format one milestone entry for a tweet, e.g. '• TeamName (U14 Boys, TX) → now #8'."""
    name = m.get("team_name", "Unknown")[:30]
    cohort = _format_cohort(m)
    state = m.get("state_code", "")
    rank = m.get("rank_in_cohort", "?")
    label = f"{cohort}, {state}" if state else cohort
    return f"• {name} ({label}) → now #{rank}"


def generate_x_thread_posts(data: dict) -> dict:
    """Compose a 4-tweet thread (milestone-driven) into the canonical post-dict shape.

    Returns a single dict with `thread_parts` carrying the per-tweet split; downstream
    Postiz translation reads `thread_parts` for chained replies.
    """
    milestones = data.get("milestones", [])
    # None when unavailable; count-bearing tweets get count-free variants instead
    # of a made-up number.
    total = f"{data['total_teams']:,}" if data["total_teams"] else None
    tweets: list[str] = []

    # Group milestones by tier
    by_tier: dict[int, list[dict]] = {}
    for m in milestones:
        by_tier.setdefault(m["milestone"], []).append(m)

    top10 = by_tier.get(10, [])
    top25 = by_tier.get(25, [])
    top50 = by_tier.get(50, [])
    top100 = by_tier.get(100, [])

    milestone_count = len(milestones)

    # Tweet 1: Hook
    if milestone_count > 0:
        if top10:
            lead = top10[0]
            tweets.append(
                f"{lead.get('team_name', 'A team')} just cracked the top 10 "
                f"in {_format_cohort(lead)}.\n\n"
                f"{milestone_count} teams hit new milestones this week."
            )
        else:
            best = milestones[0]
            tweets.append(
                f"{best.get('team_name', 'A team')} broke into the top "
                f"{best['milestone']} in {_format_cohort(best)}.\n\n"
                f"{milestone_count} teams hit new milestones this week."
            )
    else:
        tweets.append("New youth soccer rankings are live.\n\nHere's who's moving up.")

    # Tweet 2: Top 10 & 25 milestones
    lines = []
    if top10:
        lines.append("New to the top 10:")
        lines.extend(_milestone_line(m) for m in top10[:3])
    if top25:
        if lines:
            lines.append("")
        lines.append("Cracked the top 25:")
        lines.extend(_milestone_line(m) for m in top25[:3])
    if lines:
        tweets.append("\n".join(lines))

    # Tweet 3: Top 50 & 100 milestones
    lines = []
    if top50:
        lines.append("Now in the top 50:")
        lines.extend(_milestone_line(m) for m in top50[:3])
    if top100:
        if lines:
            lines.append("")
        lines.append("Entered the top 100:")
        lines.extend(_milestone_line(m) for m in top100[:3])
    if lines:
        tweets.append("\n".join(lines))

    # If no milestones at all, fall back to a general tweet
    if len(tweets) == 1:
        updated_for = f"Rankings updated for {total} teams" if total else "Rankings updated"
        tweets.append(f"{updated_for} across all 50 states.\n\nSame algorithm. Real game data. No opinions.")

    # Tweet 4 (final): CTA
    cta_lead = f"{total} teams ranked every Monday." if total else "New rankings every Monday."
    tweets.append(f"{cta_lead}\n\npitchrank.io/rankings")

    # Scheduled at Monday noon MT (same as the rankings_live post)
    monday = data["date"].replace(hour=12, minute=0, second=0, microsecond=0)
    while monday.weekday() != 0:
        monday += timedelta(days=1)

    joined = "\n---\n".join(tweets)
    log.info(f"Generated {len(tweets)}-tweet thread ({milestone_count} milestones)")
    return {
        "text": joined,
        "media_url": None,
        "scheduled_at": monday,
        "type": "x_thread",
        "thread_parts": tweets,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def save_artifacts(newsletter_html: str, drafts: list[dict], data: dict):
    """Save generated content as artifacts for debugging."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    date_str = data["date"].strftime("%Y%m%d")

    html_path = ARTIFACTS_DIR / f"newsletter_{date_str}.html"
    html_path.write_text(newsletter_html, encoding="utf-8")
    log.info(f"Saved newsletter HTML: {html_path}")

    posts_path = ARTIFACTS_DIR / f"social_posts_{date_str}.json"
    serializable = []
    for p in drafts:
        entry = {
            "type": p["type"],
            "text": p["text"],
            "media_url": p.get("media_url"),
            "scheduled_at": p["scheduled_at"].isoformat(),
        }
        if p.get("thread_parts"):
            entry["thread_parts"] = p["thread_parts"]
        if p.get("_tag_stats"):
            entry["_tag_stats"] = p["_tag_stats"]
        serializable.append(entry)
    posts_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
    log.info(f"Saved social posts JSON: {posts_path}")


def live_run_failed(
    newsletter_ok: bool, newsletter_skipped: bool, drafts_attempted: bool, draft_results: list[bool]
) -> bool:
    """True when a live run delivered nothing it attempted (the exit-1 condition).

    A deliberately skipped newsletter (quiet week) is neither success nor failure:
    it must not mask an all-drafts-failed outage, nor trip a failure on its own
    when drafts went out.
    """
    attempted = (not newsletter_skipped) or drafts_attempted
    succeeded = newsletter_ok or any(draft_results)
    return attempted and not succeeded


def main():
    parser = argparse.ArgumentParser(description="PitchRank Marketing Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Generate content without publishing")
    parser.add_argument(
        "--postiz-only",
        action="store_true",
        help="Live mode but skip Beehiiv newsletter send and blog post commit. "
        "Use this to smoke-test Postiz drafting without firing the other side effects.",
    )
    args = parser.parse_args()

    if args.dry_run and args.postiz_only:
        log.warning("--postiz-only is ignored in --dry-run mode")

    log.info("=" * 60)
    log.info("PitchRank Marketing Pipeline")
    mode = "DRY RUN" if args.dry_run else ("LIVE (Postiz-only)" if args.postiz_only else "LIVE")
    log.info(f"Mode: {mode}")
    log.info("=" * 60)

    # Step 1: Fetch data
    try:
        supabase = get_supabase_client()
        data = fetch_ranking_highlights(supabase)
    except Exception as e:
        log.error(f"Failed to fetch ranking data: {e}")
        sys.exit(1)

    # Freshness gate: announcing "new rankings are live" on stale data is worse
    # than skipping a week. Mover-emptiness is NOT the staleness signal — quiet
    # weeks are legitimate; mover-centric outputs are gated separately below.
    last_calculated = fetch_rankings_last_calculated(supabase)
    if rankings_are_stale(last_calculated):
        log.warning(f"Rankings look stale (last_calculated={last_calculated}) — not announcing. Exiting.")
        sys.exit(0)

    has_movers = bool(data["climbers"] or data["fallers"])
    if not has_movers:
        log.warning("No movers this week — skipping blog/newsletter/X thread; IG posts still run.")

    # Step 2: Generate blog post (newsletter uses the same content; both are
    # mover-centric, so a quiet week skips them)
    blog_filename, blog_content, blog_body_md, blog_title = "", "", "", ""
    if has_movers:
        try:
            blog_filename, blog_content = generate_blog_post(data, supabase)
            # Extract the markdown body (after frontmatter) for the newsletter
            parts = blog_content.split("---", 2)
            if len(parts) >= 3:
                full_md = parts[2].strip()
                # Strip the leading H1 (title) — it's in the subject line
                lines = full_md.split("\n")
                if lines and lines[0].startswith("# "):
                    blog_title = lines[0].lstrip("# ").strip()
                    blog_body_md = "\n".join(lines[1:]).strip()
                else:
                    blog_body_md = full_md
        except Exception as e:
            log.error(f"Blog generation failed: {e}")

    # Step 3: Generate newsletter from blog content
    newsletter_html, subject = "", ""
    if has_movers:
        newsletter_html = generate_newsletter_html(data, blog_body_md)
        subject = generate_newsletter_subject(data, blog_title)
        log.info(f"Subject: {subject}")

    # Step 4-5: Generate all social drafts (kill-switch gated)
    drafts_enabled = os.getenv("POSTIZ_DRAFTS_ENABLED", "true").lower() == "true"
    current_iso_week = data["date"].strftime("%G-W%V")
    social_posts: list[dict] = []
    x_thread_post: dict = {"thread_parts": []}
    all_drafts: list[dict] = []
    if drafts_enabled:
        social_posts = generate_social_posts(data)
        # Enrich IG-bound posts with team handles (post-pass; keeps generators
        # platform-agnostic). Posts that know their own teams carry
        # _tag_target_ids; the resolver is the fallback for the rest.
        for post in social_posts:
            targets = post.get("_tag_target_ids") or _resolve_tag_targets(post["type"], data)
            if targets:
                enrich_post_with_handles(post, supabase, targets)
        if has_movers:
            try:
                x_thread_post = generate_x_thread_posts(data)
            except Exception as e:
                log.error(f"X thread generation failed: {e}")
                x_thread_post = {"thread_parts": []}
        trend_posts = generate_trend_posts(current_iso_week, data)
        all_drafts = list(social_posts)
        if x_thread_post.get("thread_parts"):
            all_drafts.append(x_thread_post)
        all_drafts.extend(trend_posts)
    else:
        log.warning("POSTIZ_DRAFTS_ENABLED=false — skipping social drafts entirely")

    # Save artifacts (always, for debugging)
    save_artifacts(newsletter_html, all_drafts, data)

    if args.dry_run:
        log.info("")
        log.info("--- DRY RUN OUTPUT ---")
        log.info(f"Newsletter subject: {subject}")
        log.info(f"Newsletter length: {len(newsletter_html):,} bytes")
        log.info("")
        if blog_filename:
            log.info(f"Blog post: {blog_filename} ({len(blog_content):,} bytes)")
        log.info("")
        log.info(f"Top-10 combos: {data.get('top10_combos')}")
        big_games = data.get("big_games") or []
        if big_games:
            for g in big_games:
                log.info(
                    f"Big game: {g['home_team_name']} (#{g['home_state_rank']}) vs "
                    f"{g['away_team_name']} (#{g['away_state_rank']}) "
                    f"[{g['state_code']} {g['age_group']} {g['gender']}] on {g['game_date']}"
                )
        else:
            log.info("Big-games post skipped: no qualifying matchups")
        log.info("")
        for post in social_posts:
            log.info(f"[{post['type']}] {post['scheduled_at'].strftime('%A %I:%M %p MT')}")
            if post.get("media_url"):
                log.info(f"  Image: {post['media_url']}")
            if post.get("_tag_stats"):
                log.info(f"  Tags: {post['_tag_stats']}")
            log.info(post["text"])
            log.info("")
        if x_thread_post.get("thread_parts"):
            log.info("--- X THREAD ---")
            for i, tweet in enumerate(x_thread_post["thread_parts"]):
                log.info(f"Tweet {i + 1}/{len(x_thread_post['thread_parts'])}: {tweet}")
                log.info("")
        if drafts_enabled:
            stub_integrations = {
                "x": {"id": "DRY_RUN_X_ID", "__type": "x"},
                "instagram": {"id": "DRY_RUN_IG_ID", "__type": "instagram"},
            }
            dry_draft_results = draft_to_postiz(all_drafts, stub_integrations, dry_run=True)
            log.info(f"DRY RUN: {sum(dry_draft_results)}/{len(dry_draft_results)} would be drafted to Postiz")
        log.info("Artifacts saved. No Postiz API calls made (Supabase reads ran for data fetch + handle enrichment).")
        return

    # Step 6: Publish newsletter to Beehiiv
    newsletter_ok = False
    newsletter_skipped = False
    if args.postiz_only:
        log.info("--postiz-only: skipping Beehiiv newsletter send")
    elif not has_movers:
        # Quiet week: the newsletter is mover-centric, so skip it. Track the skip
        # separately from success so the exit guard doesn't read it as "delivered".
        log.info("No movers: skipping Beehiiv newsletter send")
        newsletter_skipped = True
    else:
        try:
            newsletter_ok = publish_to_beehiiv(newsletter_html, subject)
        except Exception as e:
            log.error(f"Newsletter publishing failed: {e}")

    # Step 7: Publish blog post (commit + push)
    blog_ok = False
    if args.postiz_only:
        log.info("--postiz-only: skipping blog post commit")
    elif not has_movers:
        log.info("No movers: skipping blog post commit")
    else:
        try:
            if blog_filename and blog_content:
                blog_ok = commit_and_push_blog_post(blog_filename, blog_content)
        except Exception as e:
            log.error(f"Blog publishing failed: {e}")

    # Step 8: Draft all social posts to Postiz (X thread + Instagram + trend)
    draft_results: list[bool] = []
    try:
        if drafts_enabled and all_drafts:
            integrations = get_postiz_integrations()
            draft_results = draft_to_postiz(all_drafts, integrations, dry_run=False)
    except Exception as e:
        log.error(f"Postiz drafting failed: {e}")

    # Summary
    newsletter_status = "SENT" if newsletter_ok else "SKIPPED" if newsletter_skipped else "FAILED"
    log.info("")
    log.info("=" * 60)
    log.info("PIPELINE COMPLETE")
    log.info(f"  Newsletter: {newsletter_status}")
    log.info(f"  Blog: {'PUBLISHED' if blog_ok else 'SKIPPED'}")
    log.info(f"  Social Drafts: {sum(draft_results)}/{len(draft_results)} drafted to Postiz")
    log.info("=" * 60)

    # --postiz-only is a smoke-test mode: any draft failure (or no drafts at all) is a
    # validation failure and must exit non-zero so CI / operator notices. Don't fall through
    # to the lenient newsletter check below — newsletter is intentionally skipped in this mode.
    if args.postiz_only:
        if not draft_results or not all(draft_results):
            log.error(f"--postiz-only smoke test failed: {sum(draft_results)}/{len(draft_results)} drafts succeeded")
            sys.exit(1)
        return

    # Live mode: exit 1 when nothing we attempted to deliver succeeded. A quiet-week
    # newsletter skip is not a delivery, so an all-drafts-failed quiet week still exits
    # non-zero instead of masking the outage; partial outages surface via the
    # individual draft_results entries.
    if live_run_failed(newsletter_ok, newsletter_skipped, bool(all_drafts), draft_results):
        sys.exit(1)


if __name__ == "__main__":
    main()
