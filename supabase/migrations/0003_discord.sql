-- Alerta Roblox - bot do Discord (alertas num canal de servidor)
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

-- Conta do Discord ligada a cada conta do app (login com Discord).
-- Guarda os tokens do Discord: so a Edge Function (chave de servico) le esta tabela.
create table public.discord_contas (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  discord_id    text not null,
  nome          text,
  access_token  text not null,
  refresh_token text not null,
  expira_em     timestamptz not null,
  updated_at    timestamptz not null default now()
);
alter table public.discord_contas enable row level security;

-- Pedidos de login com Discord em andamento (valem 10 minutos).
create table public.discord_estados (
  estado    text primary key,
  user_id   uuid not null references auth.users(id) on delete cascade,
  expira_em timestamptz not null
);
alter table public.discord_estados enable row level security;

-- Canal escolhido em cada servidor do Discord (um por servidor, por conta).
create table public.discord_canais (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  guild_id    text not null,
  guild_nome  text,
  channel_id  text not null,
  canal_nome  text,
  created_at  timestamptz not null default now(),
  unique (user_id, guild_id)
);
alter table public.discord_canais enable row level security;
create policy "ver meus canais"    on public.discord_canais for select using (auth.uid() = user_id);
create policy "apagar meus canais" on public.discord_canais for delete using (auth.uid() = user_id);

grant select, delete on public.discord_canais to authenticated;
grant all on public.discord_contas, public.discord_estados, public.discord_canais to service_role;
