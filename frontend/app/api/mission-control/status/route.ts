import { NextResponse } from 'next/server';
import { execSync } from 'child_process';
import { supabase } from '@/lib/supabaseClient';
import { requireAdmin } from '@/lib/supabase/admin';
import { AGENTS_CONFIG, AGENT_IDS } from '@/lib/agents/config';
import { formatRelativeTime, calculateNextRun } from '@/lib/agents/utils';

interface AgentStatus {
  id: string;
  name: string;
  emoji: string;
  role: string;
  model: 'Haiku' | 'Sonnet' | 'Opus';
  description: string;
  schedule: string;
  collaborates: string[];
  spawns: string[];
  status: 'active' | 'idle' | 'blocked' | 'error';
  currentTask: string | null;
  lastRun: string | null;
  nextRun: string | null;
  blockers: string[];
  alerts: string[];
}

// Fetch live status from database
async function fetchAgentLiveStatus(agentId: string): Promise<Partial<AgentStatus>> {
  try {
    // Check for active (in_progress) tasks
    const { data: activeTasks } = await supabase
      .from('agent_tasks')
      .select('*')
      .eq('assigned_agent', agentId)
      .eq('status', 'in_progress')
      .order('created_at', { ascending: false })
      .limit(1);

    const isActive = activeTasks && activeTasks.length > 0;
    const currentTask = isActive ? activeTasks[0].title : null;

    // Get last completed task for lastRun
    const { data: completedTasks } = await supabase
      .from('agent_tasks')
      .select('*')
      .eq('assigned_agent', agentId)
      .in('status', ['done', 'review'])
      .order('updated_at', { ascending: false })
      .limit(1);

    const lastRun =
      completedTasks && completedTasks.length > 0 ? formatRelativeTime(new Date(completedTasks[0].updated_at)) : null;

    // Check for blocked tasks (assigned but not started)
    const { data: blockedTasks } = await supabase
      .from('agent_tasks')
      .select('title')
      .eq('assigned_agent', agentId)
      .eq('status', 'assigned')
      .order('created_at', { ascending: false })
      .limit(3);

    // Assigned tasks are NOT blockers - they're just queued work
    // Only show as blocked if there's an actual blocker (not implemented yet)
    const assignedTasks = blockedTasks && blockedTasks.length > 0 ? blockedTasks.map((t) => t.title) : [];

    return {
      // Active if working, otherwise idle (blocked would need explicit blocker flag)
      status: isActive ? 'active' : 'idle',
      currentTask,
      lastRun,
      blockers: [], // No blockers for now - assigned tasks are just queued work
      alerts: [], // Could be populated from task comments if needed
    };
  } catch (error) {
    console.error(`Error fetching status for ${agentId}:`, error);
    return {
      status: 'error',
      currentTask: null,
      lastRun: null,
      blockers: [],
      alerts: ['Failed to fetch status'],
    };
  }
}

function getRecentCommits(): { message: string; time: string; author: string }[] {
  try {
    const output = execSync('git log --oneline --format="%s|%cr|%an" -10', { cwd: process.cwd(), encoding: 'utf-8' });
    return output
      .trim()
      .split('\n')
      .map((line) => {
        const [message, time, author] = line.split('|');
        return { message, time, author };
      });
  } catch {
    return [];
  }
}

export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const agents: AgentStatus[] = [];

  // Fetch live status for each agent from database
  for (const id of AGENT_IDS) {
    const config = AGENTS_CONFIG[id];
    const liveStatus = await fetchAgentLiveStatus(id);
    const nextRun = calculateNextRun(config.schedule);

    agents.push({
      id,
      name: config.name,
      emoji: config.emoji,
      role: config.role,
      model: config.model,
      description: config.description,
      schedule: config.schedule,
      collaborates: config.collaborates,
      spawns: config.spawns,
      status: liveStatus.status || 'idle',
      currentTask: liveStatus.currentTask || null,
      lastRun: liveStatus.lastRun || null,
      nextRun,
      blockers: liveStatus.blockers || [],
      alerts: liveStatus.alerts || [],
    });
  }

  const commits = getRecentCommits();

  const stats = {
    active: agents.filter((a) => a.status === 'active').length,
    idle: agents.filter((a) => a.status === 'idle').length,
    blocked: agents.filter((a) => a.status === 'blocked').length,
    error: agents.filter((a) => a.status === 'error').length,
  };

  // Verify blockers and alerts are always arrays
  const agentsWithDefaults = agents.map((agent) => ({
    ...agent,
    blockers: Array.isArray(agent.blockers) ? agent.blockers : [],
    alerts: Array.isArray(agent.alerts) ? agent.alerts : [],
  }));

  console.log('[Mission Control] Response agents sample:', agentsWithDefaults[0]);

  return NextResponse.json({
    agents: agentsWithDefaults,
    commits,
    stats,
    timestamp: new Date().toISOString(),
  });
}
