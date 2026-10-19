import Link from 'next/link';
import { CleanupReview } from '@/components/mission-control/cleanup/CleanupReview';

// Admin gate is enforced by frontend/middleware.ts (ADMIN_ROUTES), and by requireAdmin on every route it calls.
export const metadata = { title: 'Team cleanup', robots: { index: false, follow: false } };

export default function TeamCleanupPage() {
  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <Link href="/mission-control" className="hover:text-foreground">
            Mission Control
          </Link>
          <span>/</span>
          <span>Team cleanup</span>
        </div>
        <h1 className="font-display text-3xl font-bold tracking-tight">Team cleanup review</h1>
        <CleanupReview />
      </div>
    </div>
  );
}
