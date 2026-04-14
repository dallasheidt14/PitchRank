import { streamText, convertToModelMessages, stepCountIs, type UIMessage, isTextUIPart } from 'ai';
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

  const body = await req.json();
  const { messages, range = 'last_7_days' } = body as {
    messages: UIMessage[];
    range?: DateRangePreset;
  };

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
