create table if not exists public.analytics_chat_logs (
  id            bigserial primary key,
  created_at    timestamptz not null default now(),
  turn_id       uuid not null,
  user_email    text not null,
  model_name    text not null,
  user_question text not null,
  inherited_date_range jsonb,
  overridden_date_range jsonb,
  tool_name     text not null,
  tool_args     jsonb not null,
  tool_result_summary jsonb,
  tool_call_hash text not null,
  force_fresh   boolean not null default false,
  cost_units    integer,
  execution_ms  integer,
  success       boolean not null,
  error_type    text,
  error_message text,
  final_answer  text
);

create index if not exists analytics_chat_logs_created_at_idx
  on public.analytics_chat_logs (created_at desc);

create index if not exists analytics_chat_logs_user_email_idx
  on public.analytics_chat_logs (user_email);

create index if not exists analytics_chat_logs_turn_id_idx
  on public.analytics_chat_logs (turn_id);

-- No RLS policies: this table is server-write only via service role.
alter table public.analytics_chat_logs enable row level security;
-- Deny all default policies = no client access via anon key.
