'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  RefreshCw,
  Brain,
  Eye,
  Code,
  Sparkles,
  TrendingUp,
  Zap,
  Share2,
  AlertCircle,
  CheckCircle2,
  Clock,
  Pause,
  GitCommit,
} from 'lucide-react';
import { AgentCommsFeed } from '@/components/agent-comms-feed';

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

interface Commit {
  message: string;
  time: string;
  author: string;
}

interface DashboardData {
  agents: AgentStatus[];
  commits: Commit[];
  stats: {
    active: number;
    idle: number;
    blocked: number;
    error: number;
  };
  timestamp: string;
}

const AGENT_ICONS: Record<string, React.ElementType> = {
  cleany: Sparkles,
  watchy: Eye,
  compy: Brain,
  scrappy: Zap,
  ranky: TrendingUp,
  movy: TrendingUp,
  codey: Code,
  socialy: Share2,
};

const STATUS_CONFIG = {
  active: { color: 'bg-green-500', icon: CheckCircle2, label: 'Active' },
  idle: { color: 'bg-gray-400', icon: Pause, label: 'Idle' },
  blocked: { color: 'bg-yellow-500', icon: AlertCircle, label: 'Blocked' },
  error: { color: 'bg-red-500', icon: AlertCircle, label: 'Error' },
};

const MODEL_COLORS = {
  Haiku: 'bg-blue-100 text-blue-800',
  Sonnet: 'bg-purple-100 text-purple-800',
  Opus: 'bg-orange-100 text-orange-800',
};

function AgentCard({ agent }: { agent: AgentStatus }) {
  const Icon = AGENT_ICONS[agent.id] || Brain;
  const statusConfig = STATUS_CONFIG[agent.status];
  const StatusIcon = statusConfig.icon;
  const [expanded, setExpanded] = useState(false);

  return (
    <Card className="relative overflow-hidden">
      <div className={`absolute top-0 left-0 w-1 h-full ${statusConfig.color}`} />
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-2xl">{agent.emoji}</span>
            <div>
              <CardTitle className="text-lg">{agent.name}</CardTitle>
              <CardDescription>{agent.role}</CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge className={MODEL_COLORS[agent.model]}>{agent.model}</Badge>
            <Badge variant="outline" className="flex items-center gap-1">
              <StatusIcon className="h-3 w-3" />
              {statusConfig.label}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {/* Description */}
        <p className="text-sm text-muted-foreground">{agent.description}</p>
        
        {/* Schedule */}
        <div className="text-sm flex items-center gap-1">
          <Clock className="h-3 w-3 text-muted-foreground" />
          <span className="text-muted-foreground">{agent.schedule}</span>
        </div>

        {/* Current task if active */}
        {agent.currentTask && (
          <div className="text-sm bg-green-50 dark:bg-green-950 p-2 rounded">
            <span className="font-medium text-green-700 dark:text-green-300">Running:</span> {agent.currentTask}
          </div>
        )}

        {/* Expandable details */}
        <button 
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-blue-600 hover:underline"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>

        {expanded && (
          <div className="space-y-2 pt-2 border-t">
            {/* Relationships */}
            {agent.collaborates.length > 0 && (
              <div className="text-sm">
                <span className="font-medium">Works with:</span>{' '}
                <span className="text-muted-foreground">{agent.collaborates.join(', ')}</span>
              </div>
            )}
            {agent.spawns.length > 0 && (
              <div className="text-sm">
                <span className="font-medium">Can spawn:</span>{' '}
                <span className="text-muted-foreground">{agent.spawns.join(', ')}</span>
              </div>
            )}

            {/* Last/Next run */}
            {agent.lastRun && (
              <div className="text-sm text-muted-foreground">
                <span className="font-medium">Last run:</span> {agent.lastRun}
              </div>
            )}
            {agent.nextRun && (
              <div className="text-sm text-muted-foreground">
                <span className="font-medium">Next run:</span> {agent.nextRun}
              </div>
            )}
          </div>
        )}

        {/* Alerts */}
        {agent.alerts && agent.alerts.length > 0 && (
          <div className="mt-2 space-y-1">
            {agent.alerts.map((alert, i) => (
              <div key={i} className="text-sm text-yellow-600 dark:text-yellow-400 flex items-center gap-1">
                <AlertCircle className="h-3 w-3" />
                {alert}
              </div>
            ))}
          </div>
        )}

        {/* Blockers */}
        {agent.blockers && agent.blockers.length > 0 && (
          <div className="mt-2 space-y-1">
            {agent.blockers.map((blocker, i) => (
              <div key={i} className="text-sm text-red-600 dark:text-red-400 flex items-center gap-1">
                <AlertCircle className="h-3 w-3" />
                {blocker}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatsCard({ stats }: { stats: DashboardData['stats'] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg">Agent Status</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-4 gap-4 text-center">
          <div>
            <div className="text-2xl font-bold text-green-600">{stats.active}</div>
            <div className="text-xs text-muted-foreground">Active</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-gray-500">{stats.idle}</div>
            <div className="text-xs text-muted-foreground">Idle</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-yellow-600">{stats.blocked}</div>
            <div className="text-xs text-muted-foreground">Blocked</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-red-600">{stats.error}</div>
            <div className="text-xs text-muted-foreground">Error</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ActivityFeed({ commits }: { commits: Commit[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg flex items-center gap-2">
          <GitCommit className="h-5 w-5" />
          Recent Activity
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {commits.slice(0, 8).map((commit, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <div className="w-2 h-2 mt-1.5 rounded-full bg-blue-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="truncate font-medium">{commit.message}</div>
                <div className="text-xs text-muted-foreground">
                  {commit.author} • {commit.time}
                </div>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function MissionControlPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchData = useCallback(async () => {
    try {
      const response = await fetch('/api/mission-control/status');
      if (!response.ok) throw new Error('Failed to fetch');
      const result = await response.json();
      setData(result);
      setLastRefresh(new Date());
      setError(null);
    } catch (e) {
      setError('Failed to load agent status');
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="container mx-auto p-6">
        <div className="flex items-center justify-center h-64">
          <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="container mx-auto p-6">
        <div className="flex items-center justify-center h-64 text-red-500">
          <AlertCircle className="h-6 w-6 mr-2" />
          {error || 'Failed to load'}
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            🎛️ Mission Control
          </h1>
          <p className="text-muted-foreground">
            PitchRank Agent Dashboard
          </p>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-muted-foreground">
            Last updated: {lastRefresh.toLocaleTimeString()}
          </span>
          <Button variant="outline" size="sm" onClick={fetchData}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2">
          <StatsCard stats={data.stats} />
        </div>
        <ActivityFeed commits={data.commits} />
      </div>

      {/* Agent Communications Feed */}
      <AgentCommsFeed />

      {/* Agent Grid */}
      <div>
        <h2 className="text-xl font-semibold mb-4">Agents</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {data.agents.map(agent => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      </div>
    </div>
  );
}
