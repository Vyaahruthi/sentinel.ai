  -- REQUIRED EXTENSION
create extension if not exists pgcrypto;

--------------------------------------------------
-- 1. OBSERVATIONS (raw parameter values)
--------------------------------------------------
create table sentinel_observations (
  id uuid default gen_random_uuid() primary key,
  timestamp timestamptz default now() not null,
  junction_id text not null,
  parameter text not null,
  value float not null,
  raw_context jsonb
);

create index idx_sobs_junc_param_time
on sentinel_observations (junction_id, parameter, timestamp desc);

--------------------------------------------------
-- 2. BASELINES (rolling mean/std)
--------------------------------------------------
create table sentinel_baselines (
  id uuid default gen_random_uuid() primary key,
  computed_at timestamptz default now() not null,
  junction_id text not null,
  parameter text not null,
  mean float not null,
  std float not null,
  sample_size int not null,
  window_start timestamptz,
  window_end timestamptz
);

create index idx_sbl_junc_param
on sentinel_baselines (junction_id, parameter, computed_at desc);

--------------------------------------------------
-- 3. DRIFT EVENTS (core alerts)
--------------------------------------------------
create table drift_events (
  id uuid default gen_random_uuid() primary key,
  detected_at timestamptz default now() not null,
  junction_id text not null,
  parameter text not null,
  current_value float,
  baseline_mean float,
  baseline_std float,
  z_score float,
  confidence float,
  tier int not null check (tier in (1,2,3)),
  reason text,
  combination_id uuid,
  resolved_at timestamptz,
  status text default 'active'
);

create index idx_de_junc_time
on drift_events (junction_id, detected_at desc);

--------------------------------------------------
-- 4. DRIFT MEMORY (timeline replay)
--------------------------------------------------
create table drift_memory (
  id uuid default gen_random_uuid() primary key,
  event_id uuid references drift_events(id),
  junction_id text not null,
  parameter text not null,
  snapshot jsonb not null,
  memory_type text not null,
  recorded_at timestamptz default now() not null
);

create index idx_dm_junc_param_time
on drift_memory (junction_id, parameter, recorded_at asc);

--------------------------------------------------
-- 5. COMBINATION ALERTS (multi-drift)
--------------------------------------------------
create table combination_alerts (
  id uuid default gen_random_uuid() primary key,
  detected_at timestamptz default now() not null,
  junction_id text not null,
  parameters text[] not null,
  individual_z_scores jsonb,
  combined_score float,
  escalated_tier int check (escalated_tier in (1,2,3)),
  reason text,
  status text default 'active'
);

--------------------------------------------------
-- 6. AUTONOMY LOG (AI + Human decisions)
--------------------------------------------------
create table autonomy_log (
  id uuid default gen_random_uuid() primary key,
  event_id uuid references drift_events(id),
  junction_id text not null,
  tier int not null check (tier in (1,2,3)),
  ai_decision text,
  ai_confidence float,
  human_decision text,
  human_reviewer text,
  reviewed_at timestamptz,
  status text default 'pending',
  notes text,
  created_at timestamptz default now() not null
);

create index idx_al_status_time
on autonomy_log (status, created_at desc);
