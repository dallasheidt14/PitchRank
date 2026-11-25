import { describe, expect, it } from 'vitest';
import { filteringClientMock } from './supabase-mock';

const A = '11111111-1111-1111-1111-111111111111';
const B = '22222222-2222-2222-2222-222222222222';

/**
 * The point of this double is that it refuses what PostgREST refuses. Each case
 * below is a way it could quietly become more permissive than the real thing,
 * which is the one defect that would make every test built on it pass for the
 * wrong reason.
 */
describe('filteringClientMock', () => {
  const rows = [
    { id: '1', home: A, away: B, score: 1, excluded: false },
    { id: '2', home: B, away: A, score: null, excluded: false },
    { id: '3', home: A, away: B, score: 3, excluded: true },
  ];
  const client = () => filteringClientMock({ games: rows });

  it('errors rather than returning a row when maybeSingle matches several', async () => {
    const result = await client().client.from('games').select('*').eq('home', A).maybeSingle();

    expect(result.data).toBeNull();
    expect(result.error).toMatchObject({ code: 'PGRST116' });
  });

  it('errors when single matches none or several', async () => {
    expect((await client().client.from('games').select('*').eq('home', 'nobody').single()).error).toMatchObject({
      code: 'PGRST116',
    });
    expect((await client().client.from('games').select('*').eq('home', A).single()).error).toMatchObject({
      code: 'PGRST116',
    });
  });

  it('honours the column each or() term names instead of matching either side', async () => {
    const { data } = await client().client.from('games').select('*').or(`home.eq.${A}`);

    expect((data as typeof rows).map((row) => row.id)).toEqual(['1', '3']);
  });

  it('refuses a not() operator and an or() term it does not model', async () => {
    expect(() => client().client.from('games').select('*').not('score', 'gt', 1)).toThrow(/does not model/);
    expect(() => client().client.from('games').select('*').or('score.gt.1')).toThrow(/does not model/);
  });

  it('drops rows failing eq and not, matching PostgREST NULL handling', async () => {
    const { data } = await client().client.from('games').select('*').eq('excluded', false).not('score', 'is', null);

    expect((data as typeof rows).map((row) => row.id)).toEqual(['1']);
  });

  // supabase-js sends eq(col, null) as `eq.null`, which matches no row, NULL ones included: `.is` is how to match NULL.
  it('matches nothing for eq(col, null), as PostgREST does', async () => {
    const { data } = await client().client.from('games').select('*').eq('score', null);

    expect(data).toEqual([]);
  });

  // The real builder sends its request when awaited, so filters see the table as it is then.
  it('lets only the first of two guarded updates built before either is awaited write the row', async () => {
    const db = filteringClientMock({ profiles: [{ id: '1', owner: null }] });
    const first = db.client.from('profiles').update({ owner: 'a' }).eq('id', '1').is('owner', null).select('id');
    const second = db.client.from('profiles').update({ owner: 'b' }).eq('id', '1').is('owner', null).select('id');

    const [a, b] = await Promise.all([first, second]);

    expect(a.data).toEqual([{ id: '1' }]);
    expect(b.data).toEqual([]);
    expect(db.tableRows.profiles).toEqual([{ id: '1', owner: 'a' }]);
  });

  it('reads a single row as it is when awaited, not when the query was built', async () => {
    const db = filteringClientMock({ profiles: [{ id: '1', owner: null }] });
    const read = db.client.from('profiles').select('owner').eq('id', '1').maybeSingle();

    await db.client.from('profiles').update({ owner: 'a' }).eq('id', '1');

    expect((await read).data).toEqual({ owner: 'a' });
  });

  it('sorts by the first order key, then the next, and pages after filtering and sorting', async () => {
    const db = filteringClientMock({
      games: [
        { id: '3', day: '2026-11-01', kept: true },
        { id: '1', day: '2026-11-02', kept: true },
        { id: '2', day: '2026-11-01', kept: true },
        { id: '0', day: '2026-11-01', kept: false },
      ],
    });

    const { data } = await db.client.from('games').select('id').order('day').order('id').range(0, 1).eq('kept', true);

    expect(data).toEqual([{ id: '2' }, { id: '3' }]);
  });

  it('keeps the ids an in() filter was given, not the caller array they came from', async () => {
    const db = filteringClientMock({ games: [{ id: '1' }, { id: '2' }] });
    const ids = ['1'];
    const read = db.client.from('games').select('id').in('id', ids);
    ids.push('2');

    expect((await read).data).toEqual([{ id: '1' }]);
  });

  it('reads rows written after the query was built', async () => {
    const db = filteringClientMock({ profiles: [] });
    const read = db.client.from('profiles').select('id');

    await db.client.from('profiles').insert({ id: '1' });

    expect((await read).data).toEqual([{ id: '1' }]);
  });

  // In JavaScript null >= 0 is true, so a numeric bound is where a missing NULL check would let the row through.
  it('drops NULL from gte, as PostgREST does', async () => {
    const { data } = await client().client.from('games').select('*').gte('score', 0);

    expect((data as typeof rows).map((row) => row.id)).toEqual(['1', '3']);
  });

  it('answers only the columns a plain select names, and a column a row lacks as null', async () => {
    const { data } = await client().client.from('games').select('id, score, missing').eq('home', B);

    expect(data).toEqual([{ id: '2', score: null, missing: null }]);
  });

  it('keeps NULL and missing values in is(col, null), and refuses any other value', async () => {
    const db = filteringClientMock({ games: [{ id: '1', score: null }, { id: '2' }, { id: '3', score: 0 }] });

    const { data } = await db.client.from('games').select('id').is('score', null);

    expect(data).toEqual([{ id: '1' }, { id: '2' }]);
    expect(() =>
      db.client
        .from('games')
        .select('id')
        .is('score', 0 as unknown as null)
    ).toThrow(/does not model/);
  });
});

describe('filteringClientMock updates', () => {
  const fresh = () =>
    filteringClientMock({
      games: [
        { id: '1', score: null, note: 'a' },
        { id: '2', score: 2, note: 'b' },
      ],
    });

  it('changes only the rows its filters leave, and only once the request is sent', async () => {
    const db = fresh();

    const pending = db.client.from('games').update({ note: 'changed' }).is('score', null);
    expect(db.tableRows.games.map((row) => row.note)).toEqual(['a', 'b']);
    await pending;

    expect(db.tableRows.games.map((row) => row.note)).toEqual(['changed', 'b']);
  });

  it('answers a failing table from maybeSingle too, as a lookup against it errors', async () => {
    const db = fresh();
    db.failing.games = { code: '57014', message: 'canceling statement due to statement timeout' };

    const result = await db.client.from('games').select('id').eq('id', '1').maybeSingle();

    expect(result.data).toBeNull();
    expect(result.error).toMatchObject({ code: '57014' });
  });

  it('fails only the write failOn names, leaving the lookup before it and the stored rows alone', async () => {
    const db = fresh();
    const failure = db.failOn({ table: 'games', op: 'update', result: { data: null, error: { message: 'down' } } });

    const lookup = await db.client.from('games').select('id').eq('id', '2').maybeSingle();
    const write = await db.client.from('games').update({ note: 'x' }).eq('id', '2').select('id');

    expect(lookup).toMatchObject({ data: { id: '2' }, error: null });
    expect(write).toEqual({ data: null, error: { message: 'down' } });
    expect(failure.hits).toBe(1);
    expect(db.tableRows.games.map((row) => row.note)).toEqual(['a', 'b']);
  });

  it('answers only as many calls as failOn is given times, then runs the query', async () => {
    const db = fresh();
    db.failOn({ table: 'games', op: 'select', result: { data: null, error: null }, times: 1 });

    const first = await db.client.from('games').select('id').eq('id', '2').maybeSingle();
    const second = await db.client.from('games').select('id').eq('id', '2').maybeSingle();

    expect(first.data).toBeNull();
    expect(second.data).toEqual({ id: '2' });
  });

  it('answers the changed rows only when select follows, as supabase-js does', async () => {
    const quiet = await fresh().client.from('games').update({ note: 'x' }).eq('id', '2');
    const answered = await fresh().client.from('games').update({ note: 'x' }).eq('id', '2').select('id, note');

    expect(quiet.data).toBeNull();
    expect(answered.data).toEqual([{ id: '2', note: 'x' }]);
  });
});
