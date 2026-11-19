-- Alerta Roblox - corrige o registro do celular para notificacoes
-- (o erro "invalid regular expression: invalid repetition count(s)" no app)
-- O Postgres nao aceita {50,500} numa expressao (o maximo e 255): o tamanho
-- passa a ser conferido a parte.
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

create or replace function public.registrar_token(p_token text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'nao autenticado';
  end if;
  if p_token is null
     or char_length(p_token) not between 50 and 500
     or p_token !~ '^[A-Za-z0-9_:-]+$' then
    raise exception 'token invalido';
  end if;
  insert into public.push_tokens (token, user_id)
  values (p_token, auth.uid())
  on conflict (token) do update set user_id = excluded.user_id, updated_at = now();
end;
$$;
revoke all on function public.registrar_token(text) from public, anon;
grant execute on function public.registrar_token(text) to authenticated;
