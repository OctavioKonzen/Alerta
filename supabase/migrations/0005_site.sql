-- Alerta Roblox - site do painel do bot (entrar com Discord)
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

-- Sessoes do site. Guarda so o hash do token; so a Edge Function le esta tabela.
create table if not exists public.sessoes_web (
  token_hash text primary key,
  user_id    uuid not null references auth.users(id) on delete cascade,
  criado_em  timestamptz not null default now(),
  expira_em  timestamptz not null
);
alter table public.sessoes_web enable row level security;
grant all on public.sessoes_web to service_role;
