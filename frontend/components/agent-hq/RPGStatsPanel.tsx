'use client';

import React from 'react';
import { AGENTS, STAT_NAMES, type AgentId, type StatType } from '@/lib/agent-config';
import './agent-hq.css';

interface RPGStatsPanelProps {
  agentId: AgentId;
  agentData?: {
    level?: number;
    statValues?: Partial<Record<StatType, number>>;
  };
}

// Per-agent stat profiles (will be replaced with real data from cron runs/learnings)
const AGENT_STAT_PROFILES: Record<AgentId, Record<StatType, number>> = {
  cleany: { ACC: 92, VOL: 78, TRU: 88, SPD: 65, WIS: 70, CRE: 45 },
  scrappy: { SPD: 94, VOL: 89, TRU: 72, ACC: 68, WIS: 55, CRE: 40 },
  ranky: { ACC: 96, WIS: 85, TRU: 90, SPD: 58, VOL: 60, CRE: 35 },
  watchy: { WIS: 88, TRU: 91, SPD: 75, ACC: 82, VOL: 50, CRE: 30 },
  codey: { CRE: 90, SPD: 82, TRU: 78, WIS: 85, ACC: 75, VOL: 65 },
  movy: { CRE: 95, VOL: 88, SPD: 80, TRU: 72, WIS: 55, ACC: 60 },
  socialy: { WIS: 86, CRE: 82, TRU: 75, SPD: 68, ACC: 70, VOL: 55 },
  compy: { WIS: 94, TRU: 88, CRE: 76, SPD: 62, ACC: 80, VOL: 45 },
};

// Per-agent levels based on "experience" (runs + learnings)
const AGENT_LEVELS: Record<AgentId, number> = {
  cleany: 8,
  scrappy: 7,
  ranky: 9,
  watchy: 6,
  codey: 12,
  movy: 5,
  socialy: 4,
  compy: 7,
};

// Mock stat calculation based on runs/learnings (will be replaced with real data)
function calculateStatValue(agentId: AgentId, stat: StatType, agentData?: RPGStatsPanelProps['agentData']): number {
  if (agentData?.statValues?.[stat]) {
    return agentData.statValues[stat];
  }
  
  // Use per-agent profile
  return AGENT_STAT_PROFILES[agentId][stat] || 50;
}

function calculateLevel(agentId: AgentId, agentData?: RPGStatsPanelProps['agentData']): number {
  if (agentData?.level) {
    return agentData.level;
  }
  
  // Use per-agent level (based on runs + learnings)
  return AGENT_LEVELS[agentId] || 5;
}

export function RPGStatsPanel({ agentId, agentData }: RPGStatsPanelProps) {
  const agent = AGENTS[agentId];
  const level = calculateLevel(agentId, agentData);
  
  return (
    <div className="space-y-6 p-6 bg-black/40 rounded-lg border border-white/10">
      {/* Agent class & level */}
      <div className="space-y-2">
        <h3 className="text-2xl font-bold" style={{ color: agent.color }}>
          {agent.name}
        </h3>
        <p className="text-sm text-gray-400 uppercase tracking-wide">
          {agent.role}
        </p>
        <div className="level-badge" style={{ color: agent.color }}>
          LV.{level}
        </div>
      </div>

      {/* Stat bars */}
      <div className="space-y-4">
        <h4 className="text-xs uppercase tracking-wider text-gray-500 font-bold">
          Agent Statistics
        </h4>
        {agent.stats.map((stat) => {
          const value = calculateStatValue(agentId, stat, agentData);
          const fullName = STAT_NAMES[stat];
          
          return (
            <div key={stat} className="space-y-1">
              <div className="flex justify-between items-center text-xs">
                <span className="text-gray-400 uppercase font-bold tracking-wide">
                  {fullName}
                </span>
                <span className="text-gray-300 font-mono">
                  {value}/100
                </span>
              </div>
              <div className="stat-bar-container">
                <div
                  className="stat-bar-fill"
                  style={{
                    width: `${value}%`,
                    color: agent.color,
                  }}
                >
                  <span className="stat-bar-label">{stat}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Model info */}
      <div className="pt-4 border-t border-white/10">
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-400">Model:</span>
          <span className="font-mono font-bold" style={{ color: agent.color }}>
            {agent.model}
          </span>
        </div>
        <div className="flex items-center justify-between text-sm mt-2">
          <span className="text-gray-400">Schedule:</span>
          <span className="text-gray-300 text-xs">{agent.schedule}</span>
        </div>
      </div>
    </div>
  );
}
