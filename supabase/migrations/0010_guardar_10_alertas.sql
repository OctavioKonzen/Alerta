-- Alerta Roblox - guarda so os 10 alertas mais recentes de cada conta (antes eram 200)
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

create or replace function public.limpar_alertas_antigos()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  delete from public.alerts
  where user_id = new.user_id
    and id < (select id from public.alerts where user_id = new.user_id
              order by id desc offset 9 limit 1);
  return null;
end;
$$;

-- Apaga agora o que passou de 10 em cada conta.
delete from public.alerts a
using (
  select id, row_number() over (partition by user_id order by id desc) as pos
  from public.alerts
) r
where a.id = r.id and r.pos > 10;
