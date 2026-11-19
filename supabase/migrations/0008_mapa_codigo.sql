-- Alerta Roblox - o alerta passa a levar o mapa (Normal/Jungle) e o codigo do servidor
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

alter table public.alerts add column if not exists mapa            text;
alter table public.alerts add column if not exists codigo_servidor text;
