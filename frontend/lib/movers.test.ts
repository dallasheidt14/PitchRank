import { afterEach, describe, expect, it, vi } from 'vitest';
import { selectTopMovers } from './movers';
import { makeRankingRow as makeTeam } from '@/test/fixtures';

// Fixture defaults put last_game inside both the 7d and 30d windows.

afterEach(() => {
  vi.useRealTimers();
});

describe('selectTopMovers', () => {
  it('orders by absolute change descending and caps at maxItems', () => {
    const teams = [
      makeTeam({ team_id_master: 'a', rank_change_7d: 40 }),
      makeTeam({ team_id_master: 'b', rank_in_cohort_final: 400, rank_change_7d: -90 }),
      makeTeam({ team_id_master: 'c', rank_change_7d: 10 }),
    ];

    const result = selectTopMovers(teams, '7d', 2);

    expect(result.map((t) => t.team_id_master)).toEqual(['b', 'a']);
  });

  it('excludes teams currently ranked outside the top 500', () => {
    const teams = [
      // A faller: prior rank 301 is inside the band, so only the current-rank
      // guard can exclude it.
      makeTeam({ team_id_master: 'out', rank_in_cohort_final: 501, rank_change_7d: -200 }),
      makeTeam({ team_id_master: 'in', rank_in_cohort_final: 500, rank_change_7d: -50 }),
    ];

    const result = selectTopMovers(teams, '7d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['in']);
  });

  it('excludes teams whose prior rank was outside the top 500', () => {
    const teams = [
      // Prior rank = current + change: 100 + 1000 = 1100, a rise from deep outside the band.
      makeTeam({ team_id_master: 'deep-riser', rank_in_cohort_final: 100, rank_change_7d: 1000 }),
      makeTeam({ team_id_master: 'band-riser', rank_in_cohort_final: 300, rank_change_7d: 150 }),
    ];

    const result = selectTopMovers(teams, '7d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['band-riser']);
  });

  it('draws the prior-rank boundary exactly at 500', () => {
    const teams = [
      // Prior ranks: 350 + 150 = 500 (in), 349 + 152 = 501 (out).
      makeTeam({ team_id_master: 'edge-in', rank_in_cohort_final: 350, rank_change_7d: 150 }),
      makeTeam({ team_id_master: 'edge-out', rank_in_cohort_final: 349, rank_change_7d: 152 }),
    ];

    const result = selectTopMovers(teams, '7d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['edge-in']);
  });

  it('excludes teams without a game inside the 7d window', () => {
    const teams = [
      makeTeam({ team_id_master: 'stale', last_game: '2026-08-10T00:00:00Z', rank_change_7d: 300 }),
      makeTeam({ team_id_master: 'fresh', last_game: '2026-08-22T00:00:00Z', rank_change_7d: 50 }),
    ];

    const result = selectTopMovers(teams, '7d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['fresh']);
  });

  it('counts the window in whole calendar days, not run-time milliseconds', () => {
    // Game dates are date-only (midnight UTC) while the run stamps mid-day, so a
    // game exactly seven calendar days back must still be inside the 7d window.
    const teams = [
      makeTeam({
        team_id_master: 'seventh-day',
        last_calculated: '2026-08-24T15:30:00Z',
        last_game: '2026-08-17T00:00:00Z',
        rank_change_7d: 50,
      }),
      makeTeam({
        team_id_master: 'eighth-day',
        last_calculated: '2026-08-24T15:30:00Z',
        last_game: '2026-08-16T00:00:00Z',
        rank_change_7d: 300,
      }),
    ];

    const result = selectTopMovers(teams, '7d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['seventh-day']);
  });

  it('reads the 30d change field for the 30d window', () => {
    // 7d and 30d values disagree in both magnitude and sign, so reading the
    // wrong column changes ordering and inclusion.
    const teams = [
      makeTeam({
        team_id_master: 'flat-week',
        rank_change_7d: 0,
        rank_change_30d: 200,
        last_game: '2026-08-04T00:00:00Z',
      }),
      makeTeam({ team_id_master: 'small-month', rank_change_7d: -300, rank_change_30d: -60 }),
    ];

    const result = selectTopMovers(teams, '30d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['flat-week', 'small-month']);
  });

  it('widens the played-recently window to 30 days for 30d movers', () => {
    const teams = [
      makeTeam({
        team_id_master: 'in-window',
        last_game: '2026-08-04T00:00:00Z',
        rank_change_7d: 0,
        rank_change_30d: 60,
      }),
      makeTeam({
        team_id_master: 'out-of-window',
        last_game: '2026-07-20T00:00:00Z',
        rank_change_7d: 0,
        rank_change_30d: 200,
      }),
    ];

    const result = selectTopMovers(teams, '30d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['in-window']);
  });

  it('judges every row against the newest last_calculated in the dataset', () => {
    // A partial save leaves some rows stamped by an older run; anchoring to the
    // oldest would slide the cutoff back and admit 'stale'.
    const teams = [
      makeTeam({ team_id_master: 'old-stamp', last_calculated: '2026-08-10T12:00:00Z', rank_change_7d: 70 }),
      makeTeam({ team_id_master: 'new-stamp' }),
      makeTeam({
        team_id_master: 'stale',
        last_calculated: '2026-08-10T12:00:00Z',
        last_game: '2026-08-05T00:00:00Z',
        rank_change_7d: 300,
      }),
      makeTeam({
        team_id_master: 'missing-stamp',
        last_calculated: null,
        last_game: '2026-08-21T00:00:00Z',
        rank_change_7d: 60,
      }),
    ];

    const result = selectTopMovers(teams, '7d', 5);

    expect(result.map((t) => t.team_id_master).sort()).toEqual(['missing-stamp', 'new-stamp', 'old-stamp']);
  });

  it('anchors the window to the data even when the clock has moved on', () => {
    // The homepage re-renders hourly for a week off one Monday ranking run, so
    // the reference must not follow the wall clock.
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-30T12:00:00Z'));
    const teams = [makeTeam({ team_id_master: 'still-fresh' })];

    expect(selectTopMovers(teams, '7d', 5).map((t) => t.team_id_master)).toEqual(['still-fresh']);
  });

  it('keeps the recency gate closed when last_calculated is unparseable', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-24T12:00:00Z'));
    const teams = [
      makeTeam({
        team_id_master: 'stale',
        last_calculated: 'not-a-date',
        last_game: '2026-08-01T00:00:00Z',
        rank_change_7d: 300,
      }),
      makeTeam({
        team_id_master: 'fresh',
        last_calculated: 'not-a-date',
        last_game: '2026-08-22T00:00:00Z',
        rank_change_7d: 50,
      }),
    ];

    const result = selectTopMovers(teams, '7d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['fresh']);
  });

  it('falls back to the current day when no row carries last_calculated', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-24T12:00:00Z'));
    const teams = [
      makeTeam({ team_id_master: 'recent', last_calculated: null, last_game: '2026-08-20T00:00:00Z' }),
      makeTeam({
        team_id_master: 'dormant',
        last_calculated: null,
        last_game: '2026-06-01T00:00:00Z',
        rank_change_7d: 300,
      }),
    ];

    const result = selectTopMovers(teams, '7d', 5);

    expect(result.map((t) => t.team_id_master)).toEqual(['recent']);
  });

  it('excludes teams with no recorded last game', () => {
    const teams = [makeTeam({ team_id_master: 'no-game', last_game: null, rank_change_7d: 200 })];

    expect(selectTopMovers(teams, '7d', 5)).toEqual([]);
  });

  it('excludes teams with fewer than 8 games but keeps teams with exactly 8', () => {
    const teams = [
      makeTeam({ team_id_master: 'few-games', total_games_played: 7, rank_change_7d: 200 }),
      makeTeam({ team_id_master: 'eight-games', total_games_played: 8, rank_change_7d: 50 }),
    ];

    expect(selectTopMovers(teams, '7d', 5).map((t) => t.team_id_master)).toEqual(['eight-games']);
  });

  it('excludes teams with zero or missing change', () => {
    const teams = [
      makeTeam({ team_id_master: 'zero', rank_change_7d: 0 }),
      makeTeam({ team_id_master: 'missing', rank_change_7d: null }),
    ];

    expect(selectTopMovers(teams, '7d', 5)).toEqual([]);
  });

  it('excludes teams that are not fully ranked', () => {
    const teams = [makeTeam({ team_id_master: 'nerg', status: 'Not Enough Ranked Games', rank_change_7d: 200 })];

    expect(selectTopMovers(teams, '7d', 5)).toEqual([]);
  });
});
