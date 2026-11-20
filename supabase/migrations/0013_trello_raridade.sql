-- Alerta Roblox - guarda a raridade (etiqueta do Trello) de cada item do /info
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

alter table public.trello_cartoes add column if not exists raridade text;
