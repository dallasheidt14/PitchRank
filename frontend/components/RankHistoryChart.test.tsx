// Real Recharts choosing the ticks; element sizes are stubbed, since happy-dom has no layout.
import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { RankHistoryChart } from './RankHistoryChart';

const history = vi.hoisted(() =>
  Array.from({ length: 52 }, (_, week) => ({
    snapshot_date: new Date(Date.UTC(2025, 10, 10) + week * 7 * 86400000).toISOString().slice(0, 10),
    rank: 40 + (week % 9),
  }))
);

vi.mock('@/lib/hooks', () => ({
  useRankHistory: () => ({ data: history, isLoading: false, isError: false, error: null, refetch: () => {} }),
}));

const CHAR_WIDTH = 6.2; // a bit wider than 11px DM Sans, the cautious side for an overlap test

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  vi.restoreAllMocks();
});

async function labelsAt(chartWidth: number) {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    return (
      this.id === 'recharts_measurement_span'
        ? { width: (this.textContent ?? '').length * CHAR_WIDTH, height: 13 }
        : { width: chartWidth, height: 180 }
    ) as DOMRect;
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(RankHistoryChart, { teamId: 'x' })));
  return [...container.querySelectorAll('.recharts-xAxis-tick-labels text')].map((node) => {
    const width = (node.textContent ?? '').length * CHAR_WIDTH;
    const x = Number(node.getAttribute('x'));
    return { label: node.textContent, left: x - width / 2, right: x + width / 2 };
  });
}

describe('RankHistoryChart x-axis labels', () => {
  it('thins labels on a phone so none overlap, keeping the first and last month', async () => {
    const labels = await labelsAt(320);
    expect(labels.length).toBeGreaterThan(2);
    expect(labels.slice(1).filter((label, i) => labels[i].right > label.left)).toEqual([]);
    expect([labels[0].label, labels.at(-1)!.label]).toEqual(["Nov 10 '25", 'Nov 2']);
  });

  it('shows every month when there is room', async () => {
    const labels = (await labelsAt(1000)).map((l) => l.label);
    expect(labels).toEqual([
      "Nov 10 '25",
      'Dec 1',
      "Jan 5 '26",
      'Feb 2',
      'Mar 2',
      'Apr 6',
      'May 4',
      'Jun 1',
      'Jul 6',
      'Aug 3',
      'Sep 7',
      'Oct 5',
      'Nov 2',
    ]);
  });
});
