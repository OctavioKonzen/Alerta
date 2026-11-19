-- Alerta Roblox - frases procuradas ficam na conta (editaveis no app, no site e no PC)
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

create table if not exists public.frases (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  texto      text not null check (char_length(trim(texto)) between 3 and 120),
  created_at timestamptz not null default now()
);
create index if not exists frases_user on public.frases (user_id, created_at);
alter table public.frases enable row level security;
create policy "ver minhas frases"    on public.frases for select using (auth.uid() = user_id);
create policy "criar minhas frases"  on public.frases for insert with check (auth.uid() = user_id);
create policy "apagar minhas frases" on public.frases for delete using (auth.uid() = user_id);
grant select, insert, delete on public.frases to authenticated;
grant all on public.frases to service_role;

-- Contas que ja receberam as frases padrao (para nao recolocar se a pessoa apagar todas).
create table if not exists public.frases_iniciadas (
  user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.frases_iniciadas enable row level security;
grant all on public.frases_iniciadas to service_role;

-- No maximo 30 frases por conta; tira espacos das pontas.
create or replace function public.limite_frases()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if (select count(*) from public.frases where user_id = new.user_id) >= 30 then
    raise exception 'limite de 30 frases por conta';
  end if;
  new.texto := trim(new.texto);
  return new;
end;
$$;
drop trigger if exists frases_limite on public.frases;
create trigger frases_limite before insert on public.frases
for each row execute function public.limite_frases();

-- Na primeira vez, coloca as frases padrao.
create or replace function public.garantir_frases(p_user uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.frases_iniciadas (user_id) values (p_user) on conflict do nothing;
  if found then
    insert into public.frases (user_id, texto)
    values (p_user, 'Something feels off'), (p_user, 'A strange energy is felt');
  end if;
end;
$$;
revoke all on function public.garantir_frases(uuid) from public, anon, authenticated;
grant execute on function public.garantir_frases(uuid) to service_role;

-- Usada pelo app: devolve as frases da conta logada (colocando as padrao na 1a vez).
create or replace function public.minhas_frases()
returns setof public.frases
language plpgsql
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'nao autenticado';
  end if;
  perform public.garantir_frases(auth.uid());
  return query select * from public.frases where user_id = auth.uid() order by created_at, id;
end;
$$;
revoke all on function public.minhas_frases() from public, anon;
grant execute on function public.minhas_frases() to authenticated;
