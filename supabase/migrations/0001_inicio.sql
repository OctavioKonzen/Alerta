-- Alerta Roblox - banco de dados (Supabase)
-- Rode no Supabase: SQL Editor > New query > cole tudo > Run

create extension if not exists pgcrypto with schema extensions;

-- PCs ligados a cada conta. A chave em si nunca e guardada, so o hash.
create table public.pc_keys (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  nome         text not null check (char_length(nome) between 1 and 40),
  key_hash     text not null unique,
  prefixo      text not null,
  created_at   timestamptz not null default now(),
  last_used_at timestamptz
);
alter table public.pc_keys enable row level security;
create policy "ver meus pcs"    on public.pc_keys for select using (auth.uid() = user_id);
create policy "apagar meus pcs" on public.pc_keys for delete using (auth.uid() = user_id);

-- Celulares que recebem notificacao de cada conta.
create table public.push_tokens (
  token      text primary key,
  user_id    uuid not null references auth.users(id) on delete cascade,
  updated_at timestamptz not null default now()
);
alter table public.push_tokens enable row level security;
create policy "ver meus celulares"    on public.push_tokens for select using (auth.uid() = user_id);
create policy "apagar meus celulares" on public.push_tokens for delete using (auth.uid() = user_id);

-- Historico de alertas.
create table public.alerts (
  id         bigint generated always as identity primary key,
  user_id    uuid not null references auth.users(id) on delete cascade,
  pc_id      uuid references public.pc_keys(id) on delete set null,
  frase      text,
  mensagem   text,
  jogador    text,
  job_id     text,
  place_id   text,
  link       text,
  teste      boolean not null default false,
  created_at timestamptz not null default now()
);
create index alerts_user_data on public.alerts (user_id, created_at desc);
alter table public.alerts enable row level security;
create policy "ver meus alertas"    on public.alerts for select using (auth.uid() = user_id);
create policy "apagar meus alertas" on public.alerts for delete using (auth.uid() = user_id);

-- Alertas novos aparecem na hora no app (tempo real).
alter publication supabase_realtime add table public.alerts;

-- Cria a chave de um PC. Chamada pelo "python monitor.py conectar".
create or replace function public.criar_chave_pc(p_nome text)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_chave text;
  v_qtd   int;
begin
  if auth.uid() is null then
    raise exception 'nao autenticado';
  end if;
  select count(*) into v_qtd from public.pc_keys where user_id = auth.uid();
  if v_qtd >= 5 then
    raise exception 'limite de 5 PCs por conta. Remova um PC no app.';
  end if;
  v_chave := 'rbx_' || encode(extensions.gen_random_bytes(24), 'hex');
  insert into public.pc_keys (user_id, nome, key_hash, prefixo)
  values (auth.uid(),
          left(coalesce(nullif(trim(p_nome), ''), 'PC'), 40),
          encode(extensions.digest(v_chave, 'sha256'), 'hex'),
          left(v_chave, 10));
  return v_chave;
end;
$$;
revoke all on function public.criar_chave_pc(text) from public, anon;
grant execute on function public.criar_chave_pc(text) to authenticated;

-- Registra o celular na conta logada (se o celular era de outra conta, passa para esta).
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
  if p_token !~ '^Expo(nent)?PushToken\[[A-Za-z0-9_-]+\]$' then
    raise exception 'token invalido';
  end if;
  insert into public.push_tokens (token, user_id)
  values (p_token, auth.uid())
  on conflict (token) do update set user_id = excluded.user_id, updated_at = now();
end;
$$;
revoke all on function public.registrar_token(text) from public, anon;
grant execute on function public.registrar_token(text) to authenticated;

-- Guarda so os 200 alertas mais recentes de cada conta.
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
              order by id desc offset 199 limit 1);
  return null;
end;
$$;
create trigger alerts_limpeza after insert on public.alerts
for each row execute function public.limpar_alertas_antigos();
