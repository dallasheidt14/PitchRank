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

// Mock stat calculation based on runs/learnings (will be replaced with real data)
function calculateStatValue(agentId: AgentId, stat: StatType, agentData?: RPGStatsPanelProps['agentData']): number {
  if (agentData?.statValues?.[stat]) {
    return agentData.statValues[stat];
  }
  
  // Default mock values based on agent primary stats
  const agent = AGENTS[agentId];
  const statIndex = agent.stats.indexOf(stat);
  
  if (statIndex === 0) return 85; // Primary stat
  if (statIndex === 1) return 72; // Secondary stat
  if (statIndex === 2) return 68; // Tertiary stat
  if (statIndex === 3) return 55; // Quaternary stat
  
  return 50; // Default
}

function calculateLevel(agentId: AgentId, agentData?: RPGStatsPanelProps['agentData']): number {
  if (agentData?.level) {
    return agentData.level;
  }
  
  // Mock level calculation (will be based on runs + learnings)
  return Math.floor(Math.random() * 5) + 3; // LV.3-7 for now
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
