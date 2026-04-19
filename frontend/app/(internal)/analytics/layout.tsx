import { redirect } from 'next/navigation';
import { createServerSupabase } from '@/lib/supabase/server';
import type { ReactNode } from 'react';
import { DataProviders } from '@/app/data-providers';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export default async function AnalyticsLayout({ children }: { children: ReactNode }) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect('/login?next=/analytics');

  const { data: profile } = await supabase.from('user_profiles').select('plan').eq('id', user.id).single();

  if (!profile || profile.plan !== 'admin') redirect('/');

  return (
    <DataProviders>
      <div className="min-h-screen bg-background">
        <div className="container mx-auto px-4 py-6">{children}</div>
      </div>
    </DataProviders>
  );
}
