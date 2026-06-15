import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getWatchedTeams,
  addToWatchlist,
  removeFromWatchlist,
  isWatched,
  initWatchlist,
  fetchWatchlist,
  addToSupabaseWatchlist,
  removeFromSupabaseWatchlist,
} from './watchlist';

const KEY = 'pitchrank_watchedTeams';

/** Build a minimal fetch Response stand-in for the fields these helpers read. */
function jsonResponse(data: unknown, init: { ok?: boolean; status?: number } = {}) {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => data,
  } as Response;
}

beforeEach(() => {
  localStorage.clear();
  // These helpers log liberally on both success and failure; keep test output quiet.
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('watchlist localStorage helpers', () => {
  it('getWatchedTeams returns an empty array when nothing is stored', () => {
    expect(getWatchedTeams()).toEqual([]);
  });

  it('getWatchedTeams returns the stored list', () => {
    localStorage.setItem(KEY, JSON.stringify(['a', 'b']));
    expect(getWatchedTeams()).toEqual(['a', 'b']);
  });

  it('getWatchedTeams returns an empty array (not a throw) on malformed JSON', () => {
    localStorage.setItem(KEY, 'not json');
    expect(getWatchedTeams()).toEqual([]);
  });

  it('addToWatchlist persists a new team', () => {
    addToWatchlist('team-1');
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual(['team-1']);
  });

  it('addToWatchlist is idempotent — no duplicate entries', () => {
    addToWatchlist('team-1');
    addToWatchlist('team-1');
    expect(getWatchedTeams()).toEqual(['team-1']);
  });

  it('removeFromWatchlist drops only the target, keeping the rest', () => {
    localStorage.setItem(KEY, JSON.stringify(['a', 'b', 'c']));
    removeFromWatchlist('b');
    expect(getWatchedTeams()).toEqual(['a', 'c']);
  });

  it('isWatched reflects membership', () => {
    addToWatchlist('team-1');
    expect(isWatched('team-1')).toBe(true);
    expect(isWatched('team-2')).toBe(false);
  });
});

describe('watchlist Supabase API wrappers', () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('initWatchlist', () => {
    it('returns the watchlist object on success', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ watchlist: { id: 'wl-1', name: 'Default' } }));

      await expect(initWatchlist()).resolves.toEqual({ id: 'wl-1', name: 'Default' });
      expect(mockFetch).toHaveBeenCalledWith('/api/watchlist/init', expect.objectContaining({ method: 'POST' }));
    });

    it('returns null on a non-OK response', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ error: 'nope' }, { ok: false, status: 403 }));
      await expect(initWatchlist()).resolves.toBeNull();
    });

    it('returns null when fetch throws', async () => {
      mockFetch.mockRejectedValue(new Error('network down'));
      await expect(initWatchlist()).resolves.toBeNull();
    });
  });

  describe('fetchWatchlist', () => {
    it('returns the parsed result on success', async () => {
      const result = { watchlist: { id: 'wl-1' }, teams: [{ team_id_master: 't1' }] };
      mockFetch.mockResolvedValue(jsonResponse(result));

      await expect(fetchWatchlist()).resolves.toEqual(result);
    });

    it('returns an empty default watchlist on 403 (non-premium)', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ error: 'premium required' }, { ok: false, status: 403 }));

      const res = await fetchWatchlist();
      expect(res).toEqual({
        watchlist: { id: '', name: '', is_default: true, created_at: '', updated_at: '' },
        teams: [],
      });
    });

    it('returns null on other non-OK responses', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ error: 'server error' }, { ok: false, status: 500 }));
      await expect(fetchWatchlist()).resolves.toBeNull();
    });

    it('returns null when fetch throws', async () => {
      mockFetch.mockRejectedValue(new Error('boom'));
      await expect(fetchWatchlist()).resolves.toBeNull();
    });
  });

  describe('addToSupabaseWatchlist', () => {
    it('posts the team id and reports success', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ message: 'Team added' }));

      await expect(addToSupabaseWatchlist('t1')).resolves.toEqual({ success: true, message: 'Team added' });
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/watchlist/add',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ teamIdMaster: 't1' }) })
      );
    });

    it('surfaces the server error message on a non-OK response', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ error: 'Already watching' }, { ok: false, status: 409 }));
      await expect(addToSupabaseWatchlist('t1')).resolves.toEqual({ success: false, message: 'Already watching' });
    });

    it('reports a network error when fetch throws', async () => {
      mockFetch.mockRejectedValue(new Error('offline'));
      await expect(addToSupabaseWatchlist('t1')).resolves.toEqual({ success: false, message: 'Network error' });
    });
  });

  describe('removeFromSupabaseWatchlist', () => {
    it('posts the team id and reports success', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ message: 'Team removed' }));

      await expect(removeFromSupabaseWatchlist('t1')).resolves.toEqual({ success: true, message: 'Team removed' });
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/watchlist/remove',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ teamIdMaster: 't1' }) })
      );
    });

    it('surfaces the server error message on a non-OK response', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ error: 'Not found' }, { ok: false, status: 404 }));
      await expect(removeFromSupabaseWatchlist('t1')).resolves.toEqual({ success: false, message: 'Not found' });
    });

    it('reports a network error when fetch throws', async () => {
      mockFetch.mockRejectedValue(new Error('offline'));
      await expect(removeFromSupabaseWatchlist('t1')).resolves.toEqual({ success: false, message: 'Network error' });
    });
  });
});
