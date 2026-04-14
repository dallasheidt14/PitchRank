'use client';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

// TODO: Phase 4 — replace this placeholder with the real ChatSidebar using Vercel AI SDK useChat.
export function ChatSidebar({ range: _range }: { range: DateRangePreset }) {
  return (
    <Card className="h-[calc(100vh-8rem)] flex flex-col">
      <CardHeader>
        <CardTitle className="text-base">Ask your data</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 text-sm text-muted-foreground">Chat coming soon…</CardContent>
    </Card>
  );
}
