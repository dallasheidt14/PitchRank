"use client";

import { useEffect, useState, useCallback } from "react";
import { createClientSupabase } from "@/lib/supabase/client";
import type { User, Session } from "@supabase/supabase-js";

/**
 * User profile from user_profiles table
 */
export interface UserProfile {
  id: string;
  email: string | null;
  plan: "free" | "premium" | "admin";
  created_at: string;
  updated_at: string;
}

/**
 * Hook return type
 */
export interface UseUserReturn {
  user: User | null;
  profile: UserProfile | null;
  session: Session | null;
  isLoading: boolean;
  error: Error | null;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

/**
 * Client-side hook to get the current authenticated user
 */
export function useUser(): UseUserReturn {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  // Create supabase client once
  const [supabase] = useState(() => createClientSupabase());

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

      // Use getUser() which validates with the server
      const { data: { user: currentUser }, error: userError } = await supabase.auth.getUser();

      if (userError) {
        // AuthSessionMissingError is expected when not logged in
        if (userError.name !== "AuthSessionMissingError") {
          console.warn("Auth error:", userError.message);
        }
        setUser(null);
        setProfile(null);
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
      setUser(null);
      setProfile(null);
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
    // Get initial user (validates with server)
    const initAuth = async () => {
      try {
        // First try getUser which validates with server
        const { data: { user: currentUser }, error: userError } = await supabase.auth.getUser();

        if (userError) {
          // Not logged in or session invalid
          if (userError.name !== "AuthSessionMissingError") {
            console.warn("Initial auth error:", userError.message);
          }
          setUser(null);
          setProfile(null);
          setIsLoading(false);
          return;
        }

        setUser(currentUser);

        // Also get session for completeness
        const { data: { session: currentSession } } = await supabase.auth.getSession();
        setSession(currentSession);

        if (currentUser) {
          const userProfile = await fetchProfile(currentUser.id);
          setProfile(userProfile);
        }
      } catch (e) {
        console.error("Auth initialization error:", e);
        setError(e instanceof Error ? e : new Error("Auth initialization failed"));
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, currentSession) => {
      console.log("Auth state changed:", event);

      setSession(currentSession);
      setUser(currentSession?.user ?? null);

      if (currentSession?.user) {
        const userProfile = await fetchProfile(currentSession.user.id);
        setProfile(userProfile);
      } else {
        setProfile(null);
      }
    });

    return () => {
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
