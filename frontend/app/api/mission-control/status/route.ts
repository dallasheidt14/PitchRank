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
  status: 'active' | 'idle' | 'blocked' | 'error';
  currentTask: string | null;
  lastRun: string | null;
  nextRun: string | null;
  blockers: string[];
  alerts: string[];
}

const AGENTS_CONFIG: Record<string, { name: string; emoji: string; role: string; model: 'Haiku' | 'Sonnet' | 'Opus' }> = {
  cleany: { name: 'Cleany', emoji: '🧹', role: 'Data Hygiene', model: 'Haiku' },
  watchy: { name: 'Watchy', emoji: '👁️', role: 'Monitoring', model: 'Haiku' },
  compy: { name: 'Compy', emoji: '🧠', role: 'Meta-Learning', model: 'Sonnet' },
  scrappy: { name: 'Scrappy', emoji: '🕷️', role: 'Data Acquisition', model: 'Haiku' },
  ranky: { name: 'Ranky', emoji: '📊', role: 'Rankings Engine', model: 'Haiku' },
  movy: { name: 'Movy', emoji: '📈', role: 'Content & Analytics', model: 'Haiku' },
  codey: { name: 'Codey', emoji: '💻', role: 'Engineering', model: 'Sonnet' },
  socialy: { name: 'Socialy', emoji: '📱', role: 'SEO & Content', model: 'Haiku' },
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
