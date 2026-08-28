'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { createClientSupabase } from '@/lib/supabase/client';
import type { User, Session, AuthChangeEvent } from '@supabase/supabase-js';

export interface UserProfile {
  id: string;
  email: string | null;
  plan: 'free' | 'premium' | 'admin';
  created_at: string;
  updated_at: string;
  // Stripe subscription fields
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  subscription_status: string | null;
  subscription_period_end: string | null;
  cancel_at_period_end: boolean;
}

/**
 * Check if user has premium access (premium or admin plan)
 */
export function hasPremiumAccess(profile: UserProfile | null): boolean {
  if (!profile) return false;
  return profile.plan === 'premium' || profile.plan === 'admin';
}

/**
 * Check if user has admin access
 */
export function hasAdminAccess(profile: UserProfile | null): boolean {
  if (!profile) return false;
  return profile.plan === 'admin';
}

const PROFILE_FETCH_ATTEMPTS = 3;
const PROFILE_RETRY_BASE_MS = 300;

// PostgREST's code for "`.single()` matched no row". That is a genuine absence of
// a profile rather than a transient failure, so retrying it only delays the answer.
const NO_ROWS_ERROR_CODE = 'PGRST116';

/**
 * `failed` separates "we could not reach the profile" from "there is no profile".
 * Collapsing the two makes a paying user indistinguishable from a free one, which
 * is exactly what hasPremiumAccess would then report.
 */
interface ProfileFetchResult {
  profile: UserProfile | null;
  failed: boolean;
}

interface UseUserReturn {
  user: User | null;
  profile: UserProfile | null;
  session: Session | null;
  isLoading: boolean;
  error: Error | null;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

export function useUser(): UseUserReturn {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  // Get singleton client
  const supabase = createClientSupabase();

  const fetchProfile = useCallback(
    async (userId: string): Promise<ProfileFetchResult> => {
      for (let attempt = 1; attempt <= PROFILE_FETCH_ATTEMPTS; attempt++) {
        try {
          const { data, error: profileError } = await supabase
            .from('user_profiles')
            .select('*')
            .eq('id', userId)
            .single();

          if (!profileError) {
            return { profile: data as UserProfile, failed: false };
          }
          if (profileError.code === NO_ROWS_ERROR_CODE) {
            return { profile: null, failed: false };
          }
          console.warn(`Error fetching profile (attempt ${attempt}):`, profileError.message);
        } catch (e) {
          console.warn(`Profile fetch error (attempt ${attempt}):`, e);
        }

        if (attempt < PROFILE_FETCH_ATTEMPTS) {
          await new Promise((resolve) => setTimeout(resolve, PROFILE_RETRY_BASE_MS * attempt));
        }
      }

      return { profile: null, failed: true };
    },
    [supabase]
  );

  // A retained profile is only valid for the user it was fetched for. Holding it
  // across an account switch would hand the incoming user the previous plan.
  const markProfileUnavailable = useCallback((userId: string) => {
    setError(new Error('Could not load your subscription details'));
    setProfile((current) => (current?.id === userId ? current : null));
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const {
        data: { user: currentUser },
        error: userError,
      } = await supabase.auth.getUser();

      if (userError) {
        if (userError.name !== 'AuthSessionMissingError') {
          console.warn('Auth error:', userError.message);
        }
        setUser(null);
        setProfile(null);
        setError(userError instanceof Error ? userError : new Error('Failed to refresh user'));
        return;
      }

      setUser(currentUser);
      if (currentUser) {
        const { profile: userProfile, failed } = await fetchProfile(currentUser.id);
        if (failed) {
          markProfileUnavailable(currentUser.id);
        } else {
          setProfile(userProfile);
        }
      } else {
        setProfile(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e : new Error('Unknown error'));
    } finally {
      setIsLoading(false);
    }
  }, [supabase, fetchProfile, markProfileUnavailable]);

  const signOut = useCallback(async () => {
    try {
      const { error: signOutError } = await supabase.auth.signOut();
      if (signOutError) throw signOutError;
      setUser(null);
      setProfile(null);
      setSession(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error('Sign out failed'));
      throw e;
    }
  }, [supabase]);

  useEffect(() => {
    let isInitialized = false;
    let isMounted = true;

    // Get initial session and profile
    const initializeUser = async () => {
      console.log('[useUser] Starting initialization...');
      try {
        const {
          data: { session: currentSession },
          error: sessionError,
        } = await supabase.auth.getSession();
        console.log('[useUser] Session result:', {
          hasSession: !!currentSession,
          userId: currentSession?.user?.id,
          error: sessionError?.message,
        });

        if (!isMounted) return;

        setSession(currentSession);
        setUser(currentSession?.user ?? null);

        if (currentSession?.user) {
          // Wait for profile to load before setting isLoading to false
          console.log('[useUser] Fetching profile for user:', currentSession.user.id);
          const { profile: userProfile, failed } = await fetchProfile(currentSession.user.id);
          console.log('[useUser] Profile result:', failed ? 'fetch failed' : (userProfile?.plan ?? null));
          if (isMounted) {
            if (failed) {
              markProfileUnavailable(currentSession.user.id);
            } else {
              setProfile(userProfile);
            }
          }
        } else {
          console.log('[useUser] No session, skipping profile fetch');
          if (isMounted) {
            setProfile(null);
          }
        }
      } catch (e) {
        console.error('[useUser] Error initializing user:', e);
        if (isMounted) {
          setError(e instanceof Error ? e : new Error('Failed to initialize user'));
        }
      } finally {
        if (isMounted) {
          console.log('[useUser] Initialization complete, setting isLoading to false');
          setIsLoading(false);
          isInitialized = true;
        }
      }
    };

    initializeUser();

    // Listen for auth changes - but only process updates after initial load completes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (event: AuthChangeEvent, currentSession: Session | null) => {
      // When a recovery token is exchanged via PKCE, Supabase fires PASSWORD_RECOVERY.
      // The server-side callback may have lost the ?next=/reset-password param during
      // the redirect chain, so we catch it here and redirect to the reset page.
      // This must run before the isInitialized check so it's never skipped.
      if (event === 'PASSWORD_RECOVERY' && isMounted) {
        router.push('/reset-password');
        return;
      }

      // Skip processing auth changes until initial load is complete to avoid race conditions
      if (!isInitialized) {
        console.log('[useUser] Skipping auth state change - initial load not complete:', event);
        return;
      }

      console.log('Auth state changed:', event);
      if (!isMounted) return;

      setSession(currentSession);
      setUser(currentSession?.user ?? null);

      if (currentSession?.user) {
        const { profile: userProfile, failed } = await fetchProfile(currentSession.user.id);
        if (isMounted) {
          if (failed) {
            markProfileUnavailable(currentSession.user.id);
          } else {
            setProfile(userProfile);
          }
        }
      } else {
        if (isMounted) {
          setProfile(null);
        }
      }
    });

    return () => {
      isMounted = false;
      subscription.unsubscribe();
    };
  }, [supabase, fetchProfile, router, markProfileUnavailable]);

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
