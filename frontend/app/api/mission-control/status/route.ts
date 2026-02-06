import { NextResponse } from 'next/server';
import { execSync } from 'child_process';
import { supabase } from '@/lib/supabaseClient';

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

const AGENTS_CONFIG: Record<string, { 
  name: string; 
  emoji: string; 
  role: string; 
  model: 'Haiku' | 'Sonnet' | 'Opus';
  description: string;
  schedule: string;
  collaborates: string[];
  spawns: string[];
}> = {
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
    description: 'Normalizes club names, team names, and merges duplicate teams. Keeps the database clean so rankings are accurate.',
    schedule: 'Sunday 7pm MT',
    collaborates: ['Ranky'],
    spawns: ['Codey'],
  },
  watchy: { 
    name: 'Watchy', 
    emoji: '👁️', 
    role: 'System Monitor', 
    model: 'Haiku',
    description: 'Daily health checks on quarantine queues, rankings freshness, and data quality. First line of defense.',
    schedule: 'Daily 8am MT',
    collaborates: [],
    spawns: ['Codey'],
  },
  compy: { 
    name: 'Compy', 
    emoji: '🧠', 
    role: 'Meta-Learning', 
    model: 'Sonnet',
    description: 'Reviews all agent sessions nightly, extracts patterns and gotchas, updates learning files. Makes every agent smarter over time.',
    schedule: 'Nightly 10:30pm MT',
    collaborates: ['All agents'],
    spawns: [],
  },
  scrappy: { 
    name: 'Scrappy', 
    emoji: '🕷️', 
    role: 'Data Acquisition', 
    model: 'Haiku',
    description: 'Monitors GitHub Actions scrapes, fetches future games for preview content. Ensures fresh data flows in.',
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
    description: 'Generates weekly movers reports and weekend previews. Creates social content with narrative commentary.',
    schedule: 'Tuesday 10am, Wednesday 11am MT',
    collaborates: ['Ranky', 'Scrappy', 'Socialy'],
    spawns: ['Codey'],
  },
  codey: { 
    name: 'Codey', 
    emoji: '💻', 
    role: 'Engineering', 
    model: 'Sonnet',
    description: 'On-demand engineer spawned by other agents to fix issues, build features, and investigate errors. Escalates to Opus for complex tasks.',
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

    const lastRun = completedTasks && completedTasks.length > 0
      ? formatRelativeTime(new Date(completedTasks[0].updated_at))
      : null;

    // Check for blocked tasks (assigned but not started)
    const { data: blockedTasks } = await supabase
      .from('agent_tasks')
      .select('title')
      .eq('assigned_agent', agentId)
      .eq('status', 'assigned')
      .order('created_at', { ascending: false })
      .limit(3);

    const blockers = blockedTasks && blockedTasks.length > 0
      ? blockedTasks.map(t => t.title)
      : [];

    return {
      status: isActive ? 'active' : blockers.length > 0 ? 'blocked' : 'idle',
      currentTask,
      lastRun,
      blockers,
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
    const output = execSync(
      'git log --oneline --format="%s|%cr|%an" -10',
      { cwd: process.cwd(), encoding: 'utf-8' }
    );
    return output.trim().split('\n').map(line => {
      const [message, time, author] = line.split('|');
      return { message, time, author };
    });
  } catch {
    return [];
  }
}

export async function GET() {
  const agents: AgentStatus[] = [];

  // Fetch live status for each agent from database
  for (const [id, config] of Object.entries(AGENTS_CONFIG)) {
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
    active: agents.filter(a => a.status === 'active').length,
    idle: agents.filter(a => a.status === 'idle').length,
    blocked: agents.filter(a => a.status === 'blocked').length,
    error: agents.filter(a => a.status === 'error').length,
  };

  // Verify blockers and alerts are always arrays
  const agentsWithDefaults = agents.map(agent => ({
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
