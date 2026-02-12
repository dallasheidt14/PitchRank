'use client';

import React from 'react';
import { AGENTS, type AgentId } from '@/lib/agent-config';
import './agent-hq.css';

interface AgentPortraitProps {
  agentId: AgentId;
  status?: 'active' | 'idle' | 'error';
  lastRun?: string | null;
  nextRun?: string | null;
}

export function AgentPortrait({ 
  agentId, 
  status = 'idle', 
  lastRun, 
  nextRun 
}: AgentPortraitProps) {
  const agent = AGENTS[agentId];
  
  const statusConfig = {
    active: {
      label: 'Active',
      color: '#10B981',
      dotClass: 'active',
    },
    idle: {
      label: 'Idle',
      color: '#6B7280',
      dotClass: 'idle',
    },
    error: {
      label: 'Error',
      color: '#EF4444',
      dotClass: 'error',
    },
  };
  
  const currentStatus = statusConfig[status];
  
  return (
    <div className="flex flex-col items-center justify-center p-8 space-y-6 bg-black/40 rounded-lg border border-white/10 crt-overlay">
      {/* Agent portrait with glow */}
      <div className="relative agent-portrait">
        <div 
          className="agent-portrait-glow" 
          style={{ 
            color: agent.color,
          }} 
        />
        <div 
          className="text-9xl select-none"
          style={{
            filter: `drop-shadow(0 0 20px ${agent.color})`,
          }}
        >
          {agent.emoji}
        </div>
      </div>

      {/* Agent name */}
      <div className="text-center space-y-2">
        <h2 className="text-4xl font-bold rpg-header" style={{ color: agent.color }}>
          {agent.name}
        </h2>
        <p className="text-sm text-gray-400 italic max-w-md">
          "{agent.motto}"
        </p>
      </div>

      {/* Status indicator */}
      <div className="flex items-center gap-3 px-6 py-3 bg-black/60 rounded-full border border-white/10">
        <span className={`status-dot ${currentStatus.dotClass}`} />
        <span className="text-sm font-bold uppercase tracking-wide" style={{ color: currentStatus.color }}>
          {currentStatus.label}
        </span>
      </div>

      {/* Run times */}
      <div className="w-full max-w-md space-y-2 text-sm">
        {lastRun && (
          <div className="flex items-center justify-between px-4 py-2 bg-black/40 rounded border border-white/10">
            <span className="text-gray-400">Last run:</span>
            <span className="text-gray-200 font-mono text-xs">{lastRun}</span>
          </div>
        )}
        {nextRun && (
          <div className="flex items-center justify-between px-4 py-2 bg-black/40 rounded border border-white/10">
            <span className="text-gray-400">Next run:</span>
            <span className="text-gray-200 font-mono text-xs">{nextRun}</span>
          </div>
        )}
      </div>
    </div>
  );
}
