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
        boxstyle="round,pad=0.012",
        facecolor=color,
        edgecolor=border_color or color,
        linewidth=linewidth,
        alpha=alpha,
        zorder=2
    )
    ax.add_patch(box)
    weight = 'bold' if bold else 'normal'

    if text_lines:
        line_height = fontsize * 0.0013
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
        boxstyle="round,pad=0.008",
        facecolor=color,
        edgecolor='#cccccc',
        linewidth=1,
        alpha=0.3,
        zorder=0
    )
    ax.add_patch(rect)
    ax.text(x + 0.012, y + h - 0.008, label,
            ha='left', va='top', fontsize=8,
            color=label_color, fontweight='bold', zorder=1,
            style='italic')


def generate_pipeline_map():
    """Generate the full PitchRank pipeline process map."""
    # Use a taller figure for more vertical space
    fig, ax = plt.subplots(1, 1, figsize=(30, 48))
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

    # ──────────────────────────────────────────
    # TITLE (top of page)
    # ──────────────────────────────────────────
    ax.text(0.5, 0.99, 'PitchRank — Complete Pipeline Process Map',
            ha='center', va='top', fontsize=22, fontweight='bold',
            color=C_HEADER, zorder=10)
    ax.text(0.5, 0.982, 'v2.0.4-config-sync  |  Youth Soccer Team Ranking System  |  Data Collection \u2192 Rankings \u2192 Frontend',
            ha='center', va='top', fontsize=10, color='#666666', zorder=10)

    # ──────────────────────────────────────────
    # LEGEND (below title, above Phase 1)
    # ──────────────────────────────────────────
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

    legend_y = 0.972
    cols = 5
    col_width = 0.19
    legend_x_start = 0.03
    for i, (color, label) in enumerate(legend_items):
        xi = legend_x_start + (i % cols) * col_width
        yi = legend_y - (i // cols) * 0.011
        rect = FancyBboxPatch(
            (xi, yi), 0.012, 0.007,
            boxstyle="round,pad=0.002",
            facecolor=color,
            edgecolor='none',
            alpha=0.9,
            zorder=10
        )
        ax.add_patch(rect)
        ax.text(xi + 0.016, yi + 0.0035, label,
                ha='left', va='center', fontsize=6.5,
                color='#333', zorder=10)

    # ══════════════════════════════════════════
    # PHASE 1: SCHEDULING & TRIGGERS
    # ══════════════════════════════════════════
    p1_top = 0.945
    p1_h = 0.05
    p1_bot = p1_top - p1_h
    draw_section_bg(ax, 0.02, p1_bot, 0.96, p1_h, '#fff3e0',
                    'PHASE 1: SCHEDULING & TRIGGERS (GitHub Actions)')

    bw = 0.18
    bh = 0.025
    box_y = p1_bot + 0.008

    triggers = [
        ("scrape-games.yml", "Mon 6:00 & 11:15 AM UTC", 0.05),
        ("calculate-rankings.yml", "Mon 4:45 PM UTC", 0.26),
        ("data-hygiene-weekly.yml", "Weekly cleanup", 0.47),
        ("auto-merge-queue.yml", "Auto merge teams", 0.68),
    ]
    for label, sub, xpos in triggers:
        draw_rounded_box(ax, xpos, box_y, bw, bh, '',
                         C_TRIGGER, fontsize=7, bold=True,
                         text_lines=[label, sub])

    # Arrow from Phase 1 down to Phase 2
    draw_arrow(ax, 0.14, box_y, 0.14, p1_bot - 0.008, C_TRIGGER)

    # ══════════════════════════════════════════
    # PHASE 2: DATA COLLECTION (SCRAPING)
    # ══════════════════════════════════════════
    p2_top = 0.88
    p2_h = 0.09
    p2_bot = p2_top - p2_h
    draw_section_bg(ax, 0.02, p2_bot, 0.96, p2_h, '#e3f2fd',
                    'PHASE 2: DATA COLLECTION \u2014 Multi-Provider Scraping')

    pw = 0.13
    ph = 0.045
    prov_y = p2_top - 0.018 - ph

    providers = [
        ("GotSport API", "src/scrapers/gotsport.py\nSSL/certifi, async\nRate: 1.5-2.5s delay", 0.04),
        ("TGS Events", "src/scrapers/tgs_event.py\nEvent discovery\nHTML parsing", 0.19),
        ("AthleteOne", "src/scrapers/athleteone_scraper.py\nHTML + API client\nWeekly schedule", 0.34),
        ("SincSports", "src/scrapers/sincsports.py\nEvent-based scraping", 0.49),
        ("Modular11", "src/models/modular11_matcher.py\nWeekly scrape workflow", 0.64),
        ("US Club Soccer", "config/settings.py\nProvider: 'usclub'", 0.82),
    ]
    for title, detail, xpos in providers:
        draw_rounded_box(ax, xpos, prov_y, pw, ph, '',
                         C_SCRAPE, fontsize=6,
                         text_lines=[title, *detail.split('\n')])

    # Output bar below providers
    out_y = prov_y - 0.022
    draw_rounded_box(ax, 0.30, out_y, 0.40, 0.016,
                     'Output: JSONL / CSV files  \u2192  data/raw/',
                     C_DATA, fontsize=7, bold=True)

    # Arrow down to Phase 3
    draw_arrow(ax, 0.50, out_y, 0.50, p2_bot - 0.008, '#333')

    # ══════════════════════════════════════════
    # PHASE 3: ETL PIPELINE
    # ══════════════════════════════════════════
    p3_top = 0.775
    p3_h = 0.12
    p3_bot = p3_top - p3_h
    draw_section_bg(ax, 0.02, p3_bot, 0.96, p3_h, '#e8f5e9',
                    'PHASE 3: ETL PIPELINE \u2014 Ingestion, Validation & Deduplication')

    # Entry point
    entry_y = p3_top - 0.020
    draw_rounded_box(ax, 0.30, entry_y, 0.40, 0.016,
                     'Entry: scripts/import_games_enhanced.py \u2192 EnhancedETLPipeline',
                     C_ETL, fontsize=7, bold=True)

    # ETL sub-steps (horizontal flow)
    step_w = 0.155
    step_h = 0.06
    steps_y = entry_y - 0.068

    # Step 1: Stream
    draw_rounded_box(ax, 0.03, steps_y, step_w, step_h, '',
                     C_ETL, fontsize=6,
                     text_lines=[
                         '1. STREAM INPUT',
                         'stream_games_csv()',
                         'stream_games_jsonl()',
                         'Batch size: 1000',
                         'Memory-efficient generator'
                     ])
    draw_arrow(ax, 0.03 + step_w + 0.002, steps_y + step_h/2,
               0.205 - 0.002, steps_y + step_h/2, '#333')

    # Step 2: Validate
    draw_rounded_box(ax, 0.205, steps_y, step_w, step_h, '',
                     C_VALIDATE, fontsize=6,
                     text_lines=[
                         '2. VALIDATE',
                         'EnhancedDataValidator',
                         'parse_game_date() \u2192 3 fmt',
                         'Required: team, opp,',
                         'date, age_group, gender',
                         'Invalid \u2192 quarantine'
                     ])
    draw_arrow(ax, 0.205 + step_w + 0.002, steps_y + step_h/2,
               0.38 - 0.002, steps_y + step_h/2, '#333')

    # Step 3: Deduplicate
    draw_rounded_box(ax, 0.38, steps_y, step_w, step_h, '',
                     '#7b2cbf', fontsize=6,
                     text_lines=[
                         '3. DEDUPLICATE',
                         'Generate game_uid (UUID)',
                         'Deterministic hash:',
                         '  teams + date + scores',
                         'Perspective dedup (~50%)',
                         'Skip if already in DB'
                     ])
    draw_arrow(ax, 0.38 + step_w + 0.002, steps_y + step_h/2,
               0.555 - 0.002, steps_y + step_h/2, '#333')

    # Step 4: Batch Insert
    draw_rounded_box(ax, 0.555, steps_y, step_w, step_h, '',
                     C_DB, fontsize=6,
                     text_lines=[
                         '4. BATCH INSERT',
                         'Supabase PostgreSQL',
                         'Batch size: 1000',
                         'game_uid UNIQUE const.',
                         'ImportMetrics \u2192 build_logs',
                         'games table updated'
                     ])
    draw_arrow(ax, 0.555 + step_w + 0.002, steps_y + step_h/2,
               0.73 - 0.002, steps_y + step_h/2, '#333')

    # Step 5: Log metrics
    draw_rounded_box(ax, 0.73, steps_y, 0.235, step_h, '',
                     C_WORKFLOW, text_color='#1a1a1a', fontsize=6,
                     text_lines=[
                         '5. LOG METRICS',
                         'ImportMetrics.to_dict()',
                         'games_processed/accepted',
                         'duplicates_found/skipped',
                         'teams_matched/created',
                         'fuzzy_auto/manual/rejected'
                     ])

    # Arrow down to Phase 4
    draw_arrow(ax, 0.50, steps_y, 0.50, p3_bot - 0.008, '#333')

    # ══════════════════════════════════════════
    # PHASE 4: TEAM MATCHING
    # ══════════════════════════════════════════
    p4_top = 0.635
    p4_h = 0.10
    p4_bot = p4_top - p4_h
    draw_section_bg(ax, 0.02, p4_bot, 0.96, p4_h, '#fce4ec',
                    'PHASE 4: TEAM MATCHING \u2014 3-Tier Identity Resolution')

    tw = 0.27
    th = 0.055
    tier_y = p4_top - 0.02 - th

    # Tier 1: Direct ID
    draw_rounded_box(ax, 0.04, tier_y, tw, th, '',
                     C_MATCH, fontsize=6,
                     text_lines=[
                         'TIER 1: DIRECT ID MATCH',
                         'Confidence: 1.0 (100%)',
                         'team_alias_map.match_method = "direct_id"',
                         'Fastest path, exact provider_team_id',
                     ])

    # Tier 2: Alias Lookup
    draw_rounded_box(ax, 0.36, tier_y, tw, th, '',
                     '#1d7874', fontsize=6,
                     text_lines=[
                         'TIER 2: ALIAS LOOKUP',
                         'Confidence: 0.90-1.0',
                         'Pre-approved alias mappings',
                         'match_method = "manual" or "approved"',
                     ])

    # Tier 3: Fuzzy Match
    draw_rounded_box(ax, 0.68, tier_y, tw, th, '',
                     '#e76f51', fontsize=6,
                     text_lines=[
                         'TIER 3: FUZZY MATCHING',
                         'GameHistoryMatcher (game_matcher.py)',
                         '65% name + 25% club + 5% age + 5% loc',
                         '>=0.90: auto | 0.75-0.90: review | <0.75: reject'
                     ])

    # Arrows from tiers converge down
    converge_y = tier_y - 0.012
    draw_arrow(ax, 0.04 + tw/2, tier_y, 0.50, converge_y, '#555', lw=1)
    draw_arrow(ax, 0.36 + tw/2, tier_y, 0.50, converge_y, '#555', lw=1)
    draw_arrow(ax, 0.68 + tw/2, tier_y, 0.50, converge_y, '#555', lw=1)

    # team_alias_map output
    alias_y = converge_y - 0.016
    draw_rounded_box(ax, 0.30, alias_y, 0.40, 0.016,
                     'team_alias_map \u2192 Maps provider IDs to team_id_master UUIDs',
                     C_DB, fontsize=6.5, bold=True)

    # Arrow down to Phase 5
    draw_arrow(ax, 0.50, alias_y, 0.50, p4_bot - 0.008, '#333')

    # ══════════════════════════════════════════
    # PHASE 5: RANKING CALCULATION
    # ══════════════════════════════════════════
    p5_top = 0.51
    p5_h = 0.18
    p5_bot = p5_top - p5_h
    draw_section_bg(ax, 0.02, p5_bot, 0.96, p5_h, '#f3e5f5',
                    'PHASE 5: RANKING CALCULATION \u2014 v53e Algorithm + ML Layer 13')

    # Entry point
    entry5_y = p5_top - 0.020
    draw_rounded_box(ax, 0.25, entry5_y, 0.50, 0.016,
                     'Entry: scripts/calculate_rankings.py \u2192 compute_rankings_with_ml()',
                     C_RANK, fontsize=7, bold=True)

    # V53E box (left side)
    algo_h = 0.12
    algo_y = entry5_y - 0.008 - algo_h

    draw_rounded_box(ax, 0.03, algo_y, 0.45, algo_h, '', C_RANK, fontsize=5.5,
                     text_lines=[
                         'V53E DETERMINISTIC ALGORITHM (src/etl/v53e.py)',
                         '',
                         'Layer 1:  Time Window \u2014 365 days lookback, hide if >180d inactive',
                         'Layer 2:  Game Limits \u2014 Max 30 games, goal diff cap \u00b16, outlier z>2.5',
                         'Layer 3:  Recency Weighting \u2014 Recent K=15 @ 65%, dampen tail 0.8\u21920.4',
                         'Layer 4:  Defense Ridge \u2014 Goals Against factor = 0.25',
                         'Layer 5:  Adaptive K \u2014 Dynamic K-factor (\u03b1=0.5, \u03b2=0.6)',
                         'Layer 6:  Performance \u2014 Per-game overperformance (decay=0.08)',
                         'Layer 7:  Bayesian Shrinkage \u2014 Pool toward mean (\u03c4=8.0)',
                         'Layer 8:  Strength of Schedule \u2014 3 iters, power-SOS (damp=0.7)',
                         'Layer 9:  Opponent Adjustment \u2014 Fix double-count (clip 0.4-1.6)',
                         'Layer 10: Final Blend \u2014 OFF 0.25 + DEF 0.25 + SOS 0.50',
                     ])

    # ML Layer 13 box (right side)
    draw_rounded_box(ax, 0.52, algo_y, 0.45, algo_h, '', C_ML, fontsize=5.5,
                     text_lines=[
                         'ML LAYER 13 (src/rankings/layer13_predictive_adjustment.py)',
                         '',
                         'Model:   XGBoost (primary) / RandomForest (fallback)',
                         'Input:   Per-game features + v53e base scores',
                         '',
                         'Process:',
                         '  1. Compute per-game ML residuals (actual vs predicted)',
                         '  2. Aggregate residuals with recency decay (\u03bb=0.06)',
                         '  3. Normalize via percentile or z-score method',
                         '  4. Blend into power score (\u03b1=0.15)',
                         '  5. Batch update games.ml_overperformance via RPC',
                         '',
                         'Output:  Adjusted power_score per team',
                     ])

    # Arrows from V53E and ML to merge point
    merge_y = algo_y - 0.012
    draw_arrow(ax, 0.03 + 0.45/2, algo_y, 0.03 + 0.45/2, merge_y, C_RANK)
    draw_arrow(ax, 0.52 + 0.45/2, algo_y, 0.52 + 0.45/2, merge_y, C_ML)

    # Merge box
    draw_rounded_box(ax, 0.25, merge_y - 0.016, 0.50, 0.016,
                     'BLENDED FINAL POWER SCORE  \u2192  National Rank + State Rank per cohort',
                     '#4a0e4e', fontsize=7, bold=True)

    # Arrow down to Phase 6
    draw_arrow(ax, 0.50, merge_y - 0.016, 0.50, p5_bot - 0.008, '#333')

    # ══════════════════════════════════════════
    # PHASE 6: RANKINGS PERSISTENCE
    # ══════════════════════════════════════════
    p6_top = 0.30
    p6_h = 0.06
    p6_bot = p6_top - p6_h
    draw_section_bg(ax, 0.02, p6_bot, 0.96, p6_h, '#e0f7fa',
                    'PHASE 6: RANKINGS PERSISTENCE & DERIVATION')

    persist_w = 0.19
    persist_h = 0.032
    persist_y = p6_top - 0.02 - persist_h

    draw_rounded_box(ax, 0.04, persist_y, persist_w, persist_h, '',
                     C_DB, fontsize=6,
                     text_lines=[
                         'rankings_full',
                         'Comprehensive metrics',
                         'All v53e + ML fields'
                     ])

    draw_rounded_box(ax, 0.26, persist_y, persist_w, persist_h, '',
                     C_DB, fontsize=6,
                     text_lines=[
                         'current_rankings',
                         'Backward compatibility',
                         'National + State ranks'
                     ])

    draw_rounded_box(ax, 0.48, persist_y, persist_w, persist_h, '',
                     C_DB, fontsize=6,
                     text_lines=[
                         'State Rankings',
                         'Group by state_code',
                         'Rank within each state'
                     ])

    draw_rounded_box(ax, 0.70, persist_y, 0.26, persist_h, '',
                     C_DB, fontsize=6,
                     text_lines=[
                         'Cross-Age Global Scores',
                         'U10=0.40 \u2192 U18=1.00 anchors',
                         'Enables cross-age SOS'
                     ])

    # Arrow down to Phase 7
    draw_arrow(ax, 0.50, persist_y, 0.50, p6_bot - 0.008, '#333')

    # ══════════════════════════════════════════
    # PHASE 7: FRONTEND & USER-FACING
    # ══════════════════════════════════════════
    p7_top = 0.215
    p7_h = 0.08
    p7_bot = p7_top - p7_h
    draw_section_bg(ax, 0.02, p7_bot, 0.96, p7_h, '#e8eaf6',
                    'PHASE 7: FRONTEND \u2014 Next.js 16 + React 19 + Supabase Client')

    fw = 0.165
    fh = 0.045
    fy = p7_top - 0.02 - fh

    fe_items = [
        ("Rankings Pages", "/rankings\nBrowse by age/gender/state\nRankingsTable component", 0.04),
        ("Team Detail", "/teams/[teamId]\nGame history, insights\nComparePanel, Predictions", 0.22),
        ("API Routes (30+)", "/api/teams/search\n/api/watchlist, /api/stripe\n/api/mission-control", 0.40),
        ("Embed & Reports", "/embed widgets\n/infographics\nRecentMovers, HomeStats", 0.58),
        ("Mission Control", "/mission-control\nAgent orchestration\nTask management UI", 0.78),
    ]
    for title, detail, xpos in fe_items:
        draw_rounded_box(ax, xpos, fy, fw, fh, '',
                         C_FRONTEND, fontsize=5.5,
                         text_lines=[title, *detail.split('\n')])

    # Arrow down to DB
    draw_arrow(ax, 0.50, fy, 0.50, p7_bot - 0.008, '#333')

    # ══════════════════════════════════════════
    # DATABASE SCHEMA (bottom)
    # ══════════════════════════════════════════
    db_top = 0.115
    db_h = 0.03
    db_bot = db_top - db_h
    draw_section_bg(ax, 0.02, db_bot, 0.96, db_h, '#fff8e1',
                    'DATABASE: Supabase PostgreSQL')

    db_tables = [
        'providers', 'teams', 'games', 'team_alias_map',
        'current_rankings', 'rankings_full', 'build_logs',
        'quarantine_games', 'game_corrections', 'user_profiles'
    ]
    table_str = '  |  '.join(db_tables)
    ax.text(0.50, db_bot + db_h / 2 - 0.002, table_str,
            ha='center', va='center', fontsize=6.5, color='#333',
            fontweight='normal', fontfamily='monospace', zorder=5)

    # ══════════════════════════════════════════
    # DATA QUALITY LOOPS (right sidebar annotation)
    # ══════════════════════════════════════════
    ax.text(0.99, 0.50, 'DATA QUALITY LOOPS',
            ha='right', va='center', fontsize=8, fontweight='bold',
            color='#aaa', rotation=90, zorder=5)

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
