'use client';

import React from 'react';
import { AGENTS, AGENT_ORDER, type AgentId } from '@/lib/agent-config';
import './agent-hq.css';

interface AgentSelectBarProps {
  selectedAgent: AgentId;
  onSelectAgent: (agentId: AgentId) => void;
}

export function AgentSelectBar({ selectedAgent, onSelectAgent }: AgentSelectBarProps) {
  return (
    <div className="flex items-center justify-center gap-4 p-4 bg-black/40 rounded-lg border border-white/10">
      {AGENT_ORDER.map((agentId) => {
        const agent = AGENTS[agentId];
        const isSelected = selectedAgent === agentId;
        
        return (
          <button
            key={agentId}
            onClick={() => onSelectAgent(agentId)}
            className={`agent-select-btn ${isSelected ? 'selected' : 'unselected'}`}
            style={{ 
              color: agent.color,
              borderColor: isSelected ? agent.color : 'transparent',
            }}
            title={agent.name}
          >
            <div className="flex flex-col items-center gap-1">
              <span className="text-4xl transition-transform" style={{ 
                filter: isSelected ? 'none' : 'grayscale(80%)',
                transform: isSelected ? 'scale(1.1)' : 'scale(1)',
              }}>
                {agent.emoji}
              </span>
              <span className="text-xs font-bold uppercase" style={{
                color: isSelected ? agent.color : '#6B7280',
              }}>
                {agent.name}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
