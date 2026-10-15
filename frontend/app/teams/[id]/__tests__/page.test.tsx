// notFound() and redirect() signal by throwing, so the page's own try/catch must let them through.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockCreateClient } = vi.hoisted(() => ({ mockCreateClient: vi.fn() }));

vi.mock('@supabase/supabase-js', () => ({ createClient: mockCreateClient }));
vi.mock('@/components/TeamPageShell', () => ({ TeamPageShell: () => null }));
vi.mock('@/components/skeletons/TeamPageSkeleton', () => ({ TeamPageSkeleton: () => null }));

import Page from '../page';

const MERGED_ID = '11111111-1111-4111-8111-111111111111';
const SURVIVOR_ID = '22222222-2222-4222-8222-222222222222';

let svc: ReturnType<typeof serviceClientMock>;

function render(id: string) {
  return Page({ params: Promise.resolve({ id }) });
}

beforeEach(() => {
  svc = serviceClientMock();
  mockCreateClient.mockReturnValue(svc.client);
  vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL', 'https://example.supabase.co');
  vi.stubEnv('NEXT_PUBLIC_SUPABASE_ANON_KEY', 'anon-key');
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('team page existence check', () => {
  it("sends a merged team's old link to the team it was merged into", async () => {
    svc.queueFrom('teams', { data: { team_id_master: MERGED_ID, is_deprecated: true }, error: null });
    svc.queueFrom('team_merge_map', { data: { canonical_team_id: SURVIVOR_ID }, error: null });

    await expect(render(MERGED_ID)).rejects.toMatchObject({
      digest: expect.stringContaining(`/teams/${SURVIVOR_ID}`),
    });
    const mergeLookup = svc.from.mock.results[svc.from.mock.calls.findIndex(([table]) => table === 'team_merge_map')];
    expect((mergeLookup.value as { eq: ReturnType<typeof vi.fn> }).eq).toHaveBeenCalledWith(
      'deprecated_team_id',
      MERGED_ID
    );
  });

  it('answers a merged team with nowhere to go with not found', async () => {
    svc.queueFrom('teams', { data: { team_id_master: MERGED_ID, is_deprecated: true }, error: null });

    await expect(render(MERGED_ID)).rejects.toMatchObject({ digest: expect.stringContaining('404') });
  });

  it('answers a malformed id with not found', async () => {
    await expect(render('not-a-uuid')).rejects.toMatchObject({ digest: expect.stringContaining('404') });
  });

  // Search lists teams that have no games yet, and their page is where a member reports missing games. The empty
  // games count is there so a reinstated no-games check would answer 404.
  it('renders a team that has no games yet', async () => {
    svc.queueFrom('teams', { data: { team_id_master: SURVIVOR_ID, is_deprecated: false }, error: null });
    svc.queueFrom('games', { data: null, error: null, count: 0 });

    await expect(render(SURVIVOR_ID)).resolves.toBeTruthy();
  });

  it('still renders the page when the existence check itself fails', async () => {
    svc.queueFrom('teams', { data: null, error: { message: 'timeout' } });

    await expect(render(SURVIVOR_ID)).resolves.toBeTruthy();
  });

  it("still renders a merged team's page when the merge lookup fails", async () => {
    svc.queueFrom('teams', { data: { team_id_master: MERGED_ID, is_deprecated: true }, error: null });
    svc.queueFrom('team_merge_map', { data: null, error: { message: 'timeout' } });

    await expect(render(MERGED_ID)).resolves.toBeTruthy();
    expect(console.error).toHaveBeenCalledWith('Error looking up merged team:', { message: 'timeout' });
  });

  it('still renders the page when the check throws an error of its own', async () => {
    // supabase-js refuses a malformed project URL by throwing, not by returning an error.
    mockCreateClient.mockImplementationOnce(() => {
      throw new Error('Invalid supabaseUrl: Must be a valid HTTP or HTTPS URL.');
    });

    await expect(render(SURVIVOR_ID)).resolves.toBeTruthy();
    expect(console.error).toHaveBeenCalledWith('Error in team existence check:', expect.any(Error));
  });
});
