#!/usr/bin/env python3
"""
PitchRank Pipeline Process Map Generator
Generates a comprehensive visual diagram of the entire PitchRank data pipeline.
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np


def draw_rounded_box(ax, x, y, w, h, text, color, text_color='white',
                     fontsize=8, alpha=0.95, bold=False, border_color=None,
                     linewidth=1.5, text_lines=None):
    """Draw a rounded rectangle with centered text."""
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.015",
        facecolor=color,
        edgecolor=border_color or color,
        linewidth=linewidth,
        alpha=alpha,
        zorder=2
    )
    ax.add_patch(box)
    weight = 'bold' if bold else 'normal'

    if text_lines:
        line_height = fontsize * 0.0018
        total_height = len(text_lines) * line_height
        start_y = y + h / 2 + total_height / 2 - line_height / 2
        for i, line in enumerate(text_lines):
            fs = fontsize
            w_line = 'bold' if i == 0 else 'normal'
            if i > 0:
                fs = fontsize - 1
            ax.text(x + w / 2, start_y - i * line_height, line,
                    ha='center', va='center', fontsize=fs,
                    color=text_color, fontweight=w_line, zorder=3,
                    clip_on=False)
    else:
        ax.text(x + w / 2, y + h / 2, text,
                ha='center', va='center', fontsize=fontsize,
                color=text_color, fontweight=weight, zorder=3,
                wrap=True, clip_on=False)
    return box


def draw_arrow(ax, x1, y1, x2, y2, color='#555555', style='->', lw=1.5,
               connectionstyle="arc3,rad=0.0"):
    """Draw an arrow between two points."""
    arrow = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle=style,
        color=color,
        linewidth=lw,
        connectionstyle=connectionstyle,
        zorder=1,
        mutation_scale=12
    )
    ax.add_patch(arrow)
    return arrow


def draw_section_bg(ax, x, y, w, h, color, label, label_color='#333333'):
    """Draw a section background with label."""
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.01",
        facecolor=color,
        edgecolor='#cccccc',
        linewidth=1,
        alpha=0.3,
        zorder=0
    )
    ax.add_patch(rect)
    ax.text(x + 0.012, y + h - 0.012, label,
            ha='left', va='top', fontsize=9,
            color=label_color, fontweight='bold', zorder=1,
            style='italic')


def generate_pipeline_map():
    """Generate the full PitchRank pipeline process map."""
    fig, ax = plt.subplots(1, 1, figsize=(28, 38))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor('#FAFBFC')

    # ──────────────────────────────────────────
    # COLOR PALETTE
    # ──────────────────────────────────────────
    C_HEADER = '#1a1a2e'
    C_TRIGGER = '#e94560'
    C_SCRAPE = '#0f3460'
    C_ETL = '#16213e'
    C_VALIDATE = '#e76f51'
    C_MATCH = '#2a9d8f'
    C_RANK = '#6a0572'
    C_ML = '#e63946'
    C_DB = '#264653'
    C_FRONTEND = '#457b9d'
    C_WORKFLOW = '#f4a261'
    C_DATA = '#606c38'
    C_SUBBOX = '#333333'

    # ──────────────────────────────────────────
    # TITLE
    # ──────────────────────────────────────────
    ax.text(0.5, 0.985, 'PitchRank — Complete Pipeline Process Map',
            ha='center', va='top', fontsize=20, fontweight='bold',
            color=C_HEADER, zorder=10)
    ax.text(0.5, 0.975, 'v2.0.4-config-sync  |  Youth Soccer Team Ranking System  |  Data Collection → Rankings → Frontend',
            ha='center', va='top', fontsize=10, color='#666666', zorder=10)

    # ══════════════════════════════════════════
    # PHASE 1: SCHEDULING & TRIGGERS
    # ══════════════════════════════════════════
    phase1_y = 0.935
    draw_section_bg(ax, 0.02, phase1_y - 0.055, 0.96, 0.06, '#fff3e0',
                    'PHASE 1: SCHEDULING & TRIGGERS (GitHub Actions)')

    # Cron triggers
    bw = 0.18
    bh = 0.028
    gap = 0.03

    triggers = [
        ("scrape-games.yml", "Mon 6:00 & 11:15 AM UTC", 0.05),
        ("calculate-rankings.yml", "Mon 4:45 PM UTC", 0.26),
        ("data-hygiene-weekly.yml", "Weekly cleanup", 0.47),
        ("auto-merge-queue.yml", "Auto merge teams", 0.68),
    ]
    for label, sub, xpos in triggers:
        draw_rounded_box(ax, xpos, phase1_y - 0.048, bw, bh, '',
                         C_TRIGGER, fontsize=7, bold=True,
                         text_lines=[label, sub])

    # Arrows from triggers down
    arr_y_top = phase1_y - 0.048
    arr_y_bot = phase1_y - 0.07

    # ══════════════════════════════════════════
    # PHASE 2: DATA COLLECTION (SCRAPING)
    # ══════════════════════════════════════════
    phase2_y = 0.82
    draw_section_bg(ax, 0.02, phase2_y - 0.07, 0.96, 0.10, '#e3f2fd',
                    'PHASE 2: DATA COLLECTION — Multi-Provider Scraping')

    # Arrow from trigger to phase 2
    draw_arrow(ax, 0.14, arr_y_top - bh, 0.14, phase2_y + 0.025, C_TRIGGER)

    # Provider boxes
    pw = 0.135
    ph = 0.05
    providers = [
        ("GotSport API", "src/scrapers/gotsport.py\nSSL/certifi, async\nRate: 1.5-2.5s delay", 0.05),
        ("TGS Events", "src/scrapers/tgs_event.py\nEvent discovery\nHTML parsing", 0.21),
        ("AthleteOne", "src/scrapers/athleteone_scraper.py\nHTML + API client\nWeekly schedule", 0.37),
        ("SincSports", "src/scrapers/sincsports.py\nEvent-based scraping", 0.53),
        ("Modular11", "src/models/modular11_matcher.py\nWeekly scrape workflow", 0.69),
        ("US Club Soccer", "config/settings.py\nProvider: 'usclub'", 0.85),
    ]
    for title, detail, xpos in providers:
        draw_rounded_box(ax, xpos, phase2_y - 0.055, pw, ph, '',
                         C_SCRAPE, fontsize=6.5,
                         text_lines=[title, *detail.split('\n')])

    # Scraping output
    out_y = phase2_y - 0.068
    draw_rounded_box(ax, 0.30, out_y - 0.022, 0.40, 0.02,
                     'Output: JSONL / CSV files  →  data/raw/',
                     C_DATA, fontsize=7, bold=True)

    # Arrow down to ETL
    draw_arrow(ax, 0.50, out_y - 0.022, 0.50, out_y - 0.045, '#333')

    # ══════════════════════════════════════════
    # PHASE 3: ETL PIPELINE — INGESTION & VALIDATION
    # ══════════════════════════════════════════
    phase3_y = 0.685
    draw_section_bg(ax, 0.02, phase3_y - 0.11, 0.96, 0.145, '#e8f5e9',
                    'PHASE 3: ETL PIPELINE — Ingestion, Validation & Deduplication')

    # Entry point
    ew = 0.28
    draw_rounded_box(ax, 0.36, phase3_y + 0.015, ew, 0.022,
                     'Entry: scripts/import_games_enhanced.py → EnhancedETLPipeline',
                     C_ETL, fontsize=7, bold=True)

    # ETL sub-steps (horizontal flow)
    step_w = 0.17
    step_h = 0.07
    steps_y = phase3_y - 0.085

    # Step 1: Stream
    draw_rounded_box(ax, 0.03, steps_y, step_w, step_h, '',
                     C_ETL, fontsize=6.5,
                     text_lines=[
                         '1. STREAM INPUT',
                         'stream_games_csv()',
                         'stream_games_jsonl()',
                         'Batch size: 1000',
                         'Memory-efficient generator'
                     ])

    # Arrow
    draw_arrow(ax, 0.03 + step_w, steps_y + step_h/2,
               0.03 + step_w + 0.015, steps_y + step_h/2, '#333')

    # Step 2: Validate
    draw_rounded_box(ax, 0.215, steps_y, step_w, step_h, '',
                     C_VALIDATE, fontsize=6.5,
                     text_lines=[
                         '2. VALIDATE',
                         'EnhancedDataValidator',
                         'parse_game_date() → 3 formats',
                         'Required: team, opponent,',
                         'date, age_group, gender',
                         'Invalid → quarantine_games'
                     ])

    draw_arrow(ax, 0.215 + step_w, steps_y + step_h/2,
               0.215 + step_w + 0.015, steps_y + step_h/2, '#333')

    # Step 3: Deduplicate
    draw_rounded_box(ax, 0.40, steps_y, step_w, step_h, '',
                     '#7b2cbf', fontsize=6.5,
                     text_lines=[
                         '3. DEDUPLICATE',
                         'Generate game_uid (UUID)',
                         'Deterministic hash of:',
                         '  teams + date + scores',
                         'Perspective dedup (~50%)',
                         'Skip if already in DB'
                     ])

    draw_arrow(ax, 0.40 + step_w, steps_y + step_h/2,
               0.40 + step_w + 0.015, steps_y + step_h/2, '#333')

    # Step 4: Batch Insert
    draw_rounded_box(ax, 0.585, steps_y, step_w, step_h, '',
                     C_DB, fontsize=6.5,
                     text_lines=[
                         '4. BATCH INSERT',
                         'Supabase PostgreSQL',
                         'Batch size: 1000',
                         'game_uid UNIQUE constraint',
                         'ImportMetrics → build_logs',
                         'games table updated'
                     ])

    draw_arrow(ax, 0.585 + step_w, steps_y + step_h/2,
               0.585 + step_w + 0.015, steps_y + step_h/2, '#333')

    # Step 5: Log metrics
    draw_rounded_box(ax, 0.77, steps_y, 0.19, step_h, '',
                     C_WORKFLOW, text_color='#1a1a1a', fontsize=6.5,
                     text_lines=[
                         '5. LOG METRICS',
                         'ImportMetrics.to_dict()',
                         'games_processed/accepted',
                         'duplicates_found/skipped',
                         'teams_matched/created',
                         'fuzzy_auto/manual/rejected',
                         'memory_usage_mb'
                     ])

    # ══════════════════════════════════════════
    # PHASE 4: TEAM MATCHING
    # ══════════════════════════════════════════
    phase4_y = 0.52
    draw_section_bg(ax, 0.02, phase4_y - 0.075, 0.96, 0.115, '#fce4ec',
                    'PHASE 4: TEAM MATCHING — 3-Tier Identity Resolution')

    # Arrow from ETL down
    draw_arrow(ax, 0.50, steps_y, 0.50, phase4_y + 0.032, '#333')

    # Matching tiers
    tw = 0.28
    th = 0.065

    # Tier 1: Direct ID
    draw_rounded_box(ax, 0.04, phase4_y - 0.06, tw, th, '',
                     C_MATCH, fontsize=6.5,
                     text_lines=[
                         'TIER 1: DIRECT ID MATCH',
                         'Confidence: 1.0 (100%)',
                         'team_alias_map.match_method = "direct_id"',
                         'Fastest path, exact provider_team_id',
                     ])

    # Tier 2: Alias Lookup
    draw_rounded_box(ax, 0.36, phase4_y - 0.06, tw, th, '',
                     '#1d7874', fontsize=6.5,
                     text_lines=[
                         'TIER 2: ALIAS LOOKUP',
                         'Confidence: 0.90-1.0',
                         'Pre-approved alias mappings',
                         'match_method = "manual" or "approved"',
                     ])

    # Tier 3: Fuzzy Match
    draw_rounded_box(ax, 0.68, phase4_y - 0.06, tw, th, '',
                     '#e76f51', fontsize=6.5,
                     text_lines=[
                         'TIER 3: FUZZY MATCHING',
                         'GameHistoryMatcher (game_matcher.py)',
                         '65% name + 25% club + 5% age + 5% loc',
                         '>=0.90: auto-approve | 0.75-0.90: review',
                         '<0.75: reject'
                     ])

    # Fuzzy output boxes
    fo_y = phase4_y - 0.075
    small_w = 0.13
    small_h = 0.015

    # Arrows from tiers converge
    draw_arrow(ax, 0.04 + tw/2, phase4_y - 0.06,
               0.50, phase4_y - 0.088, '#555', lw=1)
    draw_arrow(ax, 0.36 + tw/2, phase4_y - 0.06,
               0.50, phase4_y - 0.088, '#555', lw=1)
    draw_arrow(ax, 0.68 + tw/2, phase4_y - 0.06,
               0.50, phase4_y - 0.088, '#555', lw=1)

    # team_alias_map output
    draw_rounded_box(ax, 0.35, phase4_y - 0.098, 0.30, 0.018,
                     'team_alias_map → Maps provider IDs to team_id_master UUIDs',
                     C_DB, fontsize=6.5, bold=True)

    # ══════════════════════════════════════════
    # PHASE 5: RANKING CALCULATION
    # ══════════════════════════════════════════
    phase5_y = 0.385
    draw_section_bg(ax, 0.02, phase5_y - 0.16, 0.96, 0.19, '#f3e5f5',
                    'PHASE 5: RANKING CALCULATION — v53e Algorithm + ML Layer 13')

    # Arrow from team matching down
    draw_arrow(ax, 0.50, phase4_y - 0.098, 0.50, phase5_y + 0.022, '#333')

    # Entry point
    draw_rounded_box(ax, 0.30, phase5_y + 0.005, 0.40, 0.02,
                     'Entry: scripts/calculate_rankings.py → compute_rankings_with_ml()',
                     C_RANK, fontsize=7, bold=True)

    # V53E 10-layer box (left side)
    v53_x = 0.04
    v53_w = 0.44
    v53_h = 0.155
    v53_y = phase5_y - 0.155

    draw_rounded_box(ax, v53_x, v53_y, v53_w, v53_h, '', C_RANK, fontsize=6,
                     text_lines=[
                         'V53E DETERMINISTIC ALGORITHM (src/etl/v53e.py)',
                         '',
                         'Layer 1:  Time Window — 365 days lookback, hide if >180d inactive',
                         'Layer 2:  Game Limits — Max 30 games, goal diff cap ±6, outlier z>2.5',
                         'Layer 3:  Recency Weighting — Recent K=15 @ 65%, dampen tail 0.8→0.4',
                         'Layer 4:  Defense Ridge — Goals Against factor = 0.25',
                         'Layer 5:  Adaptive K — Dynamic K-factor (α=0.5, β=0.6)',
                         'Layer 6:  Performance — Per-game overperformance (decay=0.08, thresh=2.0)',
                         'Layer 7:  Bayesian Shrinkage — Pool toward mean (τ=8.0)',
                         'Layer 8:  Strength of Schedule — 3 iterations, power-SOS (damp=0.7, cap=2)',
                         'Layer 9:  Opponent Adjustment — Fix double-count (baseline=0.5, clip 0.4-1.6)',
                         'Layer 10: Final Blend — OFF=0.25 + DEF=0.25 + SOS=0.50 = power_score',
                     ])

    # ML Layer 13 box (right side)
    ml_x = 0.52
    ml_w = 0.44
    ml_h = 0.155
    ml_y = phase5_y - 0.155

    draw_rounded_box(ax, ml_x, ml_y, ml_w, ml_h, '', C_ML, fontsize=6,
                     text_lines=[
                         'ML LAYER 13 (src/rankings/layer13_predictive_adjustment.py)',
                         '',
                         'Model:   XGBoost (primary) / RandomForest (fallback)',
                         'Input:   Per-game features + v53e base scores',
                         '',
                         'Process:',
                         '  1. Compute per-game ML residuals (actual vs predicted)',
                         '  2. Aggregate residuals with recency decay (λ=0.06)',
                         '  3. Normalize via percentile or z-score method',
                         '  4. Blend into power score (α=0.15)',
                         '  5. Batch update games.ml_overperformance via RPC',
                         '',
                         'Output:  Adjusted power_score per team',
                         '         game_residuals persisted to DB',
                     ])

    # Arrow from v53e and ML to merge point
    merge_y = v53_y - 0.012
    draw_arrow(ax, v53_x + v53_w/2, v53_y, v53_x + v53_w/2, merge_y, C_RANK)
    draw_arrow(ax, ml_x + ml_w/2, ml_y, ml_x + ml_w/2, merge_y, C_ML)

    # Merge box
    draw_rounded_box(ax, 0.30, merge_y - 0.018, 0.40, 0.018,
                     'BLENDED FINAL POWER SCORE  →  National Rank + State Rank per cohort',
                     '#4a0e4e', fontsize=7, bold=True)

    # ══════════════════════════════════════════
    # PHASE 6: STATE & CROSS-AGE RANKINGS
    # ══════════════════════════════════════════
    phase6_y = 0.17
    draw_section_bg(ax, 0.02, phase6_y - 0.035, 0.96, 0.06, '#e0f7fa',
                    'PHASE 6: RANKINGS PERSISTENCE & DERIVATION')

    draw_arrow(ax, 0.50, merge_y - 0.018, 0.50, phase6_y + 0.018, '#333')

    # Persistence targets
    persist_w = 0.20
    persist_h = 0.035
    persist_y = phase6_y - 0.028

    draw_rounded_box(ax, 0.04, persist_y, persist_w, persist_h, '',
                     C_DB, fontsize=6.5,
                     text_lines=[
                         'rankings_full',
                         'Comprehensive metrics',
                         'All v53e + ML fields'
                     ])

    draw_rounded_box(ax, 0.27, persist_y, persist_w, persist_h, '',
                     C_DB, fontsize=6.5,
                     text_lines=[
                         'current_rankings',
                         'Backward compatibility',
                         'National + State ranks'
                     ])

    draw_rounded_box(ax, 0.50, persist_y, persist_w, persist_h, '',
                     C_DB, fontsize=6.5,
                     text_lines=[
                         'State Rankings',
                         'Group by state_code',
                         'Rank within each state'
                     ])

    draw_rounded_box(ax, 0.73, persist_y, persist_w + 0.03, persist_h, '',
                     C_DB, fontsize=6.5,
                     text_lines=[
                         'Cross-Age Global Scores',
                         'U10=0.40 → U18=1.00 anchors',
                         'Enables cross-age SOS'
                     ])

    # ══════════════════════════════════════════
    # PHASE 7: FRONTEND & USER-FACING
    # ══════════════════════════════════════════
    phase7_y = 0.085
    draw_section_bg(ax, 0.02, phase7_y - 0.06, 0.96, 0.085, '#e8eaf6',
                    'PHASE 7: FRONTEND — Next.js 16 + React 19 + Supabase Client')

    draw_arrow(ax, 0.50, persist_y, 0.50, phase7_y + 0.018, '#333')

    # Frontend components
    fw = 0.175
    fh = 0.045
    fy = phase7_y - 0.05

    fe_items = [
        ("Rankings Pages", "/rankings\nBrowse by age/gender/state\nRankingsTable component", 0.04),
        ("Team Detail", "/teams/[teamId]\nGame history, insights\nComparePanel, Predictions", 0.235),
        ("API Routes (30+)", "/api/teams/search\n/api/watchlist, /api/stripe\n/api/mission-control", 0.43),
        ("Embed & Reports", "/embed widgets\n/infographics\nRecentMovers, HomeStats", 0.625),
        ("Mission Control", "/mission-control\nAgent orchestration\nTask management UI", 0.82),
    ]
    for title, detail, xpos in fe_items:
        draw_rounded_box(ax, xpos, fy, fw, fh, '',
                         C_FRONTEND, fontsize=6,
                         text_lines=[title, *detail.split('\n')])

    # ══════════════════════════════════════════
    # DATA QUALITY FEEDBACK LOOPS (right sidebar)
    # ══════════════════════════════════════════
    # Side annotation
    ax.text(0.99, 0.50, 'DATA QUALITY LOOPS',
            ha='right', va='center', fontsize=8, fontweight='bold',
            color='#888', rotation=90, zorder=5)

    # ══════════════════════════════════════════
    # DATABASE SCHEMA BOX (bottom)
    # ══════════════════════════════════════════
    db_y = 0.012
    draw_section_bg(ax, 0.02, db_y, 0.96, 0.03, '#fff8e1',
                    'DATABASE: Supabase PostgreSQL')

    db_tables = [
        'providers', 'teams', 'games', 'team_alias_map',
        'current_rankings', 'rankings_full', 'build_logs',
        'quarantine_games', 'game_corrections', 'user_profiles'
    ]
    table_str = '  |  '.join(db_tables)
    ax.text(0.50, db_y + 0.012, table_str,
            ha='center', va='center', fontsize=6.5, color='#333',
            fontweight='normal', fontfamily='monospace', zorder=5)

    # ══════════════════════════════════════════
    # LEGEND
    # ══════════════════════════════════════════
    legend_items = [
        (C_TRIGGER, 'GitHub Actions / Triggers'),
        (C_SCRAPE, 'Data Providers / Scrapers'),
        (C_ETL, 'ETL Pipeline'),
        (C_VALIDATE, 'Validation'),
        (C_MATCH, 'Team Matching'),
        (C_RANK, 'v53e Algorithm'),
        (C_ML, 'ML Layer 13'),
        (C_DB, 'Database / Storage'),
        (C_FRONTEND, 'Frontend / UI'),
        (C_WORKFLOW, 'Metrics / Logging'),
    ]

    legend_x = 0.03
    legend_y = 0.965
    for i, (color, label) in enumerate(legend_items):
        xi = legend_x + (i % 5) * 0.195
        yi = legend_y - (i // 5) * 0.013
        rect = FancyBboxPatch(
            (xi, yi), 0.012, 0.008,
            boxstyle="round,pad=0.002",
            facecolor=color,
            edgecolor='none',
            alpha=0.9,
            zorder=10
        )
        ax.add_patch(rect)
        ax.text(xi + 0.016, yi + 0.004, label,
                ha='left', va='center', fontsize=6.5,
                color='#333', zorder=10)

    # ══════════════════════════════════════════
    # SAVE
    # ══════════════════════════════════════════
    output_path = '/home/user/PitchRank/docs/pipeline_process_map.png'
    fig.savefig(output_path, dpi=200, bbox_inches='tight',
                facecolor='#FAFBFC', edgecolor='none',
                pad_inches=0.3)
    plt.close(fig)
    print(f"Pipeline process map saved to: {output_path}")
    return output_path


if __name__ == '__main__':
    path = generate_pipeline_map()
    print(f"\nDone! Process map generated at:\n  {path}")
