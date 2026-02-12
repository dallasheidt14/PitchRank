'use client';

import React from 'react';
import { AGENTS, type AgentId } from '@/lib/agent-config';
import './agent-hq.css';

interface RoleProtocolPanelProps {
  agentId: AgentId;
}

export function RoleProtocolPanel({ agentId }: RoleProtocolPanelProps) {
  const agent = AGENTS[agentId];
  
  return (
    <div className="h-full flex flex-col bg-black/40 rounded-lg border border-white/10">
      {/* Header */}
      <div className="p-4 border-b border-white/10">
        <h3 className="text-lg font-bold" style={{ color: agent.color }}>
          Role Protocol
        </h3>
        <p className="text-xs text-gray-400 mt-1">
          {agent.motto}
        </p>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto protocol-scroll p-4 space-y-6" style={{ color: agent.color }}>
        
        {/* ⚔️ Skills */}
        <div>
          <h4 className="text-sm font-bold uppercase tracking-wide mb-3 flex items-center gap-2">
            <span>⚔️</span>
            <span>Skills</span>
          </h4>
          <div className="space-y-2">
            {agent.skills.map((skill, i) => (
              <div key={i} className="text-sm text-gray-300 skill-item">
                {skill}
              </div>
            ))}
          </div>
        </div>

        {/* 📦 Equipment (Inputs → Outputs) */}
        <div>
          <h4 className="text-sm font-bold uppercase tracking-wide mb-3 flex items-center gap-2">
            <span>📦</span>
            <span>Equipment</span>
          </h4>
          
          <div className="space-y-3">
            <div>
              <p className="text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                Inputs
              </p>
              <div className="space-y-1">
                {agent.equipment.inputs.map((input, i) => (
                  <div key={i} className="text-sm text-gray-300 pl-4 border-l-2 border-blue-500/50">
                    {input}
                  </div>
                ))}
              </div>
            </div>
            
            <div className="flex items-center justify-center">
              <span className="equipment-arrow text-2xl">↓</span>
            </div>
            
            <div>
              <p className="text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                Outputs
              </p>
              <div className="space-y-1">
                {agent.equipment.outputs.map((output, i) => (
                  <div key={i} className="text-sm text-gray-300 pl-4 border-l-2 border-green-500/50">
                    {output}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* 🚫 Sealed Abilities */}
        <div>
          <h4 className="text-sm font-bold uppercase tracking-wide mb-3 flex items-center gap-2">
            <span>🚫</span>
            <span>Sealed Abilities</span>
          </h4>
          <div className="space-y-2">
            {agent.sealedAbilities.map((ban, i) => (
              <div key={i} className="text-sm sealed-ability">
                {ban}
              </div>
            ))}
          </div>
        </div>

        {/* ⚠️ Escalation */}
        <div>
          <h4 className="text-sm font-bold uppercase tracking-wide mb-3 flex items-center gap-2">
            <span>⚠️</span>
            <span>Escalation Protocol</span>
          </h4>
          <div className="space-y-2">
            {agent.escalation.map((rule, i) => (
              <div key={i} className="escalation-item text-sm text-gray-300">
                {rule}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
