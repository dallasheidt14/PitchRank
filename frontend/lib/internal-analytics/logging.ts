import 'server-only';
import { createClient, SupabaseClient } from '@supabase/supabase-js';
import { createHash, randomUUID } from 'node:crypto';
import type { TaxonomyError } from './types';

let _adminClient: SupabaseClient | null = null;

function adminClient(): SupabaseClient {
  if (_adminClient) return _adminClient;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) throw new Error('Supabase admin client env vars missing');
  _adminClient = createClient(url, key, { auth: { persistSession: false } });
  return _adminClient;
}

export function newTurnId(): string {
  return randomUUID();
}

export function hashToolCall(toolName: string, args: unknown): string {
  const normalized = JSON.stringify(args, Object.keys(args ?? {}).sort());
  return createHash('sha256').update(`${toolName}:${normalized}`).digest('hex');
}

export type ChatToolLogInput = {
  turn_id: string;
  user_email: string;
  model_name: string;
  user_question: string;
  inherited_date_range: unknown;
  overridden_date_range: unknown;
  tool_name: string;
  tool_args: unknown;
  tool_result_summary: unknown;
  force_fresh: boolean;
  cost_units?: number | null;
  execution_ms: number;
  success: boolean;
  error?: TaxonomyError | null;
  final_answer?: string | null;
};

export async function logChatToolCall(input: ChatToolLogInput): Promise<void> {
  const row = {
    turn_id: input.turn_id,
    user_email: input.user_email,
    model_name: input.model_name,
    user_question: input.user_question,
    inherited_date_range: input.inherited_date_range,
    overridden_date_range: input.overridden_date_range,
    tool_name: input.tool_name,
    tool_args: input.tool_args,
    tool_result_summary: input.tool_result_summary,
    tool_call_hash: hashToolCall(input.tool_name, input.tool_args),
    force_fresh: input.force_fresh,
    cost_units: input.cost_units ?? null,
    execution_ms: input.execution_ms,
    success: input.success,
    error_type: input.error?.type ?? null,
    error_message: input.error?.message ?? null,
    final_answer: input.final_answer ?? null,
  };

  const { error } = await adminClient().from('analytics_chat_logs').insert(row);
  if (error) console.error('[analytics] chat-log insert failed:', error.message);
}
