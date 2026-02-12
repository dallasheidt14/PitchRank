'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { RefreshCw } from 'lucide-react';
import { AgentSelectBar } from '@/components/agent-hq/AgentSelectBar';
import { RPGStatsPanel } from '@/components/agent-hq/RPGStatsPanel';
import { RoleProtocolPanel } from '@/components/agent-hq/RoleProtocolPanel';
import { AgentPortrait } from '@/components/agent-hq/AgentPortrait';
import { AGENTS, type AgentId } from '@/lib/agent-config';
import '@/components/agent-hq/agent-hq.css';

interface AgentStatusData {
  status: 'active' | 'idle' | 'error';
  lastRun: string | null;
  nextRun: string | null;
  level?: number;
  statValues?: Record<string, number>;
}

interface DashboardData {
  agents: Record<AgentId, AgentStatusData>;
  timestamp: string;
}

export default function MissionControlPage() {
  const [selectedAgent, setSelectedAgent] = useState<AgentId>('codey');
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchData = useCallback(async () => {
    try {
      const response = await fetch('/api/mission-control/status');
      if (!response.ok) {
        // If the API doesn't exist yet, use mock data
        if (response.status === 404) {
          console.log('API not found, using mock data');
          setData(createMockData());
          setLastRefresh(new Date());
          setError(null);
          setLoading(false);
          return;
        }
        throw new Error('Failed to fetch');
      }
      const result = await response.json();
      setData(result);
      setLastRefresh(new Date());
      setError(null);
    } catch (e) {
      console.error('Failed to load agent status, using mock data:', e);
      // Fallback to mock data
      setData(createMockData());
      setLastRefresh(new Date());
      setError(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [fetchData]);

  // Mock data generator for testing
  function createMockData(): DashboardData {
    const mockAgents: Record<AgentId, AgentStatusData> = {
      cleany: {
        status: 'idle',
        lastRun: '2 hours ago',
        nextRun: 'Sunday 7pm MT',
        level: 5,
      },
      scrappy: {
        status: 'active',
        lastRun: '10 minutes ago',
        nextRun: 'Tomorrow 6am MT',
        level: 7,
      },
      ranky: {
        status: 'idle',
        lastRun: 'Yesterday 12pm',
        nextRun: 'Monday 12pm MT',
        level: 6,
      },
      watchy: {
        status: 'idle',
        lastRun: '5 hours ago',
        nextRun: 'Tomorrow 8am MT',
        level: 4,
      },
      codey: {
        status: 'idle',
        lastRun: '3 days ago',
        nextRun: 'On-demand',
        level: 8,
      },
      movy: {
        status: 'idle',
        lastRun: 'Yesterday 10am',
        nextRun: 'Tuesday 10am MT',
        level: 5,
      },
      socialy: {
        status: 'idle',
        lastRun: 'Yesterday 9am',
        nextRun: 'Wednesday 9am MT',
        level: 4,
      },
      compy: {
        status: 'idle',
        lastRun: 'Last night 10:30pm',
        nextRun: 'Tonight 10:30pm MT',
        level: 6,
      },
    };
    
    return {
      agents: mockAgents,
      timestamp: new Date().toISOString(),
    };
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-black flex items-center justify-center">
        <RefreshCw className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  const agent = AGENTS[selectedAgent];
  const agentStatus = data?.agents?.[selectedAgent] || {
    status: 'idle' as const,
    lastRun: null,
    nextRun: null,
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-black text-white">
      <div className="container mx-auto p-6 space-y-6">
        
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 
              className="text-5xl font-bold rpg-header mb-2"
              style={{ color: agent.color }}
            >
              PITCHRANK AGENT HQ
            </h1>
            <p className="text-gray-400 text-sm uppercase tracking-wide">
              RPG Command Center • Phase 1 - 2D
            </p>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-400">
              Last updated: {lastRefresh.toLocaleTimeString()}
            </span>
            <Button 
              variant="outline" 
              size="sm" 
              onClick={fetchData}
              className="border-gray-600 hover:border-gray-400"
            >
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
          </div>
        </div>

        {/* Main Content Grid */}
        <div className="grid grid-cols-12 gap-6" style={{ minHeight: '600px' }}>
          
          {/* Left: Stats Panel */}
          <div className="col-span-12 lg:col-span-3">
            <RPGStatsPanel 
              agentId={selectedAgent} 
              agentData={{
                level: agentStatus.level,
                statValues: agentStatus.statValues,
              }}
            />
          </div>

          {/* Center: Agent Portrait */}
          <div className="col-span-12 lg:col-span-6">
            <AgentPortrait
              agentId={selectedAgent}
              status={agentStatus.status}
              lastRun={agentStatus.lastRun}
              nextRun={agentStatus.nextRun}
            />
          </div>

          {/* Right: Role Protocol Panel */}
          <div className="col-span-12 lg:col-span-3" style={{ minHeight: '500px' }}>
            <RoleProtocolPanel agentId={selectedAgent} />
          </div>
        </div>

        {/* Bottom: Agent Select Bar */}
        <AgentSelectBar 
          selectedAgent={selectedAgent}
          onSelectAgent={setSelectedAgent}
        />

        {/* Footer info */}
        <div className="text-center text-xs text-gray-500 pt-4 border-t border-gray-800">
          <p>Agent data refreshes automatically every 30 seconds</p>
          <p className="mt-1">3D portraits and advanced stats coming in Phase 2 🎮</p>
        </div>
      </div>
    </div>
  );
}
