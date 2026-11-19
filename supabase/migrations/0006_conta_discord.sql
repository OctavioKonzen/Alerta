-- Alerta Roblox - entrar com Discord cria a conta automaticamente
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

-- Acha a conta pelo e-mail (usado so pela Edge Function, para contas criadas pelo Discord).
create or replace function public.usuario_por_email(p_email text)
returns uuid
language sql
security definer
set search_path = ''
as $$
  select id from auth.users where lower(email) = lower(p_email) limit 1;
$$;
revoke all on function public.usuario_por_email(text) from public, anon, authenticated;
grant execute on function public.usuario_por_email(text) to service_role;
