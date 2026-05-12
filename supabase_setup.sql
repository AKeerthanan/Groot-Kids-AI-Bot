-- ============================================================
--  Groot AI — Supabase Schema Setup  (Safe Re-runnable)
--  Run this in: Supabase Dashboard → SQL Editor → Run
--  Safe to run multiple times — uses IF NOT EXISTS + DROP IF EXISTS
-- ============================================================

-- ── 1. USERS ──────────────────────────────────────────────────────────────────
create table if not exists public.users (
  id            uuid default gen_random_uuid() primary key,
  username      text not null unique,
  email         text not null unique,
  password_hash text not null,
  age           int  default 8,
  created_at    timestamptz default now()
);

-- ── 2. USER MEMORY  (Groot remembers name, age, pet, hobbies…) ───────────────
create table if not exists public.user_memory (
  id         uuid default gen_random_uuid() primary key,
  user_id    uuid references public.users(id) on delete cascade,
  key        text not null,
  value      text,
  updated_at timestamptz default now(),
  unique(user_id, key)
);

-- ── 3. CHAT HISTORY ───────────────────────────────────────────────────────────
create table if not exists public.chat_history (
  id         uuid default gen_random_uuid() primary key,
  user_id    uuid references public.users(id) on delete cascade,
  message    text,
  reply      text,
  image_url  text,
  video_url  text,
  link_url   text,
  extra_data text,
  created_at timestamptz default now()
);

create index if not exists idx_chat_history_user_id
  on public.chat_history(user_id, created_at desc);

-- ── 4. TRAINING QUEUE ─────────────────────────────────────────────────────────
create table if not exists public.training_queue (
  id          uuid default gen_random_uuid() primary key,
  user_id     uuid references public.users(id) on delete set null,
  username    text,
  question    text not null,
  answer      text,
  topic       text default 'general',
  source      text default 'unknown',
  status      text default 'pending'
              check (status in ('pending','approved','rejected')),
  reviewed_at timestamptz,
  created_at  timestamptz default now()
);

-- ── 5. ADMINS ─────────────────────────────────────────────────────────────────
create table if not exists public.admins (
  id            uuid default gen_random_uuid() primary key,
  username      text not null unique,
  password_hash text not null,
  created_at    timestamptz default now()
);

-- ── DEFAULT ADMIN  (password: admin123) ───────────────────────────────────────
insert into public.admins (username, password_hash)
values (
  'admin',
  '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9'
)
on conflict (username) do nothing;

-- ── ROW-LEVEL SECURITY ────────────────────────────────────────────────────────
alter table public.users          enable row level security;
alter table public.user_memory    enable row level security;
alter table public.chat_history   enable row level security;
alter table public.training_queue enable row level security;
alter table public.admins         enable row level security;

-- Drop existing policies first (prevents "already exists" errors on re-run)
drop policy if exists "service_all_users"     on public.users;
drop policy if exists "service_all_memory"    on public.user_memory;
drop policy if exists "service_all_chat"      on public.chat_history;
drop policy if exists "service_all_training"  on public.training_queue;
drop policy if exists "service_all_admins"    on public.admins;

-- Recreate policies (backend service role gets full access)
create policy "service_all_users"
  on public.users for all using (true) with check (true);

create policy "service_all_memory"
  on public.user_memory for all using (true) with check (true);

create policy "service_all_chat"
  on public.chat_history for all using (true) with check (true);

create policy "service_all_training"
  on public.training_queue for all using (true) with check (true);

create policy "service_all_admins"
  on public.admins for all using (true) with check (true);
