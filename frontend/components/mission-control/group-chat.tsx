'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Send, MessageCircle } from 'lucide-react';
import { createSupabaseBrowserClient } from '@/lib/supabaseBrowserClient';

interface ChatMessage {
  id: string;
  author: string;
  author_type: 'human' | 'agent';
  content: string;
  created_at: string;
}

const AGENT_EMOJIS: Record<string, string> = {
  orchestrator: '🎯',
  codey: '💻',
  movy: '📈',
  cleany: '🧹',
  watchy: '👁️',
  compy: '🧠',
  scrappy: '🕷️',
  ranky: '📊',
  socialy: '📱',
};

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function parseContentWithMentions(content: string): React.ReactNode {
  const mentionRegex = /@(\w+)/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match;

  while ((match = mentionRegex.exec(content)) !== null) {
    // Add text before mention
    if (match.index > lastIndex) {
      parts.push(content.slice(lastIndex, match.index));
    }
    
    // Add highlighted mention
    parts.push(
      <span
        key={match.index}
        className="bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 px-1 rounded font-medium"
      >
        {match[0]}
      </span>
    );
    
    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < content.length) {
    parts.push(content.slice(lastIndex));
  }

  return parts.length > 0 ? parts : content;
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isHuman = message.author_type === 'human';
  const agentEmoji = AGENT_EMOJIS[message.author.toLowerCase()] || '🤖';
  const [showTimestamp, setShowTimestamp] = useState(false);

  return (
    <div
      className={`flex gap-2 ${isHuman ? 'justify-end' : 'justify-start'}`}
      onMouseEnter={() => setShowTimestamp(true)}
      onMouseLeave={() => setShowTimestamp(false)}
    >
      {!isHuman && (
        <div className="flex-shrink-0 w-8 h-8 flex items-center justify-center text-xl">
          {agentEmoji}
        </div>
      )}
      
      <div className={`flex flex-col ${isHuman ? 'items-end' : 'items-start'} max-w-[80%]`}>
        <div
          className={`rounded-lg px-3 py-2 ${
            isHuman
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
          }`}
        >
          {!isHuman && (
            <div className="text-xs font-semibold mb-1 opacity-70">
              {message.author}
            </div>
          )}
          <div className="text-sm whitespace-pre-wrap break-words">
            {parseContentWithMentions(message.content)}
          </div>
        </div>
        
        {showTimestamp && (
          <div className="text-xs text-muted-foreground mt-1 px-1">
            {formatTimestamp(message.created_at)}
          </div>
        )}
      </div>

      {isHuman && (
        <div className="flex-shrink-0 w-8 h-8 flex items-center justify-center text-xl font-semibold bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-300 rounded-full">
          {message.author.slice(0, 2).toUpperCase()}
        </div>
      )}
    </div>
  );
}

export function GroupChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [newMessage, setNewMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const supabase = createSupabaseBrowserClient();

  // Scroll to bottom when messages change
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Fetch initial messages
  useEffect(() => {
    async function fetchMessages() {
      try {
        const response = await fetch('/api/chat');
        const data = await response.json();
        if (data.messages) {
          setMessages(data.messages);
        }
      } catch (e) {
        console.error('Failed to fetch messages:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchMessages();
  }, []);

  // Set up realtime subscription
  useEffect(() => {
    const channel = supabase
      .channel('mission_chat_channel')
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'mission_chat',
        },
        (payload) => {
          const newMsg = payload.new as ChatMessage;
          setMessages((prev) => [...prev, newMsg]);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!newMessage.trim() || sending) return;

    setSending(true);
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author: 'D H',
          author_type: 'human',
          content: newMessage.trim(),
        }),
      });

      if (response.ok) {
        setNewMessage('');
      } else {
        console.error('Failed to send message');
      }
    } catch (e) {
      console.error('Error sending message:', e);
    } finally {
      setSending(false);
    }
  };

  return (
    <Card className="flex flex-col h-[600px]">
      <CardHeader className="pb-3 border-b">
        <CardTitle className="text-lg flex items-center gap-2">
          <MessageCircle className="h-5 w-5" />
          💬 Mission Chat
        </CardTitle>
      </CardHeader>
      
      <CardContent className="flex-1 flex flex-col p-0">
        {/* Messages List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              Loading messages...
            </div>
          ) : messages.length === 0 ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              No messages yet. Start the conversation!
            </div>
          ) : (
            <>
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Input Box */}
        <div className="border-t p-4">
          <form onSubmit={handleSendMessage} className="flex gap-2">
            <Input
              type="text"
              placeholder="Type a message..."
              value={newMessage}
              onChange={(e) => setNewMessage(e.target.value)}
              disabled={sending}
              className="flex-1"
            />
            <Button
              type="submit"
              disabled={!newMessage.trim() || sending}
              size="icon"
            >
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </div>
      </CardContent>
    </Card>
  );
}
