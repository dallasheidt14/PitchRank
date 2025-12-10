-- Migration: Create watchlists and watchlist_items tables for Premium feature
-- Part of Step 3: Premium Supabase-Backed Watchlists + Custom Team Insight Engine

-- Create watchlists table
create table if not exists public.watchlists (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text default 'My Watchlist',
  is_default boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Create watchlist_items table
create table if not exists public.watchlist_items (
  id uuid primary key default gen_random_uuid(),
  watchlist_id uuid not null references public.watchlists(id) on delete cascade,
  team_id_master uuid not null,
  created_at timestamptz default now(),
  unique (watchlist_id, team_id_master)
);

-- Create indexes for performance
create index if not exists idx_watchlists_user_id on public.watchlists(user_id);
create index if not exists idx_watchlists_user_default on public.watchlists(user_id, is_default) where is_default = true;
create index if not exists idx_watchlist_items_watchlist_id on public.watchlist_items(watchlist_id);
create index if not exists idx_watchlist_items_team_id on public.watchlist_items(team_id_master);

-- Enable Row Level Security
alter table public.watchlists enable row level security;
alter table public.watchlist_items enable row level security;

-- RLS Policy: Users can manage their own watchlists
create policy "Users manage their watchlists"
on public.watchlists for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

-- RLS Policy: Users can manage items in their own watchlists
create policy "Users manage their watchlist items"
on public.watchlist_items for all
using (
  exists (
    select 1 from public.watchlists
    where watchlists.id = watchlist_items.watchlist_id
    and watchlists.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1 from public.watchlists
    where watchlists.id = watchlist_items.watchlist_id
    and watchlists.user_id = auth.uid()
  )
);

-- Trigger to update updated_at timestamp
create or replace function public.update_watchlists_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger watchlists_updated_at
  before update on public.watchlists
  for each row
  execute function public.update_watchlists_updated_at();

-- Grant permissions
grant select, insert, update, delete on public.watchlists to authenticated;
grant select, insert, update, delete on public.watchlist_items to authenticated;

comment on table public.watchlists is 'Premium user watchlists for tracking teams';
comment on table public.watchlist_items is 'Teams in user watchlists';
