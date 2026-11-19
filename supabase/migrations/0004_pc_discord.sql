-- Alerta Roblox - o programa do PC entra com a conta do Discord
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

-- Pedidos de login do PC: ainda nao se sabe de quem e (descobre pelo Discord).
alter table public.discord_estados alter column user_id drop not null;
alter table public.discord_estados add column if not exists tipo     text not null default 'app';
alter table public.discord_estados add column if not exists nome_pc  text;
alter table public.discord_estados add column if not exists pronto   boolean not null default false;
alter table public.discord_estados add column if not exists chave_pc text;
alter table public.discord_estados add column if not exists erro     text;

create index if not exists discord_contas_discord_id on public.discord_contas (discord_id);
