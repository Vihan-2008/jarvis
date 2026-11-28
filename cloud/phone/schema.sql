-- JARVIS phone app: the relay's own tables, in the owner's own Supabase project.
-- Only the relay (the Edge Function's service role) can read or write them. Message text, transcripts, files and push
-- subscriptions are stored sealed (AES-GCM, with a key only the relay holds). Nothing here is readable with the
-- project's publishable keys. Messages waiting for the laptop are deleted once the laptop has them; everything else
-- goes after 7 days at the latest.

create table if not exists public.ph_state (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- Every message id seen (made by the phone), so a message sent twice is handled once. Ids only, kept 7 days.
create table if not exists public.ph_seen (
  id text primary key,
  at timestamptz not null default now()
);

-- Messages waiting for the laptop: new, taken by the laptop, answered here while it was off, or waiting for it.
create table if not exists public.ph_inbox (
  id text primary key,
  at timestamptz not null default now(),
  status text not null default 'new' check (status in ('new', 'taken', 'offline', 'deferred')),
  claimed_at timestamptz,
  body text not null
);

-- What was said while the laptop was off, until the laptop has copied it into the Phone chat note.
create table if not exists public.ph_offlog (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  body text not null
);

-- The Phone chat as the phone shows it: the last 50 messages, 7 days at most. The status of the owner's own messages
-- (received, with_computer, answered_here, queued, done, failed) is not secret and is kept beside the sealed body.
create table if not exists public.ph_transcript (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  msg_id text unique,
  role text not null check (role in ('user', 'assistant', 'notice')),
  status text,
  body text not null
);

-- Paired phones: each has its own Ed25519 public key. The laptop enrols them; the relay never enrols one by itself.
create table if not exists public.ph_phones (
  id text primary key,
  name text not null,
  public_key text not null,
  added timestamptz not null default now(),
  last_seen timestamptz,
  push text,
  revoked boolean not null default false
);

-- Files (sealed, in the private Storage bucket "phone-files"): their sizes, for the 200 MB total and the 7-day rule.
create table if not exists public.ph_files (
  id text primary key,
  at timestamptz not null default now(),
  size bigint not null,
  name text not null default '',
  mime text not null default 'application/octet-stream'
);

do $$
declare t text;
begin
  foreach t in array array['ph_state', 'ph_seen', 'ph_inbox', 'ph_offlog', 'ph_transcript', 'ph_phones', 'ph_files'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;
grant usage, select on all sequences in schema public to service_role;

-- The private bucket for files. Storage policies are not needed: only the service role ever touches it.
insert into storage.buckets (id, name, public) values ('phone-files', 'phone-files', false) on conflict (id) do nothing;

-- The laptop takes up to `most` waiting messages, oldest first. A message taken by a laptop that then went away is
-- offered again after ten minutes. Two callers never get the same message.
create or replace function public.ph_take(most integer default 5)
returns setof public.ph_inbox
language sql security invoker set search_path = public
as $$
  update public.ph_inbox set status = 'taken', claimed_at = now()
  where id in (
    select id from public.ph_inbox
    where status in ('new', 'deferred') or (status = 'taken' and claimed_at < now() - interval '10 minutes')
    order by at
    limit least(greatest(most, 1), 10)
    for update skip locked
  )
  returning *
$$;

-- Counts one use against a limit for a period ('2026-11-28' for a key's day, '2026-11-28T14' for an hour).
-- Returns the new count, or -1 when the limit is reached: nothing is counted then, and the use must not happen.
create or replace function public.ph_bump(counter text, period text, most integer)
returns integer
language plpgsql security invoker set search_path = public
as $$
declare used integer;
begin
  insert into public.ph_state(key, value) values (counter, jsonb_build_object('period', period, 'n', 0))
  on conflict (key) do nothing;
  select case when value->>'period' = period then coalesce((value->>'n')::int, 0) else 0 end into used
  from public.ph_state where key = counter for update;
  if used >= most then
    return -1;
  end if;
  update public.ph_state set value = jsonb_build_object('period', period, 'n', used + 1), updated_at = now() where key = counter;
  return used + 1;
end $$;

-- The transcript keeps its last `keep` messages.
create or replace function public.ph_trim(keep integer default 50)
returns void
language sql security invoker set search_path = public
as $$
  delete from public.ph_transcript where id <= (select coalesce(max(id), 0) - greatest(keep, 1) from public.ph_transcript);
$$;

-- Old rows go: anything after 7 days. (Old files' objects are deleted by the relay, which lists them first.)
create or replace function public.ph_tidy()
returns void
language sql security invoker set search_path = public
as $$
  delete from public.ph_seen where at < now() - interval '7 days';
  delete from public.ph_inbox where at < now() - interval '7 days';
  delete from public.ph_offlog where at < now() - interval '7 days';
  delete from public.ph_transcript where at < now() - interval '7 days';
  delete from public.ph_state where key like 'ask:%' and updated_at < now() - interval '1 day';
$$;

revoke all on function public.ph_take(integer) from public, anon, authenticated;
revoke all on function public.ph_bump(text, text, integer) from public, anon, authenticated;
revoke all on function public.ph_trim(integer) from public, anon, authenticated;
revoke all on function public.ph_tidy() from public, anon, authenticated;
grant execute on function public.ph_take(integer) to service_role;
grant execute on function public.ph_bump(text, text, integer) to service_role;
grant execute on function public.ph_trim(integer) to service_role;
grant execute on function public.ph_tidy() to service_role;
