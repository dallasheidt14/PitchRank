'use client';
import { useMemo, useState } from 'react';
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport, isTextUIPart, isToolUIPart } from 'ai';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { DateContextChip } from './DateContextChip';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

export function ChatSidebar({ range }: { range: DateRangePreset }) {
  const [input, setInput] = useState('');

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: '/api/internal/analytics/chat',
        body: { range },
      }),

    [range]
  );

  const { messages, sendMessage, status } = useChat({ transport });
  const isLoading = status === 'submitted' || status === 'streaming';

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || isLoading) return;
    setInput('');
    sendMessage({ text });
  }

  return (
    <Card className="h-[calc(100vh-8rem)] flex flex-col">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Ask your data</CardTitle>
        <DateContextChip range={range} />
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto space-y-3 text-sm">
        {messages.map((m) => (
          <div key={m.id} className={m.role === 'user' ? 'text-foreground' : 'text-muted-foreground'}>
            <div className="font-medium text-xs uppercase opacity-60">{m.role}</div>
            {m.parts.map((part, i) => {
              if (isTextUIPart(part)) {
                return (
                  <div key={i} className="whitespace-pre-wrap">
                    {part.text}
                  </div>
                );
              }
              if (isToolUIPart(part)) {
                const toolName = part.type.replace(/^tool-/, '');
                return (
                  <details key={i} className="mt-1 text-xs">
                    <summary className="cursor-pointer">🔍 {toolName}</summary>
                    <pre className="text-xs overflow-x-auto">{JSON.stringify(part.input, null, 2)}</pre>
                  </details>
                );
              }
              return null;
            })}
          </div>
        ))}
      </CardContent>
      <form onSubmit={handleSubmit} className="p-3 border-t flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about traffic, queries, conversions…"
          disabled={isLoading}
        />
        <Button type="submit" disabled={isLoading || !input.trim()}>
          Send
        </Button>
      </form>
    </Card>
  );
}
