import { describe, it, expect } from 'vitest';
import { formatTeamRecord } from './team-record';

describe('formatTeamRecord', () => {
  it('uses the lifetime total_* record as a group when it is present', () => {
    expect(formatTeamRecord({ total_wins: 20, total_losses: 5, total_draws: 3, wins: 4, losses: 1, draws: 0 })).toBe(
      '20-5-3'
    );
  });

  it('falls back to the season record when no total_* record exists', () => {
    expect(
      formatTeamRecord({ total_wins: null, total_losses: null, total_draws: null, wins: 4, losses: 1, draws: 0 })
    ).toBe('4-1-0');
  });

  it('never mixes lifetime and season: a partial total_* record stays on the total side', () => {
    // Bug C32: per-field ?? fallback produced "20-1-0" (lifetime wins + season losses).
    const record = formatTeamRecord({
      total_wins: 20,
      total_losses: null,
      total_draws: null,
      wins: 4,
      losses: 1,
      draws: 0,
    });
    expect(record).toBe('20-0-0');
    expect(record).not.toBe('20-1-0');
  });

  it('treats missing fields as 0', () => {
    expect(formatTeamRecord({})).toBe('0-0-0');
  });
});
