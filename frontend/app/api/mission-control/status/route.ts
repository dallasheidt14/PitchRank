import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';

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

function parseWorkingFile(content: string): Partial<AgentStatus> {
  const lines = content.split('\n');
  const result: Partial<AgentStatus> = {
    blockers: [],
    alerts: [],
  };

  let currentSection = '';
  
  for (const line of lines) {
    const trimmed = line.trim();
    
    if (trimmed.startsWith('## ')) {
      currentSection = trimmed.slice(3).toLowerCase();
      continue;
    }

    if (currentSection === 'status' && trimmed && !trimmed.startsWith('#')) {
      const statusLower = trimmed.toLowerCase();
      if (statusLower.includes('active') || statusLower.includes('running')) {
        result.status = 'active';
      } else if (statusLower.includes('blocked')) {
        result.status = 'blocked';
      } else if (statusLower.includes('error')) {
        result.status = 'error';
      } else {
        result.status = 'idle';
      }
    }

    if (currentSection === 'current task' && trimmed && !trimmed.startsWith('#')) {
      if (trimmed.toLowerCase() !== 'none') {
        result.currentTask = trimmed;
      }
    }

    if (currentSection === 'last run' && trimmed && !trimmed.startsWith('#')) {
      result.lastRun = trimmed;
    }

    if (currentSection === 'next run' && trimmed && !trimmed.startsWith('#')) {
      result.nextRun = trimmed;
    }

    if (currentSection === 'blockers' && trimmed.startsWith('- ')) {
      const blocker = trimmed.slice(2);
      if (blocker.toLowerCase() !== 'none') {
        result.blockers?.push(blocker);
      }
    }

    if (currentSection === 'alerts' && trimmed.startsWith('- ')) {
      result.alerts?.push(trimmed.slice(2));
    }
  }

  return result;
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
  const memoryDir = path.join(process.cwd(), '..', 'memory');
  const agents: AgentStatus[] = [];

  for (const [id, config] of Object.entries(AGENTS_CONFIG)) {
    const filePath = path.join(memoryDir, `WORKING-${id}.md`);
    let parsed: Partial<AgentStatus> = {};

    try {
      if (fs.existsSync(filePath)) {
        const content = fs.readFileSync(filePath, 'utf-8');
        parsed = parseWorkingFile(content);
      }
    } catch (e) {
      console.error(`Error reading ${filePath}:`, e);
    }

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
      status: parsed.status || 'idle',
      currentTask: parsed.currentTask || null,
      lastRun: parsed.lastRun || null,
      nextRun: parsed.nextRun || null,
      blockers: parsed.blockers || [],
      alerts: parsed.alerts || [],
    });
  }

  const commits = getRecentCommits();

  const stats = {
    active: agents.filter(a => a.status === 'active').length,
    idle: agents.filter(a => a.status === 'idle').length,
    blocked: agents.filter(a => a.status === 'blocked').length,
    error: agents.filter(a => a.status === 'error').length,
  };

  return NextResponse.json({
    agents,
    commits,
    stats,
    timestamp: new Date().toISOString(),
  });
}
