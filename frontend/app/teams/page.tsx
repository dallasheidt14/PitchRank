import { redirect } from 'next/navigation';

/**
 * /teams route - redirects to rankings page
 *
 * This page exists to handle Next.js RSC prefetch requests that hit /teams
 * when navigating to or refreshing on /teams/[id] pages.
 * Without this, users would see a 404 error on refresh.
 */
export default function TeamsPage() {
  redirect('/rankings');
}
