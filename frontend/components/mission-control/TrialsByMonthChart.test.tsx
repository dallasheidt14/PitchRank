// Real Recharts drawing the bars; element sizes are stubbed, since happy-dom has no layout.
import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { TrialsByMonthChart } from './TrialsByMonthChart';

const months = [
  { label: 'June 2026', trials: 1 },
  { label: 'July 2026', trials: 0 },
  { label: 'August 2026', trials: 12 },
  { label: 'September 2026', trials: 5 },
];

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  vi.restoreAllMocks();
});

async function render() {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    return (
      this.id === 'recharts_measurement_span'
        ? { width: (this.textContent ?? '').length * 6, height: 13 }
        : // The tooltip maps the pointer to a bar from the chart's left and top.
          { width: 600, height: 220, left: 0, top: 0, x: 0, y: 0, right: 600, bottom: 220 }
    ) as DOMRect;
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(TrialsByMonthChart, { months })));
  return container;
}

async function tooltipAt(chart: HTMLElement, clientX: number) {
  await act(async () => {
    chart
      .querySelector('.recharts-wrapper')!
      .dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX, clientY: 110 }));
  });
  const tooltip = () => chart.querySelector('.recharts-tooltip-wrapper')?.textContent ?? '';
  await vi.waitFor(() => expect(tooltip()).not.toBe(''));
  return tooltip();
}

describe('TrialsByMonthChart', () => {
  it('names every month and its count, marking the current month as still filling in', async () => {
    const chart = await render();
    expect(chart.querySelector('[role="img"]')?.getAttribute('aria-label')).toBe(
      'Trials started per month. June 2026: 1 trial, July 2026: 0 trials, August 2026: 12 trials, September 2026: 5 trials so far.'
    );
  });

  it('labels the axis with short month names in order', async () => {
    const chart = await render();
    const labels = [...chart.querySelectorAll('.recharts-xAxis-tick-labels text')].map((node) => node.textContent);
    expect(labels).toEqual(['Jun', 'Jul', 'Aug', 'Sep']);
  });

  it("prints each month's count above its bar", async () => {
    const chart = await render();
    const counts = () => [...chart.querySelectorAll('.recharts-label-list text')].map((node) => node.textContent);
    // Recharts draws the labels once the bars finish animating in. July had
    // none, so it has no bar to label; the axis and tooltip still show it.
    await vi.waitFor(() => expect(counts()).toEqual(['1', '12', '5']));
  });

  it('shows a month with no trials as zero in its tooltip', async () => {
    const chart = await render();
    expect(await tooltipAt(chart, 250)).toBe('July 20260 trials');
  });

  it('marks the current month as so far in its tooltip', async () => {
    const chart = await render();
    expect(await tooltipAt(chart, 560)).toBe('September 20265 trials so far');
  });
});
