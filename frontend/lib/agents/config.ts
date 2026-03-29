/**
 * Operational agent configuration for status and mission-control routes.
 * For RPG card data (stats, skills, equipment), see lib/agent-config.ts.
 */

export interface AgentOperationalConfig {
  name: string;
  emoji: string;
  role: string;
  model: 'Haiku' | 'Sonnet' | 'Opus';
  description: string;
  schedule: string;
  collaborates: string[];
  spawns: string[];
}

export const AGENTS_CONFIG: Record<string, AgentOperationalConfig> = {
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

/** Agent IDs in display order */
export const AGENT_IDS = Object.keys(AGENTS_CONFIG);
