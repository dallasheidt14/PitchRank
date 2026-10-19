import { describe, expect, it } from 'vitest';
import { makeCleanupCardRow } from '@/test/fixtures';
import { alikeSets, groupCards, newestBuild, stageReviews, tally } from './cleanup';

describe('newestBuild', () => {
  it('takes the build the table saved last, not the latest page run', () => {
    expect(
      newestBuild([
        { page_run: '20261021T180020Z-ffffff', created_at: '2026-10-21T18:01:00+00:00' },
        { page_run: '20261021T180010Z-000000', created_at: '2026-10-21T18:01:00.25+00:00' },
      ])
    ).toBe('20261021T180010Z-000000');
  });

  it('has none for a page with no rows', () => {
    expect(newestBuild([])).toBeNull();
  });
});

describe('stageReviews', () => {
  it("keeps each stage's newest build, owner cards and automatic changes in page order, stages in run order", () => {
    const old = '20261021T170000Z-a1b2c3';
    const rows = [
      makeCleanupCardRow({ page_run: old, created_at: '2026-10-21T17:00:05+00:00' }),
      makeCleanupCardRow({ position: 2, card_id: 'states_2' }),
      makeCleanupCardRow({ position: 1, card_id: 'states_1' }),
      makeCleanupCardRow({ lane: 'auto', decision: 'apply', card_id: 'states_auto' }),
      makeCleanupCardRow({ stage: 'clubs', card_id: 'clubs_1' }),
    ];

    const reviews = stageReviews(rows);

    expect(reviews.map((r) => r.stage)).toEqual(['clubs', 'states']);
    expect(reviews[1].cards.map((r) => r.card_id)).toEqual(['states_1', 'states_2']);
    expect(reviews[1].auto.map((r) => r.card_id)).toEqual(['states_auto']);
  });
});

describe('groups, look-alikes and the tally', () => {
  const rows = [
    makeCleanupCardRow({ card_id: 'a', card: { group: 'B', whole: false, alike: 'k1' } }),
    makeCleanupCardRow({ card_id: 'b', card: { group: 'A', whole: true, alike: null } }),
    makeCleanupCardRow({ card_id: 'c', card: { group: 'B', whole: false, alike: 'k1' } }),
  ];

  it('groups cards in the order a group first appears', () => {
    expect(groupCards(rows).map((g) => [g.group, g.whole, g.cards.map((r) => r.card_id)])).toEqual([
      ['B', false, ['a', 'c']],
      ['A', true, ['b']],
    ]);
  });

  it('sets aside the cards that share a look-alike key', () => {
    expect([...alikeSets(rows)]).toEqual([['k1', ['a', 'c']]]);
  });

  it('counts each decision and the cards left undecided', () => {
    expect(tally(rows, { a: { decision: 'apply', note: '' }, c: { decision: null, note: 'x' } })).toEqual({
      apply: 1,
      dont_apply: 0,
      unsure: 0,
      undecided: 2,
    });
  });
});
