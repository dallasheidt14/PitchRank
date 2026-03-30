#!/usr/bin/env python3
"""
Marketing Pipeline — Automated newsletter + social posting after rankings update

Chains to Calculate Rankings workflow. Fetches ranking highlights from Supabase,
generates a newsletter, publishes to Beehiiv, and schedules social posts to Buffer.

Run: python3 scripts/marketing_pipeline.py [--dry-run]
"""

import argparse
import json
import logging
import os
import random
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

# Buffer API
BUFFER_API_URL = "https://api.bufferapp.com/1"

# Beehiiv API
BEEHIIV_API_URL = "https://api.beehiiv.com/v2"


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
                if st:
                    state_movement[st] = state_movement.get(st, 0) + abs(team.get("rank_change", 0))
            if state_movement:
                spotlight_state = max(state_movement, key=state_movement.get)
                # Top 3 teams from that state
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

    log.info(
        f"Highlights: {len(climbers)} climbers, {len(fallers)} fallers, "
        f"{total_teams} total teams, spotlight: {spotlight_state}"
    )
    return data


# ---------------------------------------------------------------------------
# Newsletter generation
# ---------------------------------------------------------------------------


def _table_row(team: dict, index: int, change_prefix: str = "+") -> str:
    """Build an HTML table row for a team."""
    bg = "#ffffff" if index % 2 == 0 else "#f8f9fa"
    rank = team.get("current_rank", team.get("rank", ""))
    name = team.get("team_name", "")
    state = team.get("state_code", team.get("state", ""))
    change = team.get("rank_change", 0)

    # Truncate long names for mobile
    display_name = name[:28] + "..." if len(name) > 30 else name

    change_color = "#0B5345" if change_prefix == "+" else "#c0392b"
    change_str = f"{change_prefix}{abs(change)}"

    return (
        f'    <tr style="background-color:{bg};">'
        f'<td style="padding:8px 10px;font-size:13px;">#{rank}</td>'
        f'<td style="padding:8px 10px;font-size:13px;font-weight:600;">{display_name}</td>'
        f'<td style="padding:8px 10px;font-size:13px;">{state}</td>'
        f'<td style="padding:8px 10px;font-size:13px;text-align:right;'
        f'font-weight:700;color:{change_color};">{change_str}</td>'
        f"</tr>"
    )


def _spotlight_row(team: dict, index: int) -> str:
    """Build an HTML table row for the state spotlight."""
    bg = "#ffffff" if index % 2 == 0 else "#f8f9fa"
    rank = team.get("current_rank", team.get("rank", ""))
    name = team.get("team_name", "")
    club = team.get("club_name", "")
    change = team.get("rank_change", 0)
    change_str = f"+{abs(change)}" if change > 0 else str(change)
    change_color = "#0B5345" if change > 0 else "#c0392b"

    return (
        f'    <tr style="background-color:{bg};">'
        f'<td style="padding:8px 10px;font-size:13px;">#{rank}</td>'
        f'<td style="padding:8px 10px;font-size:13px;font-weight:600;">{name[:28]}</td>'
        f'<td style="padding:8px 10px;font-size:13px;">{club[:25]}</td>'
        f'<td style="padding:8px 10px;font-size:13px;text-align:right;'
        f'font-weight:700;color:{change_color};">{change_str}</td>'
        f"</tr>"
    )


def generate_newsletter_html(data: dict) -> str:
    """Read the template and substitute ranking data."""
    template_path = TEMPLATE_DIR / "newsletter_weekly.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Newsletter template not found: {template_path}")

    template_str = template_path.read_text(encoding="utf-8")
    tmpl = Template(template_str)

    dt = data["date"]
    date_display = f"Week of {dt.strftime('%b %d, %Y')}"

    # Hook text — biggest mover of the week
    top_climber = data["climbers"][0] if data["climbers"] else {}
    hook_text = (
        (
            f"{top_climber.get('team_name', 'A team')} jumped "
            f"{abs(top_climber.get('rank_change', 0))} spots to "
            f"#{top_climber.get('current_rank', '?')} this week."
        )
        if top_climber
        else "New rankings are live. See who moved."
    )

    # Build table rows
    climbers_html = "\n".join(_table_row(t, i, "+") for i, t in enumerate(data["climbers"]))
    fallers_html = "\n".join(_table_row(t, i, "-") for i, t in enumerate(data["fallers"]))
    spotlight_teams_html = "\n".join(_spotlight_row(t, i) for i, t in enumerate(data["spotlight_teams"]))

    total_teams = f"{data['total_teams']:,}" if data["total_teams"] else "25,000+"
    biggest_jump = f"+{data['biggest_jump']}" if data["biggest_jump"] else "--"

    # Rotating engagement hooks
    engagement_hooks = [
        "Know a soccer parent who checks rankings at 11pm? Forward this email.",
        "What do you wish rankings could tell you? Reply and let us know.",
        "Is your team climbing or falling? Check your full trend in Premium.",
        "Tryout season is coming. Compare clubs before you commit.",
    ]
    week_num = data["date"].isocalendar()[1]
    engagement_hook = engagement_hooks[week_num % len(engagement_hooks)]

    html = tmpl.safe_substitute(
        date_display=date_display,
        hook_text=hook_text,
        climbers_html=climbers_html,
        fallers_html=fallers_html,
        spotlight_state=data["spotlight_state"] or "USA",
        spotlight_teams_html=spotlight_teams_html,
        total_teams=total_teams,
        biggest_jump=biggest_jump,
        engagement_hook=engagement_hook,
    )

    log.info(f"Newsletter generated ({len(html):,} bytes)")
    return html


def generate_newsletter_subject(data: dict) -> str:
    """Generate a data-forward subject line."""
    top = data["climbers"][0] if data["climbers"] else None
    dt = data["date"]
    date_str = dt.strftime("%b %d")

    if top:
        name = top.get("team_name", "A team")
        # Truncate long team names for subject line readability
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
    total = f"{data['total_teams']:,}" if data["total_teams"] else "25,000+"
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
        return (
            f"Every Monday, PitchRank updates {keyword} across all leagues.\n"
            f"We track {total} teams nationally, and here's what moved in {state} this week.\n\n"
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
        return (
            f"One of the most common questions in youth soccer: {keyword} — which\n"
            f"league is better? PitchRank's cross-league calibration makes a\n"
            f"data-driven comparison possible across {total} teams.\n\n"
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
        return (
            f"This week, PitchRank ranked {total} youth soccer teams across\n"
            f"all 50 states. Here's how we did it and what the data showed.\n\n"
            f"## This Week by the Numbers\n\n"
            f"- **{total}** teams ranked\n"
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
        return (
            f"Looking for the {keyword}? PitchRank ranks {total} teams across\n"
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
    return (
        f"Every Monday, PitchRank updates youth soccer rankings for {total}\n"
        f"teams across all 50 states. Here are this week's biggest movers.\n\n"
        f"## Biggest Climbers\n\n{climbers_table}\n\n"
        f"## Biggest Drops\n\n{fallers_table}\n\n"
        f"## What Drove the Movement\n\n"
        f"The biggest single jump this week was **+{biggest} spots**{top_attr}.\n"
        f"Rankings factor in strength of schedule, margin of victory, and opponent quality.\n\n"
        f"{faq}\n"
        f"**[See the full rankings →](https://pitchrank.io/rankings)**\n"
    )


def generate_blog_post(data: dict) -> tuple[str, str]:
    """Generate a weekly SEO-targeted blog post from ranking data.

    Reads the topic queue from brand/blog-topics.json and picks the next
    topic based on ISO week number. Returns (filename, markdown_content).
    """
    dt = data["date"]
    week_num = dt.isocalendar()[1]
    date_str = dt.strftime("%Y-%m-%d")
    date_display = dt.strftime("%B %d, %Y")
    total = f"{data['total_teams']:,}" if data["total_teams"] else "25,000+"

    topic = get_next_blog_topic(week_num)
    title = topic.get("title", "Youth Soccer Rankings Update").replace("{total}", total)
    slug = f"{date_str}-{topic.get('slug_prefix', 'weekly-update')}"
    tags = topic.get("tags", ["Rankings"])
    target_keyword = topic.get("target_keyword", "youth soccer rankings")

    # Build body using the topic type's template
    body = _build_blog_body(data, topic)

    # Estimate reading time
    word_count = len(body.split())
    reading_time = f"{max(1, word_count // 200)} min read"

    # Build SEO-optimized excerpt
    state = topic.get("state", "")
    age_group = topic.get("age_group", "")
    if state:
        excerpt = (
            f"This week's {state} youth soccer rankings update."
            f" See which {state} teams moved the most across {total} ranked teams."
        )
    elif age_group:
        excerpt = f"Best {age_group} soccer teams this week. Rankings for {total} teams updated every Monday."
    else:
        excerpt = f"Weekly youth soccer rankings update for {date_display}. {total} teams ranked across all 50 states."

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
            "{team_name} jumped {change} spots to #{rank}.\n\n"
            "Where does your team stand?\n\n"
            "pitchrank.io/rankings\n\n"
            "#YouthSoccer #ClubSoccer #SoccerRankings"
        ),
        (
            "Monday means new rankings.\n\n"
            "Biggest move: {team_name} ({state}) climbed {change} spots.\n\n"
            "25K+ teams updated.\n\n"
            "pitchrank.io/rankings\n\n"
            "#YouthSoccer #SoccerRankings"
        ),
    ],
    "mover_spotlight": [
        (
            "{team_name} ({state}) climbed {change} spots this week.\n\n"
            "Now #{rank} nationally.\n\n"
            "Rankings built from real game data, not vibes.\n\n"
            "pitchrank.io/rankings"
        ),
        (
            "Big move alert: {team_name} is now #{rank} nationally.\n\n"
            "+{change} spots this week.\n\n"
            "Some rankings are vibes. Ours are receipts.\n\n"
            "pitchrank.io/rankings"
        ),
    ],
    "state_spotlight": [
        (
            "Top movers in {state} this week:\n\n"
            "{mover_list}\n\n"
            "Full state rankings at pitchrank.io/rankings\n\n"
            "#{state}Soccer #YouthSoccer"
        ),
    ],
    "data_flex": [
        (
            "{total_teams} teams. Updated every Monday.\n\n"
            "Your team is in there.\n\n"
            "pitchrank.io/rankings\n\n"
            "#YouthSoccer #SoccerRankings #ClubSoccer"
        ),
        (
            "We don't guess. We count.\n\n"
            "Real match results.\n"
            "Strength of schedule.\n"
            "Updated weekly.\n\n"
            "Find your team: pitchrank.io/rankings\n\n"
            "#YouthSoccer #SoccerRankings"
        ),
    ],
}


def generate_social_posts(data: dict) -> list[dict]:
    """Generate social posts scheduled across the week."""
    posts = []
    monday = data["date"].replace(hour=12, minute=0, second=0, microsecond=0)

    # Ensure monday is actually a Monday; adjust if needed
    while monday.weekday() != 0:
        monday += timedelta(days=1)

    wednesday = monday + timedelta(days=2, hours=-4, minutes=30)  # Wed 7:30 AM MT
    thursday = monday + timedelta(days=3, hours=-4, minutes=30)  # Thu 7:30 AM MT

    top_climber = data["climbers"][0] if data["climbers"] else {}
    second_climber = data["climbers"][1] if len(data["climbers"]) > 1 else top_climber

    # Post 1: Monday noon — Rankings announcement
    if top_climber:
        template = random.choice(SOCIAL_TEMPLATES["rankings_live"])
        text = template.format(
            team_name=top_climber.get("team_name", "A team"),
            change=abs(top_climber.get("rank_change", 0)),
            rank=top_climber.get("current_rank", "?"),
            state=top_climber.get("state_code", top_climber.get("state", "")),
        )
        posts.append(
            {
                "text": text,
                "media_url": f"{PITCHRANK_URL}/api/infographic/movers?platform=instagram",
                "scheduled_at": monday,
                "type": "rankings_live",
            }
        )

    # Post 2: Wednesday — Mover spotlight (use second climber to avoid repeat)
    target = second_climber or top_climber
    if target:
        template = random.choice(SOCIAL_TEMPLATES["mover_spotlight"])
        text = template.format(
            team_name=target.get("team_name", "A team"),
            change=abs(target.get("rank_change", 0)),
            rank=target.get("current_rank", "?"),
            state=target.get("state_code", target.get("state", "")),
        )
        posts.append(
            {
                "text": text,
                "media_url": f"{PITCHRANK_URL}/api/infographic/spotlight?platform=twitter",
                "scheduled_at": wednesday,
                "type": "mover_spotlight",
            }
        )

    # Post 3: Thursday — State spotlight or data flex
    if data["spotlight_state"] and data["spotlight_teams"]:
        mover_list = "\n".join(
            f"{i + 1}. {t.get('team_name', '')} (+{abs(t.get('rank_change', 0))})"
            for i, t in enumerate(data["spotlight_teams"][:3])
        )
        template = random.choice(SOCIAL_TEMPLATES["state_spotlight"])
        text = template.format(
            state=data["spotlight_state"],
            mover_list=mover_list,
        )
    else:
        template = random.choice(SOCIAL_TEMPLATES["data_flex"])
        total = f"{data['total_teams']:,}" if data["total_teams"] else "25,000+"
        text = template.format(total_teams=total)

    posts.append(
        {
            "text": text,
            "media_url": (
                f"{PITCHRANK_URL}/api/infographic/state?state={data.get('spotlight_state', 'TX')}&platform=instagram"
            ),
            "scheduled_at": thursday,
            "type": "state_spotlight" if data["spotlight_state"] else "data_flex",
        }
    )

    log.info(f"Generated {len(posts)} social posts")
    return posts


# ---------------------------------------------------------------------------
# Buffer scheduling
# ---------------------------------------------------------------------------


def get_buffer_profiles() -> list[dict]:
    """Get connected Buffer profiles."""
    token = os.getenv("BUFFER_ACCESS_TOKEN")
    if not token:
        log.error("BUFFER_ACCESS_TOKEN not set")
        return []

    resp = requests.get(
        f"{BUFFER_API_URL}/profiles.json",
        params={"access_token": token},
        timeout=30,
    )
    if resp.status_code != 200:
        log.error(f"Buffer profiles error ({resp.status_code}): {resp.text[:300]}")
        return []

    return resp.json()


def schedule_to_buffer(posts: list[dict]) -> list[bool]:
    """Schedule social posts to all connected Buffer profiles."""
    token = os.getenv("BUFFER_ACCESS_TOKEN")
    if not token:
        log.error("BUFFER_ACCESS_TOKEN not set, skipping social posts")
        return [False] * len(posts)

    profiles = get_buffer_profiles()
    if not profiles:
        log.error("No Buffer profiles found")
        return [False] * len(posts)

    profile_ids = [p["id"] for p in profiles]
    profile_names = ", ".join(f"{p.get('service', '?')}:{p.get('formatted_username', '?')}" for p in profiles)
    log.info(f"Buffer profiles: {profile_names}")

    results = []
    for post in posts:
        scheduled_utc = post["scheduled_at"].astimezone(timezone.utc)

        # Buffer API expects repeated profile_ids[] params as form data tuples
        form_data = [
            ("access_token", token),
            ("text", post["text"]),
            ("scheduled_at", scheduled_utc.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ]
        for pid in profile_ids:
            form_data.append(("profile_ids[]", pid))

        if post.get("media_url"):
            form_data.append(("media[photo]", post["media_url"]))

        resp = requests.post(
            f"{BUFFER_API_URL}/updates/create.json",
            data=form_data,
            timeout=30,
        )

        if resp.status_code == 200:
            log.info(f"Scheduled [{post['type']}] for {post['scheduled_at'].strftime('%A %I:%M %p MT')}")
            results.append(True)
        else:
            log.error(f"Buffer error for [{post['type']}] ({resp.status_code}): {resp.text[:300]}")
            results.append(False)

    return results


# ---------------------------------------------------------------------------
# X thread posting
# ---------------------------------------------------------------------------


def get_x_client():
    """Initialize tweepy Client for X API v2. Returns None if not configured."""
    try:
        import tweepy  # noqa: E402 — optional dependency
    except ImportError:
        log.warning("tweepy not installed, skipping X thread")
        return None

    consumer_key = os.getenv("X_CONSUMER_KEY")
    consumer_secret = os.getenv("X_CONSUMER_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
        log.warning("X API credentials not configured, skipping X thread")
        return None

    return tweepy.Client(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )


def generate_thread_tweets(data: dict) -> list[str]:
    """Generate a 4-tweet thread from weekly ranking data."""
    top = data["climbers"][0] if data["climbers"] else {}
    total = f"{data['total_teams']:,}" if data["total_teams"] else "25,000+"
    state = data.get("spotlight_state", "")

    tweets = []

    # Tweet 1: Hook
    if top:
        tweets.append(
            f"{top.get('team_name', 'A team')} jumped "
            f"{abs(top.get('rank_change', 0))} spots to "
            f"#{top.get('current_rank', '?')} this week.\n\n"
            f"Here's what moved in youth soccer rankings this week."
        )
    else:
        tweets.append("New youth soccer rankings are live. Here are the biggest movers.")

    # Tweet 2: Top climbers list (truncate names to fit 280 char limit)
    climber_lines = "\n".join(
        f"{i + 1}. {t.get('team_name', '')[:30]} (+{abs(t.get('rank_change', 0))})"
        for i, t in enumerate(data["climbers"][:3])
    )
    if climber_lines:
        tweets.append(f"Biggest climbers this week:\n\n{climber_lines}")

    # Tweet 3: State spotlight
    if state and data.get("spotlight_teams"):
        spotlight_list = ", ".join(t.get("team_name", "")[:25] for t in data["spotlight_teams"][:3])
        tweets.append(f"State to watch: {state}\n\nTop movers: {spotlight_list}")

    # Tweet 4: CTA
    tweets.append(f"{total} teams ranked every Monday.\n\npitchrank.io/rankings")

    log.info(f"Generated {len(tweets)}-tweet thread")
    return tweets


def post_thread_to_x(tweets: list[str], dry_run: bool = False) -> bool:
    """Post a thread to X by chaining tweets with in_reply_to_tweet_id."""
    if dry_run:
        for i, tweet in enumerate(tweets):
            log.info(f"[DRY RUN] Thread tweet {i + 1}/{len(tweets)}: {tweet}")
        return True

    client = get_x_client()
    if not client:
        return False

    previous_tweet_id = None
    for i, tweet_text in enumerate(tweets):
        try:
            response = client.create_tweet(
                text=tweet_text,
                in_reply_to_tweet_id=previous_tweet_id,
            )
            previous_tweet_id = response.data["id"]
            log.info(f"Posted thread tweet {i + 1}/{len(tweets)} (id={previous_tweet_id})")
        except Exception as e:
            log.error(f"Failed to post thread tweet {i + 1}: {e}")
            return False

    return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def save_artifacts(newsletter_html: str, social_posts: list[dict], data: dict):
    """Save generated content as artifacts for debugging."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    date_str = data["date"].strftime("%Y%m%d")

    html_path = ARTIFACTS_DIR / f"newsletter_{date_str}.html"
    html_path.write_text(newsletter_html, encoding="utf-8")
    log.info(f"Saved newsletter HTML: {html_path}")

    posts_path = ARTIFACTS_DIR / f"social_posts_{date_str}.json"
    serializable = []
    for p in social_posts:
        serializable.append(
            {
                "type": p["type"],
                "text": p["text"],
                "media_url": p.get("media_url"),
                "scheduled_at": p["scheduled_at"].isoformat(),
            }
        )
    posts_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
    log.info(f"Saved social posts JSON: {posts_path}")


def main():
    parser = argparse.ArgumentParser(description="PitchRank Marketing Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Generate content without publishing")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("PitchRank Marketing Pipeline")
    log.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    log.info("=" * 60)

    # Step 1: Fetch data
    try:
        supabase = get_supabase_client()
        data = fetch_ranking_highlights(supabase)
    except Exception as e:
        log.error(f"Failed to fetch ranking data: {e}")
        sys.exit(1)

    if not data["climbers"] and not data["fallers"]:
        log.warning("No movers found — rankings may not have updated yet. Exiting.")
        sys.exit(0)

    # Step 2: Generate newsletter
    newsletter_html = generate_newsletter_html(data)
    subject = generate_newsletter_subject(data)
    log.info(f"Subject: {subject}")

    # Step 3: Generate blog post
    blog_filename, blog_content = "", ""
    try:
        blog_filename, blog_content = generate_blog_post(data)
    except Exception as e:
        log.error(f"Blog generation failed: {e}")

    # Step 4: Generate social posts
    social_posts = generate_social_posts(data)

    # Step 5: Generate X thread
    thread_tweets = []
    try:
        thread_tweets = generate_thread_tweets(data)
    except Exception as e:
        log.error(f"Thread generation failed: {e}")

    # Save artifacts (always, for debugging)
    save_artifacts(newsletter_html, social_posts, data)

    if args.dry_run:
        log.info("")
        log.info("--- DRY RUN OUTPUT ---")
        log.info(f"Newsletter subject: {subject}")
        log.info(f"Newsletter length: {len(newsletter_html):,} bytes")
        log.info("")
        if blog_filename:
            log.info(f"Blog post: {blog_filename} ({len(blog_content):,} bytes)")
        log.info("")
        for post in social_posts:
            log.info(f"[{post['type']}] {post['scheduled_at'].strftime('%A %I:%M %p MT')}")
            if post.get("media_url"):
                log.info(f"  Image: {post['media_url']}")
            log.info(post["text"])
            log.info("")
        if thread_tweets:
            log.info("--- X THREAD ---")
            for i, tweet in enumerate(thread_tweets):
                log.info(f"Tweet {i + 1}/{len(thread_tweets)}: {tweet}")
                log.info("")
        log.info("Artifacts saved. No API calls made.")
        return

    # Step 6: Publish newsletter to Beehiiv
    newsletter_ok = False
    try:
        newsletter_ok = publish_to_beehiiv(newsletter_html, subject)
    except Exception as e:
        log.error(f"Newsletter publishing failed: {e}")

    # Step 7: Publish blog post (commit + push)
    blog_ok = False
    try:
        if blog_filename and blog_content:
            blog_ok = commit_and_push_blog_post(blog_filename, blog_content)
    except Exception as e:
        log.error(f"Blog publishing failed: {e}")

    # Step 8: Schedule social posts to Buffer
    buffer_results = []
    try:
        buffer_results = schedule_to_buffer(social_posts)
    except Exception as e:
        log.error(f"Social scheduling failed: {e}")

    # Step 9: Post X thread
    thread_ok = False
    try:
        if thread_tweets:
            thread_ok = post_thread_to_x(thread_tweets)
    except Exception as e:
        log.error(f"X thread posting failed: {e}")

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("PIPELINE COMPLETE")
    log.info(f"  Newsletter: {'SENT' if newsletter_ok else 'FAILED'}")
    log.info(f"  Blog: {'PUBLISHED' if blog_ok else 'SKIPPED'}")
    log.info(f"  Social: {sum(buffer_results)}/{len(buffer_results)} posts scheduled")
    log.info(f"  X Thread: {'POSTED' if thread_ok else 'SKIPPED'}")
    log.info("=" * 60)

    # Exit 0 even with partial failures — the workflow should show as success
    # with logged warnings, not block the next run
    if not newsletter_ok and not any(buffer_results):
        sys.exit(1)


if __name__ == "__main__":
    main()
