/**
 * Watchlist utilities for managing watched teams in localStorage
 */

const WATCHLIST_KEY = 'pitchrank_watchedTeams';

export function getWatchedTeams(): string[] {
  if (typeof window === 'undefined') return [];
  
  try {
    const stored = localStorage.getItem(WATCHLIST_KEY);
    if (!stored) return [];
    return JSON.parse(stored) as string[];
  } catch (e) {
    console.warn('Could not read watchlist from localStorage:', e);
    return [];
  }
}

export function addToWatchlist(teamId: string): void {
  if (typeof window === 'undefined') return;
  
  try {
    const watched = getWatchedTeams();
    if (!watched.includes(teamId)) {
      watched.push(teamId);
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watched));
    }
  } catch (e) {
    console.warn('Could not save to watchlist:', e);
  }
}

export function removeFromWatchlist(teamId: string): void {
  if (typeof window === 'undefined') return;
  
  try {
    const watched = getWatchedTeams();
    const filtered = watched.filter(id => id !== teamId);
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(filtered));
  } catch (e) {
    console.warn('Could not remove from watchlist:', e);
  }
}

export function isWatched(teamId: string): boolean {
  return getWatchedTeams().includes(teamId);
}

