-- Alerta Roblox - aceita o token do Firebase (o app manda direto, sem Expo)
-- Rode no Supabase: SQL Editor > cole tudo > Run

create or replace function public.registrar_token(p_token text)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'nao autenticado'; end if;
  if p_token !~ '^[A-Za-z0-9_:-]{50,500}$' then raise exception 'token invalido'; end if;
  insert into public.push_tokens (token, user_id) values (p_token, auth.uid())
  on conflict (token) do update set user_id = excluded.user_id, updated_at = now();
end;
$$;
revoke all on function public.registrar_token(text) from public, anon;
grant execute on function public.registrar_token(text) to authenticated;
