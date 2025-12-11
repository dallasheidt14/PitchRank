"use client";

import { useEffect, useState, useCallback } from "react";
import { createClientSupabase } from "@/lib/supabase/client";
import type { User, Session, AuthChangeEvent } from "@supabase/supabase-js";

export interface UserProfile {
  id: string;
  email: string | null;
  plan: "free" | "premium" | "admin";
  created_at: string;
  updated_at: string;
  // Stripe subscription fields
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  subscription_status: string | null;
  subscription_period_end: string | null;
}

/**
 * Check if user has premium access (premium or admin plan)
 */
export function hasPremiumAccess(profile: UserProfile | null): boolean {
  if (!profile) return false;
  return profile.plan === "premium" || profile.plan === "admin";
}

/**
 * Check if subscription is active
 */
export function isSubscriptionActive(profile: UserProfile | null): boolean {
  if (!profile) return false;
  return (
    profile.subscription_status === "active" ||
    profile.subscription_status === "trialing" ||
    profile.plan === "admin"
  );
}

export interface UseUserReturn {
  user: User | null;
  profile: UserProfile | null;
  session: Session | null;
  isLoading: boolean;
  error: Error | null;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

export function useUser(): UseUserReturn {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  // Get singleton client
  const supabase = createClientSupabase();

  const fetchProfile = useCallback(async (userId: string) => {
    try {
      const { data, error: profileError } = await supabase
        .from("user_profiles")
        .select("*")
        .eq("id", userId)
        .single();

      if (profileError) {
        console.warn("Error fetching profile:", profileError.message);
        return null;
      }
      return data as UserProfile;
    } catch (e) {
      console.warn("Profile fetch error:", e);
      return null;
    }
  }, [supabase]);

  const refreshUser = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const { data: { user: currentUser }, error: userError } = await supabase.auth.getUser();

      if (userError) {
        if (userError.name !== "AuthSessionMissingError") {
          console.warn("Auth error:", userError.message);
        }
        setUser(null);
        setProfile(null);
        setError(userError instanceof Error ? userError : new Error("Failed to refresh user"));
        return;
      }

      setUser(currentUser);
      if (currentUser) {
        const userProfile = await fetchProfile(currentUser.id);
        setProfile(userProfile);
      } else {
        setProfile(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Unknown error"));
    } finally {
      setIsLoading(false);
    }
  }, [supabase, fetchProfile]);

  const signOut = useCallback(async () => {
    try {
      const { error: signOutError } = await supabase.auth.signOut();
      if (signOutError) throw signOutError;
      setUser(null);
      setProfile(null);
      setSession(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Sign out failed"));
      throw e;
    }
  }, [supabase]);

  useEffect(() => {
    let isInitialized = false;
    let isMounted = true;

    // Get initial session and profile
    const initializeUser = async () => {
      console.log("[useUser] Starting initialization...");
      try {
        const { data: { session: currentSession }, error: sessionError } = await supabase.auth.getSession();
        console.log("[useUser] Session result:", {
          hasSession: !!currentSession,
          userId: currentSession?.user?.id,
          error: sessionError?.message,
        });

        if (!isMounted) return;

        setSession(currentSession);
        setUser(currentSession?.user ?? null);

        if (currentSession?.user) {
          // Wait for profile to load before setting isLoading to false
          console.log("[useUser] Fetching profile for user:", currentSession.user.id);
          const userProfile = await fetchProfile(currentSession.user.id);
          console.log("[useUser] Profile result:", userProfile ? { plan: userProfile.plan } : null);
          if (isMounted) {
            setProfile(userProfile);
          }
        } else {
          console.log("[useUser] No session, skipping profile fetch");
          if (isMounted) {
            setProfile(null);
          }
        }
      } catch (e) {
        console.error("[useUser] Error initializing user:", e);
        if (isMounted) {
          setError(e instanceof Error ? e : new Error("Failed to initialize user"));
        }
      } finally {
        if (isMounted) {
          console.log("[useUser] Initialization complete, setting isLoading to false");
          setIsLoading(false);
          isInitialized = true;
        }
      }
    };

    initializeUser();

    // Listen for auth changes - but only process updates after initial load completes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event: AuthChangeEvent, currentSession: Session | null) => {
        // Skip processing auth changes until initial load is complete to avoid race conditions
        if (!isInitialized) {
          console.log("[useUser] Skipping auth state change - initial load not complete:", event);
          return;
        }

        console.log("Auth state changed:", event);
        if (!isMounted) return;

        setSession(currentSession);
        setUser(currentSession?.user ?? null);

        if (currentSession?.user) {
          const userProfile = await fetchProfile(currentSession.user.id);
          if (isMounted) {
            setProfile(userProfile);
          }
        } else {
          if (isMounted) {
            setProfile(null);
          }
        }
      }
    );

    return () => {
      isMounted = false;
      subscription.unsubscribe();
    };
  }, [supabase, fetchProfile]);

  return {
    user,
    profile,
    session,
    isLoading,
    error,
    signOut,
    refreshUser,
  };
}
