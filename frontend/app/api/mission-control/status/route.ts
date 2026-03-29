import { NextResponse } from 'next/server';
import { supabase } from '@/lib/supabaseClient';
import { requireAdmin } from '@/lib/supabase/admin';

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

const AGENTS_CONFIG: Record<
  string,
  {
    name: string;
    emoji: string;
    role: string;
    model: 'Haiku' | 'Sonnet' | 'Opus';
    description: string;
    schedule: string;
    collaborates: string[];
    spawns: string[];
  }
> = {
  orchestrator: {
    name: 'Orchestrator',
    emoji: '🎯',
    role: 'System Coordinator',
    model: 'Opus',
    description: 'Coordinates all agents, monitors system health, and makes high-level decisions.',
    schedule: 'Always on',
    collaborates: ['All agents'],
    spawns: ['Codey', 'Watchy', 'Cleany', 'Ranky', 'Movy', 'Scrappy', 'Socialy'],
  },
  cleany: {
    name: 'Cleany',
    emoji: '🧹',
    role: 'Data Hygiene',
    model: 'Haiku',
    description:
      'Normalizes club names, team names, and merges duplicate teams. Keeps the database clean so rankings are accurate.',
    schedule: 'Sunday 7pm MT',
    collaborates: ['Ranky'],
    spawns: ['Codey'],
  },
  watchy: {
    name: 'Watchy',
    emoji: '👁️',
    role: 'System Monitor',
    model: 'Haiku',
    description:
      'Daily health checks on quarantine queues, rankings freshness, and data quality. First line of defense.',
    schedule: 'Daily 8am MT',
    collaborates: [],
    spawns: ['Codey'],
  },
  compy: {
    name: 'Compy',
    emoji: '🧠',
    role: 'Meta-Learning',
    model: 'Sonnet',
    description:
      'Reviews all agent sessions nightly, extracts patterns and gotchas, updates learning files. Makes every agent smarter over time.',
    schedule: 'Nightly 10:30pm MT',
    collaborates: ['All agents'],
    spawns: [],
  },
  scrappy: {
    name: 'Scrappy',
    emoji: '🕷️',
    role: 'Data Acquisition',
    model: 'Haiku',
    description:
      'Monitors GitHub Actions scrapes, fetches future games for preview content. Ensures fresh data flows in.',
    schedule: 'Monday 10am, Wednesday 6am MT',
    collaborates: ['Ranky', 'Movy'],
    spawns: ['Codey'],
  },
  ranky: {
    name: 'Ranky',
    emoji: '📊',
    role: 'Rankings Engine',
    model: 'Haiku',
    description: 'Runs the v53e PowerScore algorithm with ML adjustments. Calculates rankings for 90k+ teams.',
    schedule: 'Monday 12pm MT',
    collaborates: ['Scrappy', 'Movy'],
    spawns: ['Codey'],
  },
  movy: {
    name: 'Movy',
    emoji: '📈',
    role: 'Content & Analytics',
    model: 'Haiku',
    description:
      'Generates weekly movers reports and weekend previews. Creates social content with narrative commentary.',
    schedule: 'Tuesday 10am, Wednesday 11am MT',
    collaborates: ['Ranky', 'Scrappy', 'Socialy'],
    spawns: ['Codey'],
  },
  codey: {
    name: 'Codey',
    emoji: '💻',
    role: 'Engineering',
    model: 'Sonnet',
    description:
      'On-demand engineer spawned by other agents to fix issues, build features, and investigate errors. Escalates to Opus for complex tasks.',
    schedule: 'On-demand',
    collaborates: ['All agents'],
    spawns: [],
  },
  socialy: {
    name: 'Socialy',
    emoji: '📱',
    role: 'SEO & Growth',
    model: 'Haiku',
    description: 'Analyzes Google Search Console data, identifies SEO opportunities, and coordinates content creation.',
    schedule: 'Wednesday 9am MT',
    collaborates: ['Movy', 'Codey'],
    spawns: ['Codey', 'Movy'],
  },
};

// Helper to format relative time
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

// Calculate next run based on schedule
function calculateNextRun(schedule: string): string | null {
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

export async function GET() {
  try {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

    const agentIds = Object.keys(AGENTS_CONFIG);

    // Batch: 2 queries instead of 27 sequential ones
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

    const agents: AgentStatus[] = agentIds.map((id) => {
      const config = AGENTS_CONFIG[id];
      const activeTask = activeTasks.find((t) => t.assigned_agent === id);
      const lastCompleted = completedTasks.find((t) => t.assigned_agent === id);

      return {
        id,
        name: config.name,
        emoji: config.emoji,
        role: config.role,
        model: config.model,
        description: config.description,
        schedule: config.schedule,
        collaborates: config.collaborates,
        spawns: config.spawns,
        status: activeTask ? ('active' as const) : ('idle' as const),
        currentTask: activeTask?.title ?? null,
        lastRun: lastCompleted ? formatRelativeTime(new Date(lastCompleted.updated_at)) : null,
        nextRun: calculateNextRun(config.schedule),
        blockers: [],
        alerts: [],
      };
    });

    const stats = {
      active: agents.filter((a) => a.status === 'active').length,
      idle: agents.filter((a) => a.status === 'idle').length,
      blocked: agents.filter((a) => a.status === 'blocked').length,
      error: agents.filter((a) => a.status === 'error').length,
    };

    return NextResponse.json({
      agents,
      commits: [],
      stats,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('[Mission Control] Error:', error);
    return NextResponse.json({ error: 'Failed to fetch mission control status' }, { status: 500 });
  }
}
