/**
 * Watchlist utilities for managing watched teams
 *
 * Supports both:
 * - localStorage (legacy, for backwards compatibility during migration)
 * - Supabase API (premium users)
 */

import type { WatchlistResponse, WatchlistTeam } from "@/app/api/watchlist/route";

const WATCHLIST_KEY = "pitchrank_watchedTeams";

// ===== localStorage Functions (Legacy) =====

/**
 * Get watched teams from localStorage
 * @deprecated Use fetchWatchlist() for premium users
 */
export function getWatchedTeams(): string[] {
  if (typeof window === "undefined") return [];

  try {
    const stored = localStorage.getItem(WATCHLIST_KEY);
    if (!stored) return [];
    return JSON.parse(stored) as string[];
  } catch (e) {
    console.warn("Could not read watchlist from localStorage:", e);
    return [];
  }
}

/**
 * Add team to localStorage watchlist
 * @deprecated Use addToSupabaseWatchlist() for premium users
 */
export function addToWatchlist(teamId: string): void {
  if (typeof window === "undefined") return;

  try {
    const watched = getWatchedTeams();
    if (!watched.includes(teamId)) {
      watched.push(teamId);
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watched));
    }
  } catch (e) {
    console.warn("Could not save to watchlist:", e);
  }
}

/**
 * Remove team from localStorage watchlist
 * @deprecated Use removeFromSupabaseWatchlist() for premium users
 */
export function removeFromWatchlist(teamId: string): void {
  if (typeof window === "undefined") return;

  try {
    const watched = getWatchedTeams();
    const filtered = watched.filter((id) => id !== teamId);
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(filtered));
  } catch (e) {
    console.warn("Could not remove from watchlist:", e);
  }
}

/**
 * Check if team is in localStorage watchlist
 * @deprecated Use isInSupabaseWatchlist() for premium users
 */
export function isWatched(teamId: string): boolean {
  return getWatchedTeams().includes(teamId);
}

// ===== Supabase API Functions (Premium) =====

/**
 * Initialize the user's watchlist (creates if doesn't exist)
 * @returns The watchlist object or null on error
 */
export async function initWatchlist(): Promise<{
  id: string;
  name: string;
} | null> {
  try {
    const response = await fetch("/api/watchlist/init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      console.error("Failed to init watchlist:", response.status, data.error);
      return null;
    }

    const data = await response.json();
    return data.watchlist;
  } catch (error) {
    console.error("Error initializing watchlist:", error);
    return null;
  }
}

/**
 * Fetch the user's watchlist with full team data
 * @returns WatchlistResponse or null on error
 */
export async function fetchWatchlist(): Promise<WatchlistResponse | null> {
  console.log("[fetchWatchlist] Starting fetch...");
  try {
    const response = await fetch("/api/watchlist", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
    });

    console.log("[fetchWatchlist] Response status:", response.status);

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      console.log("[fetchWatchlist] Error response:", data);

      // 403 = not premium, return empty
      if (response.status === 403) {
        console.log("[fetchWatchlist] 403 - returning empty watchlist");
        return {
          watchlist: { id: "", name: "", is_default: true, created_at: "", updated_at: "" },
          teams: [],
        };
      }

      console.error("[fetchWatchlist] Failed:", response.status, data.error);
      return null;
    }

    const result = await response.json();
    console.log("[fetchWatchlist] Success:", {
      hasWatchlist: !!result.watchlist,
      watchlistId: result.watchlist?.id,
      teamsCount: result.teams?.length ?? 0,
      teamIds: result.teams?.map((t: any) => t.team_id_master) ?? [],
    });
    return result;
  } catch (error) {
    console.error("[fetchWatchlist] Error:", error);
    return null;
  }
}

/**
 * Add a team to the Supabase watchlist
 * @param teamIdMaster - The team's UUID
 * @returns Success status and message
 */
export async function addToSupabaseWatchlist(
  teamIdMaster: string
): Promise<{ success: boolean; message: string }> {
  try {
    console.log("[Watchlist] Adding team to Supabase:", teamIdMaster);

    const response = await fetch("/api/watchlist/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ teamIdMaster }),
    });

    const data = await response.json();
    console.log("[Watchlist] Add response:", response.status, data);

    if (!response.ok) {
      return { success: false, message: data.error || "Failed to add team" };
    }

    return { success: true, message: data.message || "Team added" };
  } catch (error) {
    console.error("[Watchlist] Error adding to watchlist:", error);
    return { success: false, message: "Network error" };
  }
}

/**
 * Remove a team from the Supabase watchlist
 * @param teamIdMaster - The team's UUID
 * @returns Success status and message
 */
export async function removeFromSupabaseWatchlist(
  teamIdMaster: string
): Promise<{ success: boolean; message: string }> {
  try {
    console.log("[Watchlist] Removing team from Supabase:", teamIdMaster);

    const response = await fetch("/api/watchlist/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ teamIdMaster }),
    });

    const data = await response.json();
    console.log("[Watchlist] Remove response:", response.status, data);

    if (!response.ok) {
      return { success: false, message: data.error || "Failed to remove team" };
    }

    return { success: true, message: data.message || "Team removed" };
  } catch (error) {
    console.error("[Watchlist] Error removing from watchlist:", error);
    return { success: false, message: "Network error" };
  }
}

/**
 * Check if a team is in the Supabase watchlist
 * @param teamIdMaster - The team's UUID
 * @param watchlistTeams - Array of teams from fetchWatchlist
 * @returns Whether the team is in the watchlist
 */
export function isInSupabaseWatchlist(
  teamIdMaster: string,
  watchlistTeams: WatchlistTeam[]
): boolean {
  return watchlistTeams.some((t) => t.team_id_master === teamIdMaster);
}

// ===== Unified Functions (Auto-detect Premium) =====

/**
 * Add team to watchlist (auto-detects premium status)
 * For premium users, adds to Supabase. For free users, adds to localStorage.
 */
export async function addTeamToWatchlist(
  teamIdMaster: string,
  isPremium: boolean
): Promise<{ success: boolean; message: string }> {
  if (isPremium) {
    return addToSupabaseWatchlist(teamIdMaster);
  }

  // For free users, use localStorage (legacy behavior)
  addToWatchlist(teamIdMaster);
  return { success: true, message: "Added to local watchlist" };
}

/**
 * Remove team from watchlist (auto-detects premium status)
 */
export async function removeTeamFromWatchlist(
  teamIdMaster: string,
  isPremium: boolean
): Promise<{ success: boolean; message: string }> {
  if (isPremium) {
    return removeFromSupabaseWatchlist(teamIdMaster);
  }

  // For free users, use localStorage (legacy behavior)
  removeFromWatchlist(teamIdMaster);
  return { success: true, message: "Removed from local watchlist" };
}
