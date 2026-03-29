/**
 * Shared utility functions for agent status display.
 */

/** Format a date as a relative time string (e.g., "2 minutes ago") */
export function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** Calculate next run time based on a schedule string */
export function calculateNextRun(schedule: string): string | null {
  if (schedule.toLowerCase().includes('on-demand') || schedule.toLowerCase().includes('always on')) {
    return null;
  }

  if (schedule.toLowerCase().includes('daily')) {
    const timeMatch = schedule.match(/(\d+):?(\d+)?\s*(am|pm)/i);
    if (timeMatch) {
      return `Tomorrow at ${timeMatch[1]}:${timeMatch[2] || '00'} ${timeMatch[3].toUpperCase()}`;
    }
  }

  if (schedule.toLowerCase().includes('sunday')) return 'Next Sunday 7:00 PM MT';
  if (schedule.toLowerCase().includes('monday')) return 'Next Monday';
  if (schedule.toLowerCase().includes('tuesday')) return 'Next Tuesday';
  if (schedule.toLowerCase().includes('wednesday')) return 'Next Wednesday';

  return schedule;
}
