import { NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';
import { AGENTS_CONFIG } from '@/lib/agents/config';
import { formatRelativeTime, calculateNextRun } from '@/lib/agents/utils';

interface AgentStatusResponse {
  id: string;
  status: 'active' | 'idle' | 'error';
  currentTask: string | null;
  lastRun: string | null;
  nextRun: string | null;
}

export async function GET() {
  try {
    const agentIds = Object.keys(AGENTS_CONFIG);

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

      const schedule = AGENTS_CONFIG[agentId]?.schedule || 'Unknown';
      return {
        id: agentId,
        status: activeTask ? ('active' as const) : ('idle' as const),
        currentTask: activeTask?.title ?? null,
        lastRun: lastCompleted ? formatRelativeTime(new Date(lastCompleted.updated_at)) : null,
        nextRun: calculateNextRun(schedule),
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
