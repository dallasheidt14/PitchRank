"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createClientSupabase, isSupabaseConfigured } from "@/lib/supabase/client";
import type { User, Session, AuthChangeEvent } from "@supabase/supabase-js";

export interface UserProfile {
  id: string;
  email: string | null;
  plan: "free" | "premium" | "admin";
  created_at: string;
  updated_at: string;
}

export interface UseUserReturn {
  user: User | null;
  profile: UserProfile | null;
  session: Session | null;
  isLoading: boolean;
  error: Error | null;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
  isConfigured: boolean;
}

export function useUser(): UseUserReturn {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  // Check if Supabase is configured
  const isConfigured = useMemo(() => isSupabaseConfigured(), []);

  // Get singleton client (may be null if not configured)
  const supabase = useMemo(() => createClientSupabase(), []);

  const fetchProfile = useCallback(async (userId: string) => {
    if (!supabase) return null;
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
    if (!supabase) {
      setIsLoading(false);
      return;
    }
    try {
      setIsLoading(true);
      const { data: { user: currentUser }, error: userError } = await supabase.auth.getUser();

      if (userError) {
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
      }
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Unknown error"));
    } finally {
      setIsLoading(false);
    }
  }, [supabase, fetchProfile]);

  const signOut = useCallback(async () => {
    if (!supabase) return;
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
    // Skip auth initialization if Supabase is not configured
    if (!supabase) {
      setIsLoading(false);
      return;
    }

    // Get initial session
    supabase.auth.getSession().then(({ data: { session: currentSession } }) => {
      setSession(currentSession);
      setUser(currentSession?.user ?? null);

      if (currentSession?.user) {
        fetchProfile(currentSession.user.id).then(setProfile);
      }
      setIsLoading(false);
    });

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event: AuthChangeEvent, currentSession: Session | null) => {
        console.log("Auth state changed:", event);
        setSession(currentSession);
        setUser(currentSession?.user ?? null);

        if (currentSession?.user) {
          const userProfile = await fetchProfile(currentSession.user.id);
          setProfile(userProfile);
        } else {
          setProfile(null);
        }
      }
    );

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
    isConfigured,
  };
}
