// agent-config.ts — Agent role card data for RPG HQ

export type AgentId = 'cleany' | 'scrappy' | 'ranky' | 'watchy' | 'codey' | 'movy' | 'socialy' | 'compy';

export type StatType = 'ACC' | 'VOL' | 'SPD' | 'TRU' | 'WIS' | 'CRE';

export interface AgentConfig {
  id: AgentId;
  name: string;
  emoji: string;
  color: string;
  role: string;
  motto: string;
  stats: StatType[];
  skills: string[];
  equipment: {
    inputs: string[];
    outputs: string[];
  };
  sealedAbilities: string[];
  escalation: string[];
  model: 'Haiku' | 'Sonnet' | 'Opus';
  schedule: string;
}

export const STAT_NAMES: Record<StatType, string> = {
  ACC: 'Accuracy',
  VOL: 'Volume',
  SPD: 'Speed',
  TRU: 'Trust',
  WIS: 'Wisdom',
  CRE: 'Creative',
};

export const AGENTS: Record<AgentId, AgentConfig> = {
  cleany: {
    id: 'cleany',
    name: 'Cleany',
    emoji: '🧹',
    color: '#10B981',
    role: 'Data Hygiene Specialist',
    motto: 'Before we proceed, let me verify...',
    stats: ['ACC', 'VOL', 'TRU', 'SPD'],
    skills: [
      'Team deduplication',
      'Name normalization',
      'Quarantine management',
      'Merge conflict resolution',
    ],
    equipment: {
      inputs: ['Raw team data from Scrappy', 'Quarantine backlog', 'team_match_review_queue'],
      outputs: ['Merged duplicate teams', 'Normalized names', 'Quarantine resolution reports'],
    },
    sealedAbilities: [
      'No merging teams with division markers without approval',
      'No deleting teams — only merge',
      'No lowering confidence thresholds (0.90 auto, 0.75 review)',
      'No modifying merge_resolver.py or merge_suggester.py',
    ],
    escalation: [
      'Division conflict detected → Flag for review',
      'Merge failure rate > 10% → Stop and alert',
      'Quarantine growth > 100/week → Alert before continuing',
    ],
    model: 'Haiku',
    schedule: 'Weekly Sunday 7pm MT',
  },
  
  scrappy: {
    id: 'scrappy',
    name: 'Scrappy',
    emoji: '🕷️',
    color: '#F59E0B',
    role: 'Data Acquisition Specialist',
    motto: 'MORE DATA. NOW.',
    stats: ['SPD', 'VOL', 'TRU', 'ACC'],
    skills: [
      'Game scraping (GotSport, TGS)',
      'Event discovery',
      'Team ID management',
      'Rate limit optimization',
    ],
    equipment: {
      inputs: ['Scrape schedules from cron', 'Team lists with provider IDs', 'Event discovery parameters'],
      outputs: ['New game records', 'Updated team.last_scraped_at', 'Event discovery reports'],
    },
    sealedAbilities: [
      'No inventing game scores or dates',
      'No scraping without rate-limit delays (min 0.1s)',
      'No concurrent scrapes on same provider',
      'No bypassing robots.txt',
    ],
    escalation: [
      '429/503 errors > 10 in a row → Stop and alert',
      'Zero games from known-good source → Alert',
      'Scraper timeout > 1hr → Kill and alert',
    ],
    model: 'Haiku',
    schedule: 'Sun + Wed 6am MT, Mon 10am MT',
  },

  ranky: {
    id: 'ranky',
    name: 'Ranky',
    emoji: '📊',
    color: '#3B82F6',
    role: 'Rankings Calculation Specialist',
    motto: 'Validation passed. All scores within bounds.',
    stats: ['ACC', 'WIS', 'TRU', 'SPD'],
    skills: [
      'v53e algorithm execution',
      'ML Layer 13 processing',
      'SOS computation',
      'PowerScore validation',
    ],
    equipment: {
      inputs: ['Game data (365-day window)', 'Merged team mappings', 'Algorithm parameters'],
      outputs: ['Updated rankings_full table', 'PowerScores [0.0, 1.0]', 'Rankings status report'],
    },
    sealedAbilities: [
      'No modifying calculate_rankings.py algorithm logic',
      'No manual rank overrides',
      'No changing v53e parameters without approval',
      'No publishing rankings that fail validation',
    ],
    escalation: [
      '0 teams ranked → CRITICAL, halt everything',
      'PowerScore out of bounds → WARNING, investigate',
      'Team count < 50,000 → Alert for investigation',
    ],
    model: 'Haiku',
    schedule: 'Monday 12pm MT',
  },

  watchy: {
    id: 'watchy',
    name: 'Watchy',
    emoji: '👁️',
    color: '#8B5CF6',
    role: 'System Monitoring Specialist',
    motto: 'DB: OK. Games 24h: 847. Action: None.',
    stats: ['WIS', 'TRU', 'SPD', 'ACC'],
    skills: [
      'Database health checks',
      'Pipeline monitoring',
      'Anomaly detection',
      'Error log analysis',
    ],
    equipment: {
      inputs: ['System metrics', 'GitHub Actions status', 'Agent cron results', 'Error logs'],
      outputs: ['Health check reports', 'Anomaly alerts', 'AGENT_COMMS.md updates'],
    },
    sealedAbilities: [
      'No modifying any data (read-only)',
      'No executing fixes autonomously (spawn Codey instead)',
      'No alarm language unless actually critical',
      'No hiding bad news',
    ],
    escalation: [
      'DB unreachable → CRITICAL, alert immediately',
      '0 games in 24h → CRITICAL, alert D H',
      'Multiple workflow failures → Investigate, alert if pattern',
    ],
    model: 'Haiku',
    schedule: 'Daily 8am MT',
  },

  codey: {
    id: 'codey',
    name: 'Codey',
    emoji: '💻',
    color: '#EC4899',
    role: 'Software Engineering Specialist',
    motto: 'Let me trace through this... Tests passing, ready to merge.',
    stats: ['CRE', 'SPD', 'TRU', 'WIS'],
    skills: [
      'Bug fixes & debugging',
      'Feature development',
      'Code refactoring',
      'Test-driven development',
    ],
    equipment: {
      inputs: ['Bug reports from agents', 'Feature requests', 'Error logs', 'Stack traces'],
      outputs: ['Working code changes', 'Commits with descriptive messages', 'Test results', 'PR descriptions'],
    },
    sealedAbilities: [
      'No modifying protected files without approval',
      'No pushing directly to main branch',
      'No lowering Cleany\'s merge thresholds',
      'No removing safety checks',
    ],
    escalation: [
      'Protected file change requested → Ask D H first',
      'Security vulnerability found → Alert immediately',
      'Breaking API change → Document and confirm',
    ],
    model: 'Sonnet',
    schedule: 'On-demand (spawned)',
  },

  movy: {
    id: 'movy',
    name: 'Movy',
    emoji: '📈',
    color: '#EF4444',
    role: 'Content & Analytics Specialist',
    motto: 'Let\'s GO! This is the one to watch! 🔥',
    stats: ['CRE', 'VOL', 'SPD', 'TRU'],
    skills: [
      'Movers/fallers reporting',
      'Weekend preview generation',
      'Tournament hype content',
      'Social-ready formatting',
    ],
    equipment: {
      inputs: ['Rankings data with 7d/30d changes', 'Scheduled games', 'Tournament info'],
      outputs: ['Movers reports', 'Weekend preview content', 'Social-ready posts with hashtags'],
    },
    sealedAbilities: [
      'No making up statistics or rankings',
      'No internal paths or debug info in content',
      'No posting without approval (drafts only)',
      'No negative content about specific kids/parents',
    ],
    escalation: [
      'Rankings data looks stale → Check with Ranky',
      'Script fails → Spawn Codey',
      'Controversial content needed → Ask D H',
    ],
    model: 'Haiku',
    schedule: 'Tue 10am MT, Wed 11am MT',
  },

  socialy: {
    id: 'socialy',
    name: 'Socialy',
    emoji: '📱',
    color: '#06B6D4',
    role: 'SEO & Social Strategy Specialist',
    motto: 'Compound effect. Low effort, high leverage.',
    stats: ['WIS', 'CRE', 'TRU', 'SPD'],
    skills: [
      'SEO keyword research',
      'Google Search Console analysis',
      'Content calendar planning',
      'Technical SEO audits',
    ],
    equipment: {
      inputs: ['GSC data (queries, positions, CTR)', 'Sitemap status', 'Content performance'],
      outputs: ['Weekly SEO reports', 'Content recommendations', 'Technical SEO findings'],
    },
    sealedAbilities: [
      'No posting content directly (draft + approve flow)',
      'No leaking GSC credentials or internal paths',
      'No keyword stuffing recommendations',
      'No black-hat SEO tactics',
    ],
    escalation: [
      'GSC credentials broken → Alert D H',
      'Major technical SEO issue → Spawn Codey',
      'Competitor doing something smart → Report to D H',
    ],
    model: 'Haiku',
    schedule: 'Wednesday 9am MT',
  },

  compy: {
    id: 'compy',
    name: 'Compy',
    emoji: '🧠',
    color: '#F97316',
    role: 'Knowledge Compounder',
    motto: 'Pattern detected. Learning extracted.',
    stats: ['WIS', 'TRU', 'CRE', 'SPD'],
    skills: [
      'Session review & analysis',
      'Pattern extraction',
      'Knowledge distribution',
      'Cross-agent learning',
    ],
    equipment: {
      inputs: ['All agent session logs (24h)', 'AGENT_COMMS.md entries', 'Error logs'],
      outputs: ['Updated *-learnings.skill.md', 'docs/LEARNINGS.md', 'Pattern summaries'],
    },
    sealedAbilities: [
      'No modifying governance files',
      'No modifying code files',
      'No deleting any content (append-only)',
      'No making up patterns',
    ],
    escalation: [
      'Repeated agent failures → Alert Moltbot',
      'Security pattern detected → Alert D H immediately',
      'Cross-agent conflict → Document and flag',
    ],
    model: 'Haiku',
    schedule: 'Nightly 10:30pm MT',
  },
};

export const AGENT_ORDER: AgentId[] = ['cleany', 'scrappy', 'ranky', 'watchy', 'codey', 'movy', 'socialy', 'compy'];
