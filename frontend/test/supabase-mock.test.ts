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
});
