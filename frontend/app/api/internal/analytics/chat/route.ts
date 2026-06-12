import { streamText, convertToModelMessages, stepCountIs, type UIMessage, isTextUIPart } from 'ai';
import { NextResponse } from 'next/server';
import { anthropic } from '@ai-sdk/anthropic';
import { requireAdmin } from '@/lib/supabase/admin';
import { resolveDateRange } from '@/lib/internal-analytics/dates';
import { buildTools } from '@/lib/internal-analytics/chat/tools';
import { buildSystemPrompt } from '@/lib/internal-analytics/chat/system-prompt';
import { newTurnId } from '@/lib/internal-analytics/logging';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

export const runtime = 'nodejs';
export const maxDuration = 60;
export const dynamic = 'force-dynamic';

const FRESH_INTENT = /\b(today|right now|just now|this minute|this hour)\b/i;

export async function POST(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  // Reject oversized payloads before req.json() buffers and parses them
  const contentLength = Number(req.headers.get('content-length'));
  if (Number.isFinite(contentLength) && contentLength > 500_000) {
    return NextResponse.json({ error: 'Payload too large — start a new conversation' }, { status: 413 });
  }

  const body = await req.json();
  const { messages, range = 'last_7_days' } = body as {
    messages: UIMessage[];
    range?: DateRangePreset;
  };

  // Bound the payload before it reaches the model — unbounded histories are
  // pure token-cost amplification on this endpoint
  if (!Array.isArray(messages) || messages.length === 0) {
    return NextResponse.json({ error: 'messages array is required' }, { status: 400 });
  }
  if (messages.length > 50) {
    return NextResponse.json({ error: 'Too many messages — start a new conversation' }, { status: 400 });
  }
  const totalChars = messages.reduce(
    (sum, m) => sum + (m.parts ?? []).reduce((s, p) => s + (isTextUIPart(p) ? p.text.length : 0), 0),
    0
  );
  if (totalChars > 100_000) {
    return NextResponse.json({ error: 'Conversation too large — start a new conversation' }, { status: 400 });
  }

  const lastMessage = messages[messages.length - 1];
  const lastContent = lastMessage?.parts?.find(isTextUIPart)?.text ?? '';
  const forceFresh = FRESH_INTENT.test(lastContent);

  const inheritedRange = resolveDateRange(range, 'America/Phoenix');
  const turnId = newTurnId();
  const userEmail = auth.user.email ?? 'unknown@pitchrank.io';
  const modelName = 'claude-sonnet-4-6';

  const tools = buildTools({
    turnId,
    userEmail,
    modelName,
    question: lastContent,
    inheritedRange,
    forceFresh,
  });

  const modelMessages = await convertToModelMessages(messages);

  const result = await streamText({
    model: anthropic(modelName),
    system: buildSystemPrompt(inheritedRange),
    messages: modelMessages,
    tools,
    stopWhen: stepCountIs(5),
  });

  return result.toUIMessageStreamResponse();
}
