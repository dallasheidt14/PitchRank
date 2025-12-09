-- Migration: Create user_profiles table for Supabase Auth integration
-- This table syncs with auth.users to store additional user data

-- Create user_profiles table
create table if not exists public.user_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  plan text default 'free' check (plan in ('free', 'premium', 'admin')),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Add index on email for lookups
create index if not exists idx_user_profiles_email on public.user_profiles(email);

-- Add index on plan for filtering
create index if not exists idx_user_profiles_plan on public.user_profiles(plan);

-- Enable RLS
alter table public.user_profiles enable row level security;

-- Policy: Users can view their own profile
create policy "Users can view own profile"
  on public.user_profiles for select
  using (auth.uid() = id);

-- Policy: Users can update their own profile
create policy "Users can update own profile"
  on public.user_profiles for update
  using (auth.uid() = id);

-- Policy: Allow insert during user creation (handled by trigger)
create policy "Enable insert for authenticated users"
  on public.user_profiles for insert
  with check (auth.uid() = id);

-- Function to handle new user creation
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.user_profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$ language plpgsql security definer;

-- Trigger to automatically create profile when user signs up
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Function to update updated_at timestamp
create or replace function public.handle_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- Trigger for updated_at
drop trigger if exists on_user_profiles_updated on public.user_profiles;
create trigger on_user_profiles_updated
  before update on public.user_profiles
  for each row execute function public.handle_updated_at();

-- Grant permissions
grant usage on schema public to anon, authenticated;
grant select on public.user_profiles to anon, authenticated;
grant insert, update on public.user_profiles to authenticated;

-- Comment on table
comment on table public.user_profiles is 'Stores additional user profile data, synced with auth.users';
comment on column public.user_profiles.plan is 'User subscription plan: free, premium, or admin';
