'use client';

import React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { GripVertical, MessageSquare } from 'lucide-react';

// Agent emoji mapping
const AGENT_EMOJIS: Record<string, string> = {
  cleany: '🧹',
  watchy: '👀',
  compy: '🧠',
  scrappy: '🕷️',
  ranky: '📊',
  movy: '🎬',
  codey: '💻',
  socialy: '📱',
  orchestrator: '🎛️',
};

const PRIORITY_STYLES = {
  low: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  medium: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  high: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
};

export interface TaskCardProps {
  id: string;
  title: string;
  description?: string | null;
  assigned_agent?: string | null;
  priority: 'low' | 'medium' | 'high';
  commentCount?: number;
  onClick?: () => void;
  onDragStart?: (e: React.DragEvent) => void;
  onDragEnd?: (e: React.DragEvent) => void;
}

export function TaskCard({
  id,
  title,
  description,
  assigned_agent,
  priority,
  commentCount = 0,
  onClick,
  onDragStart,
  onDragEnd,
}: TaskCardProps) {
  const agentEmoji = assigned_agent ? AGENT_EMOJIS[assigned_agent.toLowerCase()] || '🤖' : null;

  return (
    <Card
      draggable
      className="cursor-pointer hover:shadow-md transition-shadow group"
      onClick={onClick}
      onDragStart={(e) => {
        e.dataTransfer.setData('taskId', id);
        onDragStart?.(e);
      }}
      onDragEnd={onDragEnd}
    >
      <CardContent className="p-3">
        <div className="flex items-start gap-2">
          {/* Drag handle */}
          <GripVertical className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 mt-0.5" />
          
          <div className="flex-1 min-w-0">
            {/* Title */}
            <h4 className="font-medium text-sm leading-tight mb-1 line-clamp-2">
              {title}
            </h4>
            
            {/* Description preview */}
            {description && (
              <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
                {description}
              </p>
            )}
            
            {/* Footer with badges */}
            <div className="flex items-center justify-between gap-2 mt-2">
              <div className="flex items-center gap-1.5">
                {/* Priority badge */}
                <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${PRIORITY_STYLES[priority]}`}>
                  {priority}
                </Badge>
                
                {/* Assigned agent */}
                {assigned_agent && (
                  <span className="text-sm flex items-center gap-1" title={assigned_agent}>
                    {agentEmoji}
                    <span className="text-[10px] text-muted-foreground capitalize">
                      {assigned_agent}
                    </span>
                  </span>
                )}
              </div>
              
              {/* Comment count */}
              {commentCount > 0 && (
                <div className="flex items-center gap-0.5 text-muted-foreground">
                  <MessageSquare className="h-3 w-3" />
                  <span className="text-[10px]">{commentCount}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
