import { describe, it, expect } from 'vitest';
import { gscRowsToObjects, computeGscDeltas } from '../gsc';

describe('gscRowsToObjects', () => {
  it('maps GSC `keys` array to dimension columns', () => {
    const raw = {
      rows: [
        { keys: ['youth soccer rankings'], clicks: 120, impressions: 5000, ctr: 0.024, position: 6.3 },
        { keys: ['club soccer az'], clicks: 95, impressions: 4200, ctr: 0.022, position: 7.1 },
      ],
    };
    const result = gscRowsToObjects(raw, ['query']);
    expect(result).toEqual([
      { query: 'youth soccer rankings', clicks: 120, impressions: 5000, ctr: 0.024, position: 6.3 },
      { query: 'club soccer az', clicks: 95, impressions: 4200, ctr: 0.022, position: 7.1 },
    ]);
  });
});

describe('computeGscDeltas', () => {
  it('returns absolute deltas for ctr and position, percent deltas for clicks and impressions', () => {
    const d = computeGscDeltas(
      { clicks: 110, impressions: 5500, ctr: 0.025, position: 5.8 },
      { clicks: 100, impressions: 5000, ctr: 0.02, position: 6.3 }
    );
    expect(d.clicks_delta).toBeCloseTo(0.1);
    expect(d.impressions_delta).toBeCloseTo(0.1);
    expect(d.ctr_delta).toBeCloseTo(0.005);
    expect(d.position_delta).toBeCloseTo(0.5); // lower position is better → positive when improved
  });
});
