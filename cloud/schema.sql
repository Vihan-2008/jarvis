-- Isolated private tables. Only the authenticated Edge Function service role
-- can read or write; browser publishable keys cannot retrieve vault contents.
create extension if not exists vector with schema extensions;
create table if not exists public.jarvis_chunks (
  path text not null,
  ordinal integer not null check (ordinal >= 0),
  digest text not null,
  content text not null check (length(content) <= 1600),
  embedding extensions.vector(384) not null,
  updated_at timestamptz not null default now(),
  primary key(path, ordinal)
);
alter table public.jarvis_chunks enable row level security;
revoke all on public.jarvis_chunks from public, anon, authenticated;
grant all on public.jarvis_chunks to service_role;
create or replace function public.jarvis_match(query_embedding extensions.vector(384), match_count integer default 6)
returns table(path text, ordinal integer, content text, similarity double precision)
language sql stable security invoker set search_path = public, extensions
as $$
  select c.path, c.ordinal, c.content, 1 - (c.embedding <=> query_embedding)
  from public.jarvis_chunks c
  order by c.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 8)
$$;
revoke all on function public.jarvis_match(extensions.vector,integer) from public, anon, authenticated;
grant execute on function public.jarvis_match(extensions.vector,integer) to service_role;
