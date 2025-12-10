-- Add Stripe subscription fields to user_profiles table
-- This migration adds columns to track Stripe customer and subscription data

-- Add stripe_customer_id column
alter table public.user_profiles
add column if not exists stripe_customer_id text;

-- Add stripe_subscription_id column
alter table public.user_profiles
add column if not exists stripe_subscription_id text;

-- Add subscription_status column
alter table public.user_profiles
add column if not exists subscription_status text;

-- Add subscription_period_end to track when subscription expires
alter table public.user_profiles
add column if not exists subscription_period_end timestamptz;

-- Create index on stripe_customer_id for webhook lookups
create index if not exists idx_user_profiles_stripe_customer_id
on public.user_profiles(stripe_customer_id);

-- Add comment for documentation
comment on column public.user_profiles.stripe_customer_id is 'Stripe customer ID for billing';
comment on column public.user_profiles.stripe_subscription_id is 'Active Stripe subscription ID';
comment on column public.user_profiles.subscription_status is 'Current subscription status (active, canceled, past_due, etc.)';
comment on column public.user_profiles.subscription_period_end is 'When the current subscription period ends';
