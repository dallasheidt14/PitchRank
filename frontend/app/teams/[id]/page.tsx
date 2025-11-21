import { TeamPageShell } from '@/components/TeamPageShell';
import { TeamPageSkeleton } from '@/components/skeletons/TeamPageSkeleton';
import { createClient } from '@supabase/supabase-js';
import { Suspense } from 'react';
import { notFound } from 'next/navigation';
import type { Metadata } from 'next';

interface TeamPageProps {
  params: Promise<{
    id: string;
  }>;
}

// ISR: Revalidate every hour
export const revalidate = 3600;

export async function generateMetadata({ params }: TeamPageProps): Promise<Metadata> {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseAnonKey) {
    return { title: 'Team | PitchRank' };
  }

  try {
    const supabase = createClient(supabaseUrl, supabaseAnonKey);
    
    // In Next.js 15, params might be a Promise - await it if needed
    const resolvedParams = await params;

    const { data: team, error } = await supabase
      .from('teams')
      .select('team_name, club_name, state_code')
      .eq('team_id_master', resolvedParams.id)
      .maybeSingle();

    if (error) {
      console.error('Error fetching team metadata:', error);
      return { title: 'Team | PitchRank' };
    }

    if (!team) {
      return { title: 'Team Not Found | PitchRank' };
    }

    return {
      title: `${team.team_name}${team.state_code ? ` (${team.state_code})` : ''} | PitchRank`,
      description: `View rankings, trajectory, momentum, and full profile for ${team.team_name}${team.club_name ? ` from ${team.club_name}` : ''}.`,
    };
  } catch (error) {
    console.error('Error in generateMetadata:', error);
    return { title: 'Team | PitchRank' };
  }
}

export default async function Page({ params }: TeamPageProps) {
  // In Next.js 16, params is a Promise - await it
  const resolvedParams = await params;

  // Check if team exists before rendering
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (supabaseUrl && supabaseAnonKey) {
    try {
      const supabase = createClient(supabaseUrl, supabaseAnonKey);

      // Validate UUID format first (basic check)
      const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
      if (!uuidRegex.test(resolvedParams.id)) {
        notFound();
      }

      const { data: team, error } = await supabase
        .from('teams')
        .select('team_id_master')
        .eq('team_id_master', resolvedParams.id)
        .maybeSingle();

      if (error) {
        console.error('Error checking team existence:', error);
        // Don't 404 on error, let client-side handle it
      } else if (!team) {
        // Team doesn't exist - show 404 page
        notFound();
      }
    } catch (error) {
      console.error('Error in team existence check:', error);
      // Don't 404 on error, let client-side handle it
    }
  }

  return (
    <Suspense fallback={<TeamPageSkeleton />}>
      <TeamPageShell id={resolvedParams.id} />
    </Suspense>
  );
}
