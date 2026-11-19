-- Alerta Roblox - canal por SERVIDOR (so o administrador escolhe) e membros participam
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

-- Canal de alertas de cada servidor do Discord (escolhido por um administrador).
create table if not exists public.discord_servidores (
  guild_id        text primary key,
  guild_nome      text,
  channel_id      text not null,
  canal_nome      text,
  configurado_por uuid references auth.users(id) on delete set null,
  updated_at      timestamptz not null default now()
);
alter table public.discord_servidores enable row level security;
grant all on public.discord_servidores to service_role;

-- Quem manda os proprios alertas para o canal de cada servidor (qualquer membro).
create table if not exists public.discord_participantes (
  user_id    uuid not null references auth.users(id) on delete cascade,
  guild_id   text not null references public.discord_servidores(guild_id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, guild_id)
);
alter table public.discord_participantes enable row level security;
grant all on public.discord_participantes to service_role;

-- Traz o que ja estava configurado no formato antigo (discord_canais).
insert into public.discord_servidores (guild_id, guild_nome, channel_id, canal_nome, configurado_por, updated_at)
select distinct on (guild_id) guild_id, guild_nome, channel_id, canal_nome, user_id, created_at
from public.discord_canais
order by guild_id, created_at desc
on conflict (guild_id) do nothing;

insert into public.discord_participantes (user_id, guild_id)
select user_id, guild_id from public.discord_canais
on conflict do nothing;
