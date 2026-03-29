import { NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';
import { requireAdmin } from '@/lib/supabase/admin';

interface AgentStatusResponse {
  id: string;
  status: 'active' | 'idle' | 'error';
  currentTask: string | null;
  lastRun: string | null;
  nextRun: string | null;
}

// Agent schedules (hardcoded for nextRun calculation)
const AGENT_SCHEDULES: Record<string, string> = {
  orchestrator: 'Always on',
  codey: 'On-demand',
  watchy: 'Daily 8:00 AM MT',
  cleany: 'Sunday 7:00 PM MT',
  movy: 'Tuesday 10am, Wednesday 11am MT',
  compy: 'Nightly 10:30 PM MT',
  scrappy: 'Monday 10am, Wednesday 6am MT',
  ranky: 'Monday 12:00 PM MT',
  socialy: 'Wednesday 9:00 AM MT',
};

// Calculate relative time string (e.g., "2 minutes ago")
function formatRelativeTime(date: Date): string {
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

// Calculate next run time based on schedule
function calculateNextRun(agentId: string, schedule: string): string | null {
  // For on-demand agents, no next run
  if (schedule.toLowerCase().includes('on-demand') || schedule.toLowerCase().includes('always on')) {
    return null;
  }

  const now = new Date();

  // Simple heuristic: if it's a daily schedule, show "Tomorrow at [time]"
  if (schedule.toLowerCase().includes('daily')) {
    const timeMatch = schedule.match(/(\d+):?(\d+)?\s*(am|pm)/i);
    if (timeMatch) {
      const hour = parseInt(timeMatch[1]) + (timeMatch[3].toLowerCase() === 'pm' && timeMatch[1] !== '12' ? 12 : 0);
      return `Tomorrow at ${timeMatch[1]}:${timeMatch[2] || '00'} ${timeMatch[3].toUpperCase()}`;
    }
  }

  // For weekly schedules (like "Sunday 7pm")
  if (schedule.toLowerCase().includes('sunday')) {
    return 'Next Sunday 7:00 PM MT';
  }
  if (schedule.toLowerCase().includes('monday')) {
    return 'Next Monday';
  }
  if (schedule.toLowerCase().includes('tuesday')) {
    return 'Next Tuesday';
  }
  if (schedule.toLowerCase().includes('wednesday')) {
    return 'Next Wednesday';
  }

  // Default: just return the schedule
  return schedule;
}

export async function GET() {
  try {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

    const agentIds = Object.keys(AGENT_SCHEDULES);

    // Batch: 2 queries instead of 18
    const [activeResult, completedResult] = await Promise.all([
      supabase
        .from('agent_tasks')
        .select('assigned_agent, title, created_at')
        .in('assigned_agent', agentIds)
        .eq('status', 'in_progress')
        .order('created_at', { ascending: false }),
      supabase
        .from('agent_tasks')
        .select('assigned_agent, updated_at')
        .in('assigned_agent', agentIds)
        .in('status', ['done', 'review'])
        .order('updated_at', { ascending: false }),
    ]);

    if (activeResult.error) {
      console.error('Error querying active tasks:', activeResult.error);
    }
    if (completedResult.error) {
      console.error('Error querying completed tasks:', completedResult.error);
    }

    const activeTasks = activeResult.data ?? [];
    const completedTasks = completedResult.data ?? [];

    const agents: AgentStatusResponse[] = agentIds.map((agentId) => {
      const activeTask = activeTasks.find((t) => t.assigned_agent === agentId);
      const lastCompleted = completedTasks.find((t) => t.assigned_agent === agentId);

      const schedule = AGENT_SCHEDULES[agentId] || 'Unknown';
      return {
        id: agentId,
        status: activeTask ? ('active' as const) : ('idle' as const),
        currentTask: activeTask?.title ?? null,
        lastRun: lastCompleted ? formatRelativeTime(new Date(lastCompleted.updated_at)) : null,
        nextRun: calculateNextRun(agentId, schedule),
      };
    });

    return NextResponse.json({
      agents,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('[AgentStatus] Error:', error);
    return NextResponse.json({ error: 'Failed to fetch agent status', agents: [] }, { status: 500 });
  }
}
