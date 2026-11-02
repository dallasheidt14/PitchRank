import { describe, expect, it } from 'vitest';
import { makeCleanupCardRow, makePairCard, makePairCardRow } from '@/test/fixtures';
import {
  alikeSets,
  appliedChange,
  changeText,
  cleanWeeks,
  cleanupWeek,
  evidenceLines,
  groupCards,
  newestBuild,
  pairEvidenceLines,
  stageReviews,
  tally,
  type SpotCheckRun,
  type SpotVerdict,
} from './cleanup';

describe('evidenceLines', () => {
  const none = { opponents: {}, opponents_total: 0, club: {}, gotsport: null, name: { state: null, how: 'none' } };

  it('says where the name points, when it points two ways, and when its state word places nothing', () => {
    expect(evidenceLines({ ...none, name: { state: 'NV', how: 'town' } })).toEqual([
      'Name points to NV (a town in the name)',
    ]);
    expect(evidenceLines({ ...none, name: { state: null, how: 'conflict' } })).toEqual(['Name points two ways']);
    expect(evidenceLines({ ...none, name: { state: null, how: 'unplaced' } })).toEqual([
      "Name mentions a state it can't be placed by",
    ]);
  });

  it('counts opponents with no stored state only in the total', () => {
    expect(evidenceLines({ ...none, opponents_total: 4 })).toEqual([
      'Opponents: none with a state (of 4 teams played)',
    ]);
  });

  it('orders a tie by state and says nothing for a card with no evidence', () => {
    expect(evidenceLines({ ...none, club: { UT: 3, NV: 3 } })).toEqual(['Club-mates: NV 3 · UT 3']);
    expect(evidenceLines(none)).toEqual([]);
    expect(evidenceLines(undefined)).toEqual([]);
  });
});

describe('pairEvidenceLines', () => {
  it('says when a pair shares no opponent, leaves out an overlap it cannot measure, and counts the days both played', () => {
    expect(
      pairEvidenceLines({
        doorway: 'D',
        shared_opponents: 0,
        shared_opponent_names: [],
        shared_dates: 1,
        opponent_overlap: null,
      })
    ).toEqual([
      "Found as one club's squad under two spellings",
      'No shared opponents',
      'Played on the same day 1 time',
    ]);
  });
});

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
    const choices = {
      a: { decision: 'apply', note: '', swap: false },
      c: { decision: null, note: 'x', swap: false },
    } as const;
    expect(tally(rows, choices)).toEqual({
      apply: 1,
      dont_apply: 0,
      unsure: 0,
      undecided: 2,
    });
  });
});

describe('appliedChange', () => {
  it('counts an automatic change unless the review kept the stored value or the two teams apart', () => {
    expect(appliedChange(makeCleanupCardRow({ lane: 'auto', decision: 'apply' }), false)).toBe(true);
    expect(
      appliedChange(makeCleanupCardRow({ lane: 'auto', decision: 'apply', card: { keep_as_is: true } }), false)
    ).toBe(false);
    expect(
      appliedChange(makePairCardRow({ lane: 'auto', decision: 'apply', card: { keep_separate: true } }), false)
    ).toBe(false);
  });

  it("counts the owner's Apply only once the review is done", () => {
    expect(appliedChange(makeCleanupCardRow({ lane: 'owner', decision: 'apply' }), false)).toBe(false);
    expect(appliedChange(makeCleanupCardRow({ lane: 'owner', decision: 'apply' }), true)).toBe(true);
    expect(appliedChange(makeCleanupCardRow({ lane: 'owner', decision: 'dont_apply' }), true)).toBe(false);
  });
});

describe('changeText', () => {
  it('names a merge the way it applied, the swap turning which row was kept', () => {
    const row = makePairCardRow({ lane: 'auto', decision: 'apply' });
    expect(changeText(row)).toBe('Phoenix Rising B13 Premier merged into Phoenix Rising 2013 Boys');
    expect(changeText({ ...row, swap: true })).toBe('Phoenix Rising 2013 Boys merged into Phoenix Rising B13 Premier');
  });
});

describe('cleanupWeek', () => {
  it('names a run by the Wednesday on or before its date', () => {
    expect(['2026-10-28-all', '2026-10-31-ca', '2026-11-03-all'].map(cleanupWeek)).toEqual([
      '2026-10-28',
      '2026-10-28',
      '2026-10-28',
    ]);
    expect(cleanupWeek('2026-11-04-all')).toBe('2026-11-04');
  });
});

describe('cleanWeeks', () => {
  function run(runId: string, ...verdicts: Array<SpotVerdict | null>): SpotCheckRun {
    return {
      runId,
      checks: verdicts.map((verdict, i) => ({
        cardId: `${runId}-${i}`,
        position: i + 1,
        card: makePairCard(),
        swap: false,
        verdict,
        note: null,
      })),
    };
  }

  it('counts the weeks in a row, newest first, whose every merge was judged right', () => {
    expect(
      cleanWeeks([
        run('2026-11-04-all', 'right', 'right'),
        run('2026-10-28-all', 'right'),
        run('2026-10-21-all', 'wrong'),
        run('2026-10-14-all', 'right'),
      ])
    ).toBe(2);
  });

  it("counts a week's runs as one week, and one merge judged wrong spoils the whole week", () => {
    expect(
      cleanWeeks([run('2026-10-31-ca', 'right'), run('2026-10-29-all', 'right'), run('2026-10-28-all', 'right')])
    ).toBe(1);
    expect(cleanWeeks([run('2026-10-29-all', 'right'), run('2026-10-28-all', 'wrong')])).toBe(0);
  });

  it('stops at a week with no sample', () => {
    expect(cleanWeeks([run('2026-11-04-all', 'right'), run('2026-10-21-all', 'right')])).toBe(1);
  });

  it('passes over the newest week while it is still being judged, but not an older one', () => {
    expect(
      cleanWeeks([run('2026-11-04-all', 'right', null), run('2026-10-28-all', 'right'), run('2026-10-21-all', 'right')])
    ).toBe(2);
    expect(
      cleanWeeks([run('2026-11-04-all', 'right'), run('2026-10-28-all', null), run('2026-10-21-all', 'right')])
    ).toBe(1);
  });

  it('counts none when the newest week holds a merge judged wrong, judged in full or not', () => {
    expect(cleanWeeks([run('2026-11-04-all', 'wrong', null), run('2026-10-28-all', 'right')])).toBe(0);
    expect(cleanWeeks([])).toBe(0);
  });
});
