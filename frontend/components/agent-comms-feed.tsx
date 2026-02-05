'use client';

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { RefreshCw, MessageSquare, ChevronDown, ChevronUp } from 'lucide-react';

interface AgentMessage {
  timestamp: string;
  agentName: string;
  agentEmoji: string;
  messagePreview: string;
  fullMessage: string;
  sessionId: string;
}

interface AgentActivityResponse {
  messages: AgentMessage[];
  count: number;
  timestamp: string;
}

function MessageBubble({ message }: { message: AgentMessage }) {
  const [expanded, setExpanded] = useState(false);
  const time = new Date(message.timestamp);
  const timeStr = time.toLocaleTimeString('en-US', { 
    hour: 'numeric', 
    minute: '2-digit',
    hour12: true 
  });
  const dateStr = time.toLocaleDateString('en-US', { 
    month: 'short', 
    day: 'numeric' 
  });

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg hover:bg-muted/50 transition-colors">
      {/* Agent Avatar */}
      <div className="flex-shrink-0">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-xl">
          {message.agentEmoji}
        </div>
      </div>

      {/* Message Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="font-semibold text-sm">{message.agentName}</span>
          <span className="text-xs text-muted-foreground">
            {dateStr} at {timeStr}
          </span>
        </div>

        {/* Message Text */}
        <div className="text-sm text-foreground/90">
          {expanded ? (
            <div className="whitespace-pre-wrap">{message.fullMessage}</div>
          ) : (
            <div>{message.messagePreview}</div>
          )}
        </div>

        {/* Expand/Collapse Button */}
        {message.fullMessage.length > message.messagePreview.length && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 mt-1 flex items-center gap-1"
          >
            {expanded ? (
              <>
                <ChevronUp className="h-3 w-3" />
                Show less
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" />
                Show more
              </>
            )}
          </button>
        )}

        {/* Session Badge */}
        <div className="mt-2">
          <Badge variant="outline" className="text-xs">
            Session: {message.sessionId.substring(0, 8)}
          </Badge>
        </div>
      </div>
    </div>
  );
}

export function AgentCommsFeed() {
  const [data, setData] = useState<AgentActivityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchActivity = async () => {
    try {
      const response = await fetch('/api/agent-activity');
      if (!response.ok) throw new Error('Failed to fetch');
      const result = await response.json();
      setData(result);
      setError(null);
    } catch (e) {
      setError('Failed to load agent communications');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchActivity();
    const interval = setInterval(fetchActivity, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            🤖 Agent Communications
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-32">
            <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            🤖 Agent Communications
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground text-center py-8">
            {error || 'No messages found'}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            🤖 Agent Communications
          </CardTitle>
          <Badge variant="secondary">{data.count} messages</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-1 max-h-[600px] overflow-y-auto">
          {data.messages.length === 0 ? (
            <div className="text-sm text-muted-foreground text-center py-8">
              No agent messages yet
            </div>
          ) : (
            data.messages.map((msg, idx) => (
              <MessageBubble key={`${msg.sessionId}-${msg.timestamp}-${idx}`} message={msg} />
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}
