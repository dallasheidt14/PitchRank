import { describe, it, expect } from 'vitest';
import { ga4RowsToObjects } from '../ga4';

describe('ga4RowsToObjects', () => {
  it('merges metric and dimension headers into row objects with parsed numerics', () => {
    const raw = {
      dimensionHeaders: [{ name: 'pagePath' }],
      metricHeaders: [{ name: 'screenPageViews' }, { name: 'engagementRate' }],
      rows: [
        { dimensionValues: [{ value: '/' }], metricValues: [{ value: '120' }, { value: '0.45' }] },
        { dimensionValues: [{ value: '/upgrade' }], metricValues: [{ value: '30' }, { value: '0.62' }] },
      ],
    };
    expect(ga4RowsToObjects(raw)).toEqual([
      { pagePath: '/', screenPageViews: 120, engagementRate: 0.45 },
      { pagePath: '/upgrade', screenPageViews: 30, engagementRate: 0.62 },
    ]);
  });

  it('returns empty array when raw has no rows', () => {
    expect(ga4RowsToObjects({ rows: [] })).toEqual([]);
    expect(ga4RowsToObjects({})).toEqual([]);
  });
});
