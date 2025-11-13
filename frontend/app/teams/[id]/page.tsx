import { TeamPageShell } from '@/components/TeamPageShell';
import { TeamPageSkeleton } from '@/components/skeletons/TeamPageSkeleton';
import { createClient } from '@supabase/supabase-js';
import { Suspense } from 'react';
import type { Metadata } from 'next';

interface TeamPageProps {
  params: {
    id: string;
  };
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

    const { data: team, error } = await supabase
      .from('teams')
      .select('team_name, club_name, state_code')
      .eq('team_id_master', params.id)
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

export default function Page({ params }: TeamPageProps) {
  return (
    <Suspense fallback={<TeamPageSkeleton />}>
      <TeamPageShell id={params.id} />
    </Suspense>
  );
}
