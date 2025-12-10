"use client";

import { useEffect, useRef } from "react";
import type { UserProfile } from "./useUser";
import { hasPremiumAccess } from "./useUser";

const WATCHLIST_KEY = "pitchrank_watchedTeams";
const MIGRATION_DONE_KEY = "pitchrank_watchlist_migrated";

/**
 * Hook to migrate localStorage watchlist to Supabase on premium login.
 *
 * This runs once per user when they first become premium:
 * 1. Reads localStorage watchlist
 * 2. For each team, calls /api/watchlist/add
 * 3. Clears the localStorage key
 * 4. Sets a migration flag to prevent re-runs
 *
 * @param profile - User profile from useUser hook (null if not logged in)
 * @param userId - User's ID for tracking migration status
 */
export function useWatchlistMigration(
  profile: UserProfile | null,
  userId: string | null
): void {
  const migrationAttempted = useRef(false);

  useEffect(() => {
    // Only run on client side
    if (typeof window === "undefined") return;

    // Only run once per session
    if (migrationAttempted.current) return;

    // Only run for premium users
    if (!profile || !userId || !hasPremiumAccess(profile)) return;

    // Check if migration already done for this user
    const migrationKey = `${MIGRATION_DONE_KEY}_${userId}`;
    const alreadyMigrated = localStorage.getItem(migrationKey);
    if (alreadyMigrated === "true") return;

    // Get localStorage watchlist
    const localWatchlist = getLocalStorageWatchlist();
    if (localWatchlist.length === 0) {
      // No local watchlist to migrate, mark as done
      localStorage.setItem(migrationKey, "true");
      return;
    }

    // Mark as attempted to prevent multiple runs
    migrationAttempted.current = true;

    // Perform migration
    migrateWatchlist(localWatchlist, migrationKey);
  }, [profile, userId]);
}

/**
 * Get watchlist from localStorage
 */
function getLocalStorageWatchlist(): string[] {
  try {
    const stored = localStorage.getItem(WATCHLIST_KEY);
    if (!stored) return [];
    return JSON.parse(stored) as string[];
  } catch {
    return [];
  }
}

/**
 * Migrate watchlist items to Supabase
 */
async function migrateWatchlist(
  teamIds: string[],
  migrationKey: string
): Promise<void> {
  console.log(`[Watchlist Migration] Starting migration of ${teamIds.length} teams`);

  let successCount = 0;
  let failCount = 0;

  // First, ensure watchlist is initialized
  try {
    await fetch("/api/watchlist/init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("[Watchlist Migration] Failed to init watchlist:", error);
    return; // Don't mark as migrated if init failed
  }

  // Migrate each team (with some parallelism)
  const BATCH_SIZE = 5;
  for (let i = 0; i < teamIds.length; i += BATCH_SIZE) {
    const batch = teamIds.slice(i, i + BATCH_SIZE);

    const results = await Promise.allSettled(
      batch.map(async (teamIdMaster) => {
        const response = await fetch("/api/watchlist/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ teamIdMaster }),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || "Failed to add team");
        }

        return teamIdMaster;
      })
    );

    for (const result of results) {
      if (result.status === "fulfilled") {
        successCount++;
      } else {
        failCount++;
        console.warn("[Watchlist Migration] Failed to migrate team:", result.reason);
      }
    }
  }

  console.log(
    `[Watchlist Migration] Complete: ${successCount} succeeded, ${failCount} failed`
  );

  // Mark migration as done and clear localStorage
  if (successCount > 0 || failCount === 0) {
    localStorage.setItem(migrationKey, "true");
    localStorage.removeItem(WATCHLIST_KEY);
    console.log("[Watchlist Migration] LocalStorage cleared");
  }
}

/**
 * Manually trigger watchlist migration
 * Useful for testing or forcing re-migration
 */
export async function forceWatchlistMigration(userId: string): Promise<{
  success: boolean;
  migrated: number;
  failed: number;
}> {
  const localWatchlist = getLocalStorageWatchlist();

  if (localWatchlist.length === 0) {
    return { success: true, migrated: 0, failed: 0 };
  }

  let migrated = 0;
  let failed = 0;

  try {
    await fetch("/api/watchlist/init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return { success: false, migrated: 0, failed: localWatchlist.length };
  }

  for (const teamIdMaster of localWatchlist) {
    try {
      const response = await fetch("/api/watchlist/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ teamIdMaster }),
      });

      if (response.ok) {
        migrated++;
      } else {
        failed++;
      }
    } catch {
      failed++;
    }
  }

  if (migrated > 0) {
    const migrationKey = `${MIGRATION_DONE_KEY}_${userId}`;
    localStorage.setItem(migrationKey, "true");
    localStorage.removeItem(WATCHLIST_KEY);
  }

  return { success: failed === 0, migrated, failed };
}
