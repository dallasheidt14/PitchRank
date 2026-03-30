-- Add cancel_at_period_end flag to track pending cancellations
-- When a user cancels via Stripe Customer Portal, status stays "active"
-- but cancel_at_period_end becomes true. Without this flag, the dashboard
-- shows them as a happy paid subscriber when they've actually cancelled.

alter table public.user_profiles
  add column if not exists cancel_at_period_end boolean not null default false;

comment on column public.user_profiles.cancel_at_period_end is
  'True when user has cancelled but subscription remains active until period end';
