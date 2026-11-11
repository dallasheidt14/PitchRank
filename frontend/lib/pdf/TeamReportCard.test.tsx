// @vitest-environment node
import React from 'react';
import { describe, it, expect } from 'vitest';
import { renderToBuffer } from '@react-pdf/renderer';
import { TeamReportCard, type ReportCardProps } from './TeamReportCard';

const TEAM_ID = 'eddb44d8-310e-4863-901c-513ba477ff8b';

const baseProps = (): ReportCardProps => ({
  team: {
    team_id_master: TEAM_ID,
    team_name: 'SCSA Eleven U13B Red',
    club_name: 'South Central Soccer Academy Eleven',
    state: 'IN',
    age: 13,
    gender: 'M',
  },
  ranking: {
    power_score_final: 0.484738,
    rank_in_cohort_final: 20,
    rank_in_state_final: 1,
    offense_norm: null,
    defense_norm: null,
    sos_norm: 0,
    rank_change_7d: null,
    rank_change_30d: 293,
    rank_change_state_7d: null,
    rank_change_state_30d: null,
    perf_centered: null,
    wins: 25,
    losses: 4,
    draws: 1,
    games_played: 30,
    total_wins: 60,
    total_losses: 20,
    total_draws: 5,
    total_games_played: 85,
    win_percentage: null,
  },
  games: [
    { game_date: 'Oct 24', opponent_name: 'Boilers FC 2012/13 Boys Gold', score: '0-1', result: 'L' },
    { game_date: 'Sep 27', opponent_name: 'FWSC U13B Frankfurt', score: '6-0', result: 'W' },
  ],
  nextGame: null,
  cohortTotal: 5578,
  stateCohortTotal: 82,
  rankingsAsOf: 'November 10, 2026',
  generatedDate: 'November 11, 2026',
  gamesLabel: '1.1M+',
});

type Node = { type: unknown; props: Record<string, unknown> } | string | number | null | undefined | boolean | Node[];

type Drawn = { points: string; fill: string };

/**
 * The document's text, concatenated, every link target, and every drawn polygon, read by expanding
 * each component in turn.
 */
function readDocument(props: ReportCardProps): { text: string; links: string[]; shapes: Drawn[] } {
  const links: string[] = [];
  const shapes: Drawn[] = [];
  const walk = (node: Node): string => {
    if (node == null || typeof node === 'boolean') return '';
    if (typeof node === 'string' || typeof node === 'number') return String(node);
    if (Array.isArray(node)) return node.map(walk).join('');
    if (typeof node.type === 'function') return walk((node.type as (p: unknown) => Node)(node.props));
    if (typeof node.props.src === 'string') links.push(node.props.src);
    if (typeof node.props.points === 'string')
      shapes.push({ points: node.props.points, fill: String(node.props.fill) });
    return walk(node.props.children as Node);
  };
  const text = walk(TeamReportCard(props) as Node);
  return { text, links, shapes };
}

const UP_ARROW = { points: '5,0 10,9 0,9', fill: '#10B981' };
const DOWN_ARROW = { points: '0,1 10,1 5,10', fill: '#EF4444' };

async function pageCount(props: ReportCardProps): Promise<number> {
  const pdf = await renderToBuffer(React.createElement(TeamReportCard, props) as Parameters<typeof renderToBuffer>[0]);
  return (pdf.toString('latin1').match(/\/Type\s*\/Page[^s]/g) ?? []).length;
}

describe('TeamReportCard', () => {
  it('shows the headline numbers on the site scale and the right way round', () => {
    const { text } = readDocument(baseProps());

    expect(text).toContain('#20');
    expect(text).toContain('of 5,578 U13 Boys teams · Top 1%');
    expect(text).toContain('48.47');
    expect(text).toContain('Up 293 spots in the last 30 days');
    expect(text).toContain('25-4-1');
    expect(text).toContain('Last 30 ranked games · 85% win rate');
    expect(text).toContain('Rankings as of November 10, 2026 · Report created November 11, 2026');
    expect(text).toContain('PitchRank · 1.1M+ games analyzed · Rankings update every week');
  });

  it('leaves the totals out when they could not be counted', () => {
    const props = baseProps();
    props.cohortTotal = null;
    props.stateCohortTotal = null;

    const { text } = readDocument(props);

    expect(text).toContain('#20U13 Boys teams nationally');
    expect(text).toContain('INDIANA RANK#1U13 Boys teams in Indiana');
    expect(text).not.toContain('Top ');
  });

  it('draws a green up arrow for a climb', () => {
    expect(readDocument(baseProps()).shapes).toEqual([UP_ARROW]);
  });

  it('shows a drop in words beside a red down arrow', () => {
    const props = baseProps();
    props.ranking.rank_change_30d = -4;

    const { text, shapes } = readDocument(props);

    expect(text).toContain('Down 4 spots in the last 30 days');
    expect(shapes).toEqual([DOWN_ARROW]);
  });

  it('draws no arrow when the rank did not move', () => {
    const props = baseProps();
    props.ranking.rank_change_30d = 0;

    expect(readDocument(props).shapes).toEqual([]);
  });

  it('shows the state rank under the state name', () => {
    const { text } = readDocument(baseProps());

    expect(text).toContain('INDIANA RANK#1of 82 U13 Boys teams in Indiana');
  });

  it('shows a state rank outside the 50 boards under its code, and links the national board', () => {
    const props = baseProps();
    props.team.state = 'DC';

    const { text, links } = readDocument(props);

    expect(text).toContain('DC RANK#1of 82 U13 Boys teams in DC');
    expect(links).toContain('https://www.pitchrank.io/rankings/national/u13/male');
  });

  it('leaves the state box out for a team with no state, though the fallback RPC still ranks it', () => {
    const props = baseProps();
    props.team.state = null;

    const { text } = readDocument(props);

    expect(text).not.toContain(' RANK#1');
    expect(text).not.toContain('teams in');
  });

  it('leaves the state box out when there is no state rank', () => {
    const props = baseProps();
    props.ranking.rank_in_state_final = null;

    expect(readDocument(props).text).not.toContain('INDIANA RANK');
  });

  it('lists each game with its opponent and score', () => {
    const { text } = readDocument(baseProps());

    expect(text).toContain('Oct 24Boilers FC 2012/13 Boys Gold0-1L');
    expect(text).toContain('Sep 27FWSC U13B Frankfurt6-0W');
  });

  it('names the next opponent when there is one', () => {
    const props = baseProps();
    props.nextGame = { game_date: 'Nov 20', opponent_name: 'FWSC Frankfurt' };

    const { text } = readDocument(props);

    expect(text).toContain('NEXT UP: VS FWSC FRANKFURT · NOV 20');
    expect(text).toContain('How does SCSA Eleven U13B Red match up?');
  });

  it('falls back to any opponent when no game is coming up', () => {
    expect(readDocument(baseProps()).text).toContain('See how SCSA Eleven U13B Red stacks up against any opponent');
  });

  it('says "your team" in the headline when the name is long', () => {
    const props = baseProps();
    props.team.team_name = 'Southern Indiana United Futbol Club Academy 2014 Boys Red Elite';

    expect(readDocument(props).text).toContain('See how your team stacks up against any opponent');
  });

  it('carries the team to the upgrade page and links the state board and a fresh report', () => {
    const { links } = readDocument(baseProps());

    expect(links).toEqual([
      `https://www.pitchrank.io/upgrade?next=/teams/${TEAM_ID}&utm_source=report-card&utm_medium=pdf&utm_campaign=free-report-card`,
      'https://www.pitchrank.io/report-card',
      'https://www.pitchrank.io/rankings/in/u13/male',
    ]);
  });

  it('fits on one page with very long team and opponent names', async () => {
    const longest = baseProps();
    longest.team.team_name =
      'Southern Indiana United Futbol Club Academy 2014 Boys Red Elite Premier ECNL RL North Div';
    longest.ranking.rank_change_30d = -1234;
    longest.nextGame = { game_date: 'Nov 20', opponent_name: 'Southern Indiana United Futbol Club Academy 2014 Boys' };
    longest.games = Array.from({ length: 5 }, () => ({
      game_date: 'Sep 12',
      opponent_name:
        'Southern Indiana United Futbol Club Academy 2014 Boys Red Elite Premier ECNL Regional League North',
      score: '10-10',
      result: 'D' as const,
    }));

    expect(await pageCount(baseProps())).toBe(1);
    expect(await pageCount(longest)).toBe(1);
  }, 30_000);
});
