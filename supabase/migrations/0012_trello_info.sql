-- Alerta Roblox - comando /info no Discord com as informacoes do Trello do Clover Retribution
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

-- Copia do Trello (atualizada sozinha pela funcao discord-bot a cada 30 minutos).
create table if not exists public.trello_listas (
  id   text primary key,
  nome text not null,
  pos  double precision
);
create table if not exists public.trello_cartoes (
  id         text primary key,
  id_lista   text not null,
  nome       text not null,
  texto      text,                          -- descricao ja convertida para o Discord (sem links do Trello)
  imagens    jsonb not null default '[]',   -- enderecos das imagens do cartao
  pos        double precision,
  short_link text
);
create index if not exists trello_cartoes_lista on public.trello_cartoes (id_lista, pos);
create table if not exists public.trello_estado (
  id                integer primary key default 1,
  atualizado_em     timestamptz,
  atualizando_desde timestamptz
);
insert into public.trello_estado (id) values (1) on conflict do nothing;

-- Canal onde o /info funciona em cada servidor (escolhido no site; sem linha = qualquer canal).
create table if not exists public.discord_info_canal (
  guild_id   text primary key,
  channel_id text not null,
  canal_nome text,
  updated_at timestamptz not null default now()
);

alter table public.trello_listas      enable row level security;
alter table public.trello_cartoes     enable row level security;
alter table public.trello_estado      enable row level security;
alter table public.discord_info_canal enable row level security;
grant all on public.trello_listas, public.trello_cartoes, public.trello_estado, public.discord_info_canal to service_role;
